"""MMMU generation driver; the CPU path uses deterministic synthetic outputs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any

import yaml

if __package__:
    from .common import (build_messages, build_prompt, check_invariants, load_samples, make_record,
                         select_smoke, validate_record)
else:
    from common import (build_messages, build_prompt, check_invariants, load_samples, make_record,
                        select_smoke, validate_record)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TokenCounter:
    def count(self, sample, prompt: str, messages: list[dict], ordinal: int, cfg: dict) -> int:
        raise NotImplementedError


class FakeTokenCounter(TokenCounter):
    """The third selected sample deliberately exceeds the configured input bound."""

    def count(self, sample, prompt: str, messages: list[dict], ordinal: int, cfg: dict) -> int:
        bound = (cfg["budget"]["max_model_len"] - cfg["budget"]["max_new_tokens"]
                 - cfg["budget"]["prompt_safety_margin"])
        return bound + 1 if ordinal == 2 else len(prompt.split())


class Engine:
    def generate(self, requests: list[dict]) -> list[dict | Exception]:
        raise NotImplementedError


class FakeEngine(Engine):
    """Synthetic only: selected positions 1, 2, 3 mean length, skip, error."""

    def __init__(self, stop_after_chunks: int | None = None, mismatch_ordinal: int | None = None):
        self.calls: list[list[str]] = []
        self.stop_after_chunks = stop_after_chunks
        self.mismatch_ordinal = mismatch_ordinal

    def generate(self, requests: list[dict]) -> list[dict | Exception]:
        self.calls.append([request["sample"].id for request in requests])
        outputs = []
        for request in requests:
            ordinal = request["ordinal"]
            if ordinal == 3:
                outputs.append(RuntimeError(f"synthetic failure for {request['sample'].id}"))
                continue
            length = ordinal == 1
            max_tokens = request["cfg"]["budget"]["max_new_tokens"]
            token_ids = [ordinal] * max_tokens if length else [ordinal]
            outputs.append({"raw_text": f"synthetic:{request['sample'].id}",
                            "output_token_ids": token_ids,
                            "finish_reason": "length" if length else "stop", "stop_reason": None,
                            "num_prompt_tokens": request["precomputed"] +
                            (1 if ordinal == self.mismatch_ordinal else 0)})
        return outputs


class VLLMEngine(Engine):
    def __init__(self, cfg: dict, model_path: str, revision: str):
        raise NotImplementedError("VLLMEngine is implemented in the next step")


def git_info() -> dict:
    def run(*args):
        try:
            result = subprocess.run(["git", *args], cwd=Path(__file__).resolve().parent,
                                    capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = run("rev-parse", "HEAD")
    dirty = run("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit or "unknown", "dirty": bool(dirty) if dirty is not None else "unknown"}


def recover_raw(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    lines = raw.splitlines(keepends=True)
    records = []
    valid_bytes = 0
    for index, line in enumerate(lines):
        try:
            if not line.endswith(b"\n"):
                raise ValueError("line has no final newline")
            record = json.loads(line)
            validate_record(record)
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            if index != len(lines) - 1:
                raise ValueError(f"invalid raw line {index + 1} before last line")
            torn = path.with_name(path.name + ".torn")
            torn.write_bytes(line)
            with path.open("r+b") as stream:
                stream.truncate(valid_bytes)
            print(f"Recovered torn final line to {torn}")
            break
        records.append(record)
        valid_bytes += len(line)
    return records


def resume_state(raw_path: Path, env_path: Path, selected: list, config_sha256: str,
                 dry_run: bool, limit: int | None, subjects: list[str] | None) -> list[dict]:
    if raw_path.exists() and not env_path.exists():
        raise ValueError("raw file exists without environment metadata")
    if env_path.exists():
        env = json.loads(env_path.read_text(encoding="utf-8"))
        if env.get("config_sha256") != config_sha256:
            raise ValueError("config_sha256 mismatch")
        if env.get("dry_run") is not dry_run:
            raise ValueError("dry_run mode mismatch")
        if env.get("limit") != limit:
            raise ValueError("limit mismatch")
        if env.get("subjects") != subjects:
            raise ValueError("subjects mismatch")
    records = recover_raw(raw_path)
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate id in raw file")
    selected_ids = {sample.id for sample in selected}
    foreign = set(ids) - selected_ids
    if foreign:
        raise ValueError(f"raw contains ids outside selection: {sorted(foreign)}")
    return records


def write_env(path: Path, env: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(env, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def print_summary(records: list[dict], mismatches: int, code_commits: list[str]) -> int:
    statuses = Counter(record["status"] for record in records)
    finishes = Counter(record["finish_reason"] for record in records if record["finish_reason"] is not None)
    skips = Counter(record["reason"] for record in records if record["status"] == "skip")
    tokens = sorted(record["output_tokens"] for record in records if record["output_tokens"] is not None)
    distribution = ({"min": tokens[0], "median": statistics.median(tokens),
                     "p90": tokens[math.ceil(len(tokens) * 0.9) - 1], "max": tokens[-1]}
                    if tokens else "unknown")
    lengths = defaultdict(list)
    for record in records:
        if record["finish_reason"] == "length":
            lengths[record["subject"]].append(record["id"])
    violations = sum(len(check_invariants(record)) for record in records)
    print("status:", dict(statuses))
    print("finish_reason:", dict(finishes))
    print("output_tokens:", distribution)
    print("skip reasons:", dict(skips), "errors:", statuses["error"])
    print("length ids:", dict(lengths))
    print("invariant violations:", violations, "token mismatches:", mismatches)
    print("code_commits:", code_commits)
    return 2 if statuses["error"] or violations else 0


def run_pipeline(cfg: dict, config_bytes: bytes, out: Path, samples: list,
                 model_path: str, revision: str, data_root: str | None, dry_run: bool,
                 limit: int | None = None, subjects: list[str] | None = None,
                 engine: Engine | None = None, counter: TokenCounter | None = None,
                 invocation_args: dict | None = None) -> int:
    if not dry_run and not cfg["prompt"]["verified"]:
        raise ValueError("prompt source is unverified")
    if limit is not None:
        samples = select_smoke(samples, limit)
    if len({sample.id for sample in samples}) != len(samples):
        raise ValueError("duplicate sample id")
    out.mkdir(parents=True, exist_ok=True)
    raw_path = out / cfg["run"]["raw_filename"]
    env_path = out / cfg["run"]["env_filename"]
    digest = hashlib.sha256(config_bytes).hexdigest()
    records = resume_state(raw_path, env_path, samples, digest, dry_run, limit, subjects)
    prior = json.loads(env_path.read_text(encoding="utf-8")) if env_path.exists() else None
    current_git = git_info()
    if prior and prior.get("invocations"):
        previous_git = prior["invocations"][-1].get("git", {})
        previous_commit = previous_git.get("commit", "unknown")
        if previous_commit != current_git["commit"]:
            print(f"WARNING: code commit changed since previous invocation: "
                  f"{previous_commit} -> {current_git['commit']}")
    env = prior or {"schema_version": cfg["schema"]["version"], "config": cfg,
                    "config_sha256": digest, "model": {"repo": cfg["model"]["repo_id"],
                    "revision": revision, "path": model_path},
                    "dataset": {"repo": cfg["dataset"]["repo_id"], "revision": cfg["dataset"]["revision"]},
                    "partial": limit is not None or subjects is not None, "dry_run": dry_run,
                    "limit": limit, "subjects": subjects,
                    "git_first": current_git, "invocations": []}
    started = time.monotonic()
    invocation = {"started_at": utc_now(), "finished_at": None, "duration_seconds": None,
                  "git": current_git,
                  "args": invocation_args or {"model_path": model_path, "revision": revision,
                                                 "data_root": data_root, "out": str(out),
                                                 "dry_run": dry_run, "limit": limit, "subjects": subjects}}
    env["invocations"].append(invocation)
    write_env(env_path, env)
    if dry_run:
        counter = counter or FakeTokenCounter()
        engine = engine or FakeEngine()
    else:
        if counter is None:
            if __package__:
                from .inputs import HFTokenCounter, resolve_model_dir
            else:
                from inputs import HFTokenCounter, resolve_model_dir
            model_path = str(resolve_model_dir(model_path, revision, weights=False))
            counter = HFTokenCounter(Path(model_path), cfg)
        engine = engine or VLLMEngine(cfg, model_path, revision)
    done = {record["id"] for record in records}
    pending = [(ordinal, sample) for ordinal, sample in enumerate(samples) if sample.id not in done]
    chunk_size = cfg["run"]["chunk_size"]
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    max_input = (cfg["budget"]["max_model_len"] - cfg["budget"]["max_new_tokens"]
                 - cfg["budget"]["prompt_safety_margin"])
    mismatches = 0
    try:
        with raw_path.open("a", encoding="utf-8") as stream:
            for chunk_number, offset in enumerate(range(0, len(pending), chunk_size), 1):
                chunk = pending[offset:offset + chunk_size]
                prepared = []
                requests = []
                for ordinal, sample in chunk:
                    images = sample.images()
                    prompt = build_prompt(sample, cfg)
                    messages = build_messages(sample, cfg, images)
                    precomputed = counter.count(sample, prompt, messages, ordinal, cfg)
                    base = make_record(sample, cfg, synthetic=dry_run,
                                       image_indices=sorted(sample.image_indices),
                                       precomputed_prompt_tokens=precomputed)
                    if precomputed > max_input:
                        if hasattr(counter, "pop_prepared"):
                            counter.pop_prepared(sample.id)
                        prepared.append((base | {"status": "skip", "reason": "prompt_too_long"}, None))
                    else:
                        request = {"sample": sample, "ordinal": ordinal, "prompt": prompt,
                                   "messages": messages, "images": images, "precomputed": precomputed, "cfg": cfg}
                        if hasattr(counter, "pop_prepared"):
                            request["prepared"] = counter.pop_prepared(sample.id)
                        prepared.append((base, request))
                        requests.append(request)
                outputs = engine.generate(requests) if requests else []
                if len(outputs) != len(requests):
                    raise AssertionError("engine returned wrong number of outputs")
                output_iter = iter(outputs)
                chunk_records = []
                for base, request in prepared:
                    if request is None:
                        record = base
                    else:
                        output = next(output_iter)
                        if isinstance(output, Exception):
                            record = base | {"status": "error", "error": repr(output)}
                        else:
                            measured = output["num_prompt_tokens"]
                            if measured != request["precomputed"]:
                                mismatches += 1
                            record = base | {"status": "ok", "raw_text": output["raw_text"],
                                             "output_token_ids": output["output_token_ids"],
                                             "output_tokens": len(output["output_token_ids"]),
                                             "finish_reason": output["finish_reason"],
                                             "stop_reason": output["stop_reason"],
                                             "num_prompt_tokens": measured}
                    validate_record(record)
                    chunk_records.append(record)
                if mismatches:
                    raise AssertionError(f"precomputed prompt token mismatch in chunk {chunk_number}")
                for record in chunk_records:
                    stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                records.extend(chunk_records)
                if isinstance(engine, FakeEngine) and engine.stop_after_chunks == chunk_number:
                    raise RuntimeError(f"synthetic interruption after chunk {chunk_number}")
    finally:
        invocation["finished_at"] = utc_now()
        invocation["duration_seconds"] = round(time.monotonic() - started, 3)
        write_env(env_path, env)
    code_commits = list(dict.fromkeys(item.get("git", {}).get("commit", "unknown")
                                      for item in env["invocations"]))
    return print_summary(records, mismatches, code_commits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model_path")
    parser.add_argument("--revision")
    parser.add_argument("--data_root")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry_run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--subjects")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("limit must be nonnegative")
    config_bytes = args.config.read_bytes()
    cfg = yaml.safe_load(config_bytes)
    model_path = args.model_path or cfg["model"]["repo_id"]
    revision = args.revision or cfg["model"]["revision"]
    subjects = [part.strip() for part in args.subjects.split(",")] if args.subjects else None
    if not args.dry_run and not cfg["prompt"]["verified"]:
        parser.error("prompt source is unverified")
    samples = load_samples(cfg, args.data_root, subjects)
    return run_pipeline(cfg, config_bytes, args.out, samples, model_path, revision, args.data_root,
                        args.dry_run, args.limit, subjects,
                        invocation_args={key: str(value) if isinstance(value, Path) else value
                                         for key, value in vars(args).items()})


if __name__ == "__main__":
    raise SystemExit(main())

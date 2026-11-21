"""Validate the last full D1 checkpoint, then reuse the pilot merge and load."""

import argparse
import json
import tarfile

import d1_pilot_artifacts as artifacts


ROOT = artifacts.ROOT
REPORTS = ROOT / "reports/full"
FULL = ROOT / "artifacts/full"
CHECKPOINT = FULL / "checkpoint-90"
MERGED = ROOT / "artifacts/merged_full"


def verify():
    evidence = json.loads((ROOT / "reports/input_verification.json").read_bytes())
    for name, digest in evidence["files"].items():
        assert artifacts.sha(ROOT / name) == digest, name
    for row in evidence["images"]:
        path = artifacts.IMAGES / row["path"]
        assert path.stat().st_size == row["bytes"] and artifacts.sha(path) == row["sha256"], row["path"]
    assert len(evidence["images"]) == 548
    assert evidence["model_revision"] == artifacts.CONFIG["model_revision"]
    assert {path.name: path.stat().st_size for path in artifacts.BASE.glob("model-*.safetensors")} == evidence["model_shards"]
    artifacts.save(REPORTS / "input_verification.json", evidence)


def merge():
    state = json.loads((CHECKPOINT / "trainer_state.json").read_bytes())
    args = json.loads((FULL / "args.json").read_bytes())
    assert state["global_step"] == state["max_steps"] == 90 and state["epoch"] == 2
    assert args["max_steps"] == -1 and args["num_train_epochs"] == 2
    assert args["model_revision"] == artifacts.CONFIG["model_revision"]
    assert not args["adapters"] and not args["ref_adapters"] and args["ref_model"] is None
    assert args["resume_from_checkpoint"] is None
    assert sorted(path.name for path in FULL.glob("checkpoint-*")) == [CHECKPOINT.name]
    artifacts.merge()


def package():
    paths = {f"reports/{path.name}": path for path in REPORTS.iterdir() if path.is_file() and path.suffix != ".gz"}
    paths.update({f"reports/{name}": FULL / name for name in ("args.json", "logging.jsonl", "full_observations.jsonl")})
    paths.update({f"adapter/{path.relative_to(CHECKPOINT).as_posix()}": path for path in CHECKPOINT.rglob("*") if path.is_file()})
    sums = ROOT / "d1_full_sha256.json"
    artifacts.save(sums, {name: artifacts.sha(path) for name, path in paths.items()})
    archive = ROOT / "d1_full_results.tar.gz"
    with tarfile.open(archive, "x:gz", compresslevel=1) as handle:
        for name, path in paths.items():
            handle.add(path, arcname=name, recursive=False)
        handle.add(sums, arcname="artifact_sha256.json")
    print("ARCHIVE_SHA256", artifacts.sha(archive), archive.stat().st_size, flush=True)


if __name__ == "__main__":
    artifacts.REPORTS, artifacts.CHECKPOINT, artifacts.MERGED = REPORTS, CHECKPOINT, MERGED
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("verify", "merge", "load", "package"))
    {"verify": verify, "merge": merge, "load": artifacts.load, "package": package}[parser.parse_args().step]()

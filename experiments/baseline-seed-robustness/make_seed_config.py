#!/usr/bin/env python3
"""Derive a config from code/config.yaml that differs ONLY in the generation seeds.

Text-level substitution (comments preserved), then a parsed-dict diff proves that
nothing except sampling.seed / sampling.engine_seed changed. The scoring.judge.seed
(also 3407) is deliberately never touched.
"""
import argparse, json, re, sys
from pathlib import Path
import yaml

ALLOWED = {("sampling", "seed"), ("sampling", "engine_seed")}


def rewrite(text: str, sampling_seed: int, engine_seed: int) -> str:
    out, top, hits = [], None, {"seed": 0, "engine_seed": 0}
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#") and line.rstrip().endswith(":"):
            top = line.rstrip()[:-1]
        elif top == "sampling":
            m = re.match(r"^(  )(seed|engine_seed)(:\s*)\d+(.*)$", line)
            if m:
                val = sampling_seed if m.group(2) == "seed" else engine_seed
                line = f"{m.group(1)}{m.group(2)}{m.group(3)}{val}{m.group(4)}"
                hits[m.group(2)] += 1
        out.append(line)
    if hits != {"seed": 1, "engine_seed": 1}:
        sys.exit(f"ERROR: expected exactly one sampling.seed and one sampling.engine_seed line, got {hits}")
    return "\n".join(out) + "\n"


def flat(d, prefix=()):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from flat(v, prefix + (k,))
        else:
            yield prefix + (k,), v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, default=Path("code/config.yaml"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sampling-seed", type=int, required=True)
    ap.add_argument("--engine-seed", type=int, required=True)
    a = ap.parse_args()
    base_text = a.base.read_text(encoding="utf-8")
    new_text = rewrite(base_text, a.sampling_seed, a.engine_seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(new_text, encoding="utf-8")
    b, n = dict(flat(yaml.safe_load(base_text))), dict(flat(yaml.safe_load(new_text)))
    changed = {".".join(k): [b[k], n[k]] for k in b if b[k] != n.get(k)}
    illegal = [k for k in changed if tuple(k.split(".")) not in ALLOWED]
    if illegal or set(b) != set(n):
        sys.exit(f"ERROR: unexpected config differences: {illegal}")
    a.out.with_suffix(".diff.json").write_text(json.dumps({"base": str(a.base), "changed": changed}, indent=1) + "\n")
    print(json.dumps({"out": str(a.out), "changed": changed}))


if __name__ == "__main__":
    main()

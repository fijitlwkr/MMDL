"""Freeze held-out D1 pairs and a seeded D3 v2 training probe without rewriting inputs."""

import json
import random

from classify_answers import ROOT, read_rows
from d3_prepare_v2 import verify_inputs
from sample_m0 import sha


DEV_PAIRS = ROOT / "data/d3_dev_pairs_swift.jsonl"
DEV_INDEX = ROOT / "data/d3_dev_pairs_index.jsonl"
PROBE = ROOT / "data/d3_train_probe_index.jsonl"


def protected_hashes():
    protected = verify_inputs()
    for manifest in ("reports/d3_artifacts_v2_sha256.json",):
        values = json.loads((ROOT / manifest).read_bytes())
        for name, digest in values.items():
            assert sha(ROOT / name) == digest, name
        protected.update(values)
        protected[manifest] = sha(ROOT / manifest)
    for name in ("HANDOFF_D3_cpu.md", "PLAN_D3.md", "reports/d3_artifacts_sha256.json"):
        protected[name] = sha(ROOT / name)
    return protected


def main():
    assert not any(path.exists() for path in (DEV_PAIRS, DEV_INDEX, PROBE)), "Preserve existing outputs"
    before = protected_hashes()
    split = json.loads((ROOT / "data/d3_split.json").read_bytes())
    dev = set(split["development_rows"])
    original_data = (ROOT / "data/d1_pairs_swift.jsonl").read_bytes().splitlines(keepends=True)
    original_index = (ROOT / "data/d1_pairs_index.jsonl").read_bytes().splitlines(keepends=True)
    assert len(original_data) == len(original_index) == 707
    selected = [number for number, line in enumerate(original_index) if json.loads(line)["row"] in dev]
    assert len(selected) == 146
    training_lines = (ROOT / "data/d3_pairs_v2_index.jsonl").read_bytes().splitlines(keepends=True)
    assert len(training_lines) == 611
    assert not dev & {json.loads(line)["row"] for line in training_lines}
    probe = random.Random(3407).sample(training_lines, 146)
    for path, lines in ((DEV_PAIRS, [original_data[n] for n in selected]),
                        (DEV_INDEX, [original_index[n] for n in selected]), (PROBE, probe)):
        with path.open("xb") as handle:
            handle.write(b"".join(lines))
    assert len(read_rows(PROBE)) == 146
    assert protected_hashes() == before
    print("D3 development pairs 146, training probe 146; original rows and hashes preserved")


if __name__ == "__main__":
    main()

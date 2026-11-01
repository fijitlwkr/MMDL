"""Phase 2 only. Download pinned adapters and merge using the training merge script."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from verify_code import ROOT, verify

BASE = "Qwen/Qwen3-VL-4B-Instruct"
BASE_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
ADAPTERS = {
    "E1": ("MMDL-team4/hypB-e1-structured-3k", "0de38ff61af238608dc7be53358f1dac23788995"),
    "E2": ("MMDL-team4/hypB-e2-answer-3k", "72e45c1bb07eb79179739fae949ccf80f21e891b"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=ADAPTERS)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("use a new model output folder")
    verify()
    from huggingface_hub import snapshot_download
    base = Path(snapshot_download(BASE, revision=BASE_REVISION))
    repo, revision = ADAPTERS[args.run]
    adapter = Path(snapshot_download(repo, revision=revision,
                                    allow_patterns=["adapter_config.json", "adapter_model.safetensors"]))
    assert base.name == BASE_REVISION and adapter.name == revision
    training = ROOT / "assignment/experiments/hypB_train/yoonseok"
    config = json.loads((training / "train_config.json").read_text())
    assert config["model"] == BASE and config["model_revision"] == BASE_REVISION
    subprocess.run([sys.executable, str(training / "merge.py"), str(adapter), str(args.out)], check=True)
    for file in base.iterdir():
        if file.suffix in {".json", ".jinja", ".txt"} and file.name not in {"config.json", "model.safetensors.index.json"}:
            assert file.read_bytes() == (args.out / file.name).read_bytes(), file.name
    receipt = {"run": args.run, "base": BASE, "base_revision": BASE_REVISION,
               "adapter": repo, "adapter_revision": revision, "dtype": "bfloat16",
               "adapter_sha256": hashlib.sha256((adapter / "adapter_model.safetensors").read_bytes()).hexdigest(),
               "merged_weight_bytes": sum(p.stat().st_size for p in args.out.glob("*.safetensors"))}
    (args.out.parent / "model_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()

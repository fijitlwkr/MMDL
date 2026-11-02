"""Phase 2 only. Download pinned adapters and merge using the training merge script."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from verify_code import ROOT, verify

BASE = "Qwen/Qwen3-VL-4B-Instruct"
BASE_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
ADAPTERS = {
    "E1": ("MMDL-team4/hypB-e1-structured-3k", "run-jinho"),
    "E2": ("MMDL-team4/hypB-e2-answer-3k", "run-jinho"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=ADAPTERS)
    parser.add_argument("out", type=Path)
    parser.add_argument("--local-adapter", type=Path, default=None,
                        help="Optional local path to adapter checkpoint directory")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("use a new model output folder")
    verify()
    from huggingface_hub import snapshot_download
    base = Path(snapshot_download(BASE, revision=BASE_REVISION))
    repo, revision = ADAPTERS[args.run]

    if args.local_adapter and args.local_adapter.exists():
        adapter = args.local_adapter.resolve()
        print(f"Using local adapter from: {adapter}")
    else:
        print(f"Downloading adapter from HF: {repo}@{revision}")
        adapter = Path(snapshot_download(repo, revision=revision,
                                        allow_patterns=["adapter_config.json", "adapter_model.safetensors"]))

    training = ROOT / "assignment/experiments/hypB_train/jinho"
    config = json.loads((training / "train_config.json").read_text())
    assert config["model"] == BASE and config["model_revision"] == BASE_REVISION

    train_py = training / ".venv-train/bin/python"
    merge_py = training / "merge.py"
    py_exec = str(train_py) if train_py.exists() else sys.executable
    subprocess.run([py_exec, str(merge_py), str(adapter), str(args.out)], check=True)

    for file in base.iterdir():
        if file.suffix in {".json", ".jinja", ".txt"} and file.name not in {"config.json", "model.safetensors.index.json"}:
            assert file.read_bytes() == (args.out / file.name).read_bytes(), file.name

    receipt = {
        "run": args.run,
        "base": BASE,
        "base_revision": BASE_REVISION,
        "adapter": repo,
        "adapter_revision": revision,
        "dtype": "bfloat16",
        "adapter_sha256": hashlib.sha256((adapter / "adapter_model.safetensors").read_bytes()).hexdigest(),
        "merged_weight_bytes": sum(p.stat().st_size for p in args.out.glob("*.safetensors"))
    }
    (args.out.parent / "model_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()


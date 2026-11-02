"""Upload trained LoRA adapter and logs to Hugging Face branch run-jinho."""
import argparse
import json
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from huggingface_hub import HfApi

REPOS = {
    "E1": "MMDL-team4/hypB-e1-structured-3k",
    "E2": "MMDL-team4/hypB-e2-answer-3k",
}
BRANCH = "run-jinho"
BASE_MODEL = "Qwen/Qwen3-VL-4B-Instruct"
BASE_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"

README_TEMPLATE = """---
base_model: {base_model}
library_name: peft
tags:
- lora
- qwen3-vl
---

# {repo_name}

가설 B(구조화된 풀이 SFT) {run} 모델의 LoRA adapter입니다.
역할: {role}

> **학습 완료** · {branch} 브랜치의 마지막 checkpoint-188 adapter입니다.

## 원본 모델
`{base_model}`, revision `{base_revision}`, bf16

## 학습 데이터
`MMDL-team4/hypB-train-data` v1.1 (`{run}_train_swift.jsonl`, 3,000문항)

## 학습 설정
- 도구: ms-swift
- 언어모델 LoRA만 (36층 q, k, v, o, gate, up, down), r=16, alpha=32, dropout=0.05
- ViT 및 Merger 고정
- Optimizer: AdamW, lr 1e-4, cosine, warmup 3%, 1 epoch (188 steps)
- Batch size: effective 16 (1 per device x accum 16)
- 손실: assistant 응답 토큰만
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=["E1", "E2"])
    parser.add_argument("folder", type=Path, help="output folder containing checkpoint-188 and logs")
    parser.add_argument("--git-commit", default="exp/hypB-data", help="Git commit hash or branch name")
    args = parser.parse_args()

    repo = REPOS[args.run]
    folder = args.folder.resolve()
    checkpoint = folder / "checkpoint-188"
    if not checkpoint.exists():
        # Check if folder itself is checkpoint
        if (folder / "adapter_model.safetensors").exists():
            checkpoint = folder
        else:
            raise FileNotFoundError(f"checkpoint-188 not found in {folder}")

    api = HfApi()
    # Ensure branch exists
    try:
        api.create_branch(repo, branch=BRANCH, repo_type="model")
        print(f"Created branch {BRANCH} on {repo}")
    except Exception as e:
        print(f"Branch {BRANCH} already exists or note: {e}")

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Copy adapter files
        shutil.copyfile(checkpoint / "adapter_model.safetensors", tmp_path / "adapter_model.safetensors")
        adapter_cfg = json.loads((checkpoint / "adapter_config.json").read_text())
        adapter_cfg["base_model_name_or_path"] = BASE_MODEL
        adapter_cfg["revision"] = BASE_REVISION
        (tmp_path / "adapter_config.json").write_text(json.dumps(adapter_cfg, indent=2))

        # 2. Copy logs and metadata if available
        for file_name in [
            "train_log.txt", "train_args.json", "train_config.json",
            "trainer_state.json", "training_history.json", "training_observations.json",
            "summary.json", "packages_train.txt", "packages_eval.txt"
        ]:
            src = folder / file_name
            if src.exists():
                shutil.copyfile(src, tmp_path / file_name)

        # Also check parent artifacts for package info
        artifacts = folder.parent
        for pkg_file in ["train-packages.txt", "eval-packages.txt"]:
            src = artifacts / pkg_file
            if src.exists() and not (tmp_path / pkg_file).exists():
                shutil.copyfile(src, tmp_path / pkg_file)

        # 3. Write README.md
        role = "정리 풀이 학습 (주 실험)" if args.run == "E1" else "Final Answer 1줄 학습 (대조군)"
        readme_content = README_TEMPLATE.format(
            base_model=BASE_MODEL,
            base_revision=BASE_REVISION,
            repo_name=repo.split("/")[-1],
            run=args.run,
            role=role,
            branch=BRANCH
        )
        (tmp_path / "README.md").write_text(readme_content)

        print(f"Uploading files to {repo} on branch {BRANCH}...")
        api.upload_folder(
            folder_path=str(tmp_path),
            repo_id=repo,
            repo_type="model",
            revision=BRANCH,
            commit_message=f"Upload {args.run} adapter and logs by Jinho ({args.git_commit})"
        )
        print(f"Successfully uploaded {args.run} to {repo} @ {BRANCH}!")


if __name__ == "__main__":
    main()


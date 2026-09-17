#!/usr/bin/env python3
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from mmmu_pipeline.config import load_config
from mmmu_pipeline.experiments import get_handler


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = REPO_ROOT / "experiments" / "exp0_baseline" / "config.json"


def _command_output(command):
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def save_environment_snapshot(path, config, config_path):
    import torch

    try:
        vllm_version = importlib.metadata.version("vllm")
    except importlib.metadata.PackageNotFoundError:
        vllm_version = None
    gpu_query = _command_output([
        "nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader,nounits"
    ])
    gpu_rows = []
    if gpu_query:
        for line in gpu_query.splitlines():
            name, separator, driver = line.rpartition(",")
            gpu_rows.append({
                "model": name.strip() if separator else line.strip(),
                "driver_version": driver.strip() if separator else None,
            })
    nvidia_smi = _command_output(["nvidia-smi"])
    nvcc = _command_output(["nvcc", "--version"])
    config_bytes = Path(config_path).read_bytes()
    package_versions = {}
    for package in ["vllm", "torch", "transformers", "datasets", "qwen-vl-utils"]:
        try:
            package_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            package_versions[package] = None
    snapshot = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "torch_cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "vllm_version": vllm_version,
        "package_versions": package_versions,
        "gpu_models": [row["model"] for row in gpu_rows],
        "driver_versions": sorted({row["driver_version"] for row in gpu_rows if row["driver_version"]}),
        "gpus": gpu_rows,
        "nvidia_smi": nvidia_smi,
        "nvcc_version": nvcc,
        "environment": {key: os.environ.get(key) for key in config["env"]},
        "config_path": str(Path(config_path).resolve()),
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "model": config["model"],
        "dataset": config["dataset"],
        "sampling": config["sampling"],
        "generation_budget": config["generation_budget"],
        "experiment": config.get("experiment"),
        "selection": config.get("selection"),
        "active_condition": config.get("active_condition"),
    }
    Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def prepare_vllm_input(messages, processor):
    from qwen_vl_utils import process_vision_info

    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    images, videos, video_kwargs = process_vision_info(
        messages,
        image_patch_size=processor.image_processor.patch_size,
        return_video_kwargs=True,
        return_video_metadata=True,
    )
    multimodal_data = {}
    if images is not None:
        multimodal_data["image"] = images
    if videos is not None:
        multimodal_data["video"] = videos
    return {
        "prompt": prompt,
        "multi_modal_data": multimodal_data,
        "mm_processor_kwargs": video_kwargs,
    }


def run(config, config_path):
    # These must be set before importing transformers, tokenizers, or vLLM.
    for key, value in config["env"].items():
        os.environ[key] = str(value)

    experiment_kind = config.get("experiment", {}).get("kind")
    handler = get_handler(experiment_kind)
    selection_data = handler["load_selection"](config) if handler else None

    output_dir = Path(config["output_dir"])
    protected_names = [
        "effective_config.json", "env.json", "dataset.jsonl", "predictions.jsonl",
        "results.json", "results.md", "subset_summary.json", "subset_summary.md",
        "comparison.json", "comparison.md",
    ]
    existing_outputs = [name for name in protected_names if (output_dir / name).exists()]
    image_dir = output_dir / "images"
    if existing_outputs or (image_dir.exists() and any(image_dir.iterdir())):
        raise RuntimeError(
            f"Refusing to overwrite existing experiment outputs in {output_dir}: "
            f"{existing_outputs or ['images/']}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    if handler and handler.get("pre_run"):
        handler["pre_run"](config, selection_data, output_dir)

    (output_dir / "effective_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    env_path = output_dir / "env.json"

    snapshot = save_environment_snapshot(env_path, config, config_path)
    required_vllm = config["backend"]["required_version"]
    if snapshot["vllm_version"] != required_vllm:
        raise RuntimeError(
            f"vLLM must be exactly {required_vllm}; found {snapshot['vllm_version']!r}. "
            f"Environment snapshot was saved to {env_path}."
        )
    if not snapshot["gpus"]:
        raise RuntimeError(f"No NVIDIA GPU/driver detected. Environment snapshot was saved to {env_path}.")

    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams
    # NOTE: image_layout.py depends on this being a late/local import — see install_layout_builder
    from mmmu_pipeline.dataset import build_dataset, build_messages
    from mmmu_pipeline.scoring import evaluate, score_generation, write_results

    dataset_path = output_dir / "dataset.jsonl"
    selected_ids = None if selection_data is None else selection_data["selected_id_set"]
    records = build_dataset(config, dataset_path, image_dir, selected_ids)
    processor = AutoProcessor.from_pretrained(
        config["model"]["name"], revision=config["model"]["revision"]
    )
    messages = [build_messages(record, config) for record in records]
    requests = [prepare_vllm_input(item, processor) for item in messages]
    max_images = max(len(record["image_paths"]) for record in records)

    llm = LLM(
        model=config["model"]["name"],
        revision=config["model"]["revision"],
        tokenizer_revision=config["model"]["revision"],
        max_model_len=config["generation_budget"]["max_model_len"],
        gpu_memory_utilization=config["backend"]["gpu_memory_utilization"],
        trust_remote_code=True,
        limit_mm_per_prompt={"image": max(1, max_images)},
        seed=config["sampling"]["engine_seed"],
    )
    # vLLM has no do_sample argument: a positive temperature enables sampling, while 0 is greedy.
    effective_temperature = (
        config["sampling"]["temperature"] if config["sampling"]["do_sample"] else 0.0
    )
    sampling = SamplingParams(
        temperature=effective_temperature,
        top_p=config["sampling"]["top_p"],
        top_k=config["sampling"]["top_k"],
        repetition_penalty=config["sampling"]["repetition_penalty"],
        presence_penalty=config["sampling"]["presence_penalty"],
        max_tokens=config["generation_budget"]["max_new_tokens"],
        stop_token_ids=[],
        seed=config["sampling"]["sampling_params_seed"],
    )
    outputs = llm.generate(requests, sampling_params=sampling)
    expected_total = (
        config["dataset"]["expected_subjects"]
        * config["dataset"]["expected_examples_per_subject"]
        if selection_data is None
        else config["selection"]["expected_examples"]
    )
    if len(outputs) != expected_total:
        raise RuntimeError(f"Expected {expected_total} vLLM outputs, got {len(outputs)}")

    rows = []
    for record, output in zip(records, outputs):
        if not output.outputs:
            raise RuntimeError(f"No generation candidate for {record['question_id']}")
        generation = output.outputs[0]
        row = {
            "question_id": record["question_id"],
            "subject": record["subject"],
            "raw_text": generation.text,
            "finish_reason": generation.finish_reason,
            "input_tokens": len(output.prompt_token_ids) if output.prompt_token_ids is not None else None,
            "output_tokens": len(generation.token_ids or []),
            "parse_failure": False,
            "question_type": record["question_type"],
            "answer": record["answer"],
            "options": record["options"],
        }
        if row["input_tokens"] is None:
            raise RuntimeError(f"vLLM did not report input token ids for {record['question_id']}")
        parsed, correct, row["parse_failure"] = score_generation(row)
        row["parsed_prediction"] = parsed
        row["correct"] = correct
        rows.append(row)

    result = evaluate(rows)
    expected_result_subjects = (
        config["dataset"]["expected_subjects"]
        if selection_data is None
        else sum(count > 0 for count in selection_data["subject_counts"].values())
    )
    if result["n_total"] != expected_total or result["n_subjects"] != expected_result_subjects:
        raise RuntimeError(
            f"Refusing to publish partial result: {result['n_total']} examples / {result['n_subjects']} subjects"
        )
    predictions_path = output_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_results(result, output_dir / "results.json", output_dir / "results.md")

    if handler and handler.get("post_run"):
        handler["post_run"](config, selection_data, rows, output_dir)

    print(f"Raw generations: {predictions_path}")
    print(f"Environment:     {env_path}")
    print(f"Results:         {output_dir / 'results.md'}")
    print(f"Macro accuracy:  {result['macro_accuracy'] * 100:.2f}")
    print(f"Parse failures:  {result['parse_failure_count']}/{expected_total}")


def score_only(config, predictions_path):
    from mmmu_pipeline.scoring import evaluate, write_results

    with Path(predictions_path).open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    result = evaluate(rows)
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    write_results(result, output_dir / "results.json", output_dir / "results.md")
    print(f"Re-scored {len(rows)} unchanged raw generations -> {output_dir / 'results.md'}")


def dry_run(config, config_path):
    import mmmu_pipeline

    print(f"config_path={config_path}")
    print(f"output_dir={config['output_dir']}")
    print(f"output_dir_exists={Path(config['output_dir']).is_dir()}")
    print(f"mmmu_pipeline={Path(mmmu_pipeline.__file__).resolve()}")

    experiment_kind = config.get("experiment", {}).get("kind")
    handler = get_handler(experiment_kind)
    if handler:
        selection_data = handler["load_selection"](config)
        if handler.get("dry_run_extra"):
            handler["dry_run_extra"](config, selection_data)

    print("dry_run=OK (model and vLLM were not loaded)")


def main():
    parser = argparse.ArgumentParser(description="Run a fixed MMMU/Qwen3-VL experiment")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--score-only",
        metavar="PREDICTIONS_JSONL",
        help="Re-parse an existing raw JSONL without loading the model or changing raw_text",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate config paths and package imports without loading the model or vLLM",
    )
    parser.add_argument(
        "--presence-penalty",
        type=float,
        help="Experiment-C condition; allowed values are fixed by its config (0 or 0.5)",
    )
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    experiment_kind = config.get("experiment", {}).get("kind")
    if experiment_kind == "presence_penalty_stratified":
        if args.presence_penalty is None:
            parser.error("Experiment C requires --presence-penalty 0 or 0.5")
        from mmmu_pipeline.presence_penalty import configure_condition

        configure_condition(config, args.presence_penalty)
    elif args.presence_penalty is not None:
        parser.error("--presence-penalty is only allowed for Experiment C")
    if args.dry_run:
        dry_run(config, config_path)
    elif args.score_only:
        score_only(config, args.score_only)
    else:
        run(config, config_path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise

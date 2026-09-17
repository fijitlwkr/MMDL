import json
from pathlib import Path


SUBJECTS = [
    "Accounting", "Agriculture", "Architecture_and_Engineering", "Art", "Art_Theory",
    "Basic_Medical_Science", "Biology", "Chemistry", "Clinical_Medicine", "Computer_Science",
    "Design", "Diagnostics_and_Laboratory_Medicine", "Economics", "Electronics",
    "Energy_and_Power", "Finance", "Geography", "History", "Literature", "Manage",
    "Marketing", "Materials", "Math", "Mechanical_Engineering", "Music", "Pharmacy",
    "Physics", "Psychology", "Public_Health", "Sociology",
]


FIXED = {
    "model.name": "Qwen/Qwen3-VL-4B-Instruct",
    "model.revision": "ebb281ec70b05090aa6165b016eac8ec08e71b17",
    "dataset.name": "MMMU/MMMU",
    "dataset.revision": "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68",
    "dataset.split": "validation",
    "dataset.expected_subjects": 30,
    "dataset.expected_examples_per_subject": 30,
    "backend.name": "vllm",
    "backend.required_version": "0.11.0",
    "backend.gpu_memory_utilization": 0.9,
    "env.VLLM_ENABLE_V1_MULTIPROCESSING": "0",
    "env.VLLM_WORKER_MULTIPROC_METHOD": "spawn",
    "env.TOKENIZERS_PARALLELISM": "false",
    "sampling.do_sample": True,
    "sampling.temperature": 0.7,
    "sampling.top_p": 0.8,
    "sampling.top_k": 20,
    "sampling.repetition_penalty": 1.0,
    "sampling.presence_penalty": 1.5,
    "sampling.engine_seed": 42,
    "sampling.sampling_params_seed": 42,
    "generation_budget.max_model_len": 9048,
    "generation_budget.max_new_tokens": 2048,
    "image.min_pixels": 1003520,
    "image.max_pixels": 4014080,
    "system_message": None,
    "scoring.parse_failure_policy": "mark_as_incorrect",
}


def _get(config, dotted_key):
    value = config
    for key in dotted_key.split("."):
        value = value[key]
    return value


def load_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    output_dir = Path(config["output_dir"])
    if not output_dir.is_absolute():
        output_dir = path.parent / output_dir
    config["output_dir"] = str(output_dir.resolve())
    errors = []
    if config.get("enforce_fixed_baseline", False):
        for key, expected in FIXED.items():
            try:
                actual = _get(config, key)
            except KeyError:
                errors.append(f"{key}: missing (expected {expected!r})")
                continue
            if actual != expected:
                errors.append(f"{key}: {actual!r} (expected {expected!r})")

    if config["sampling"]["engine_seed"] != config["sampling"]["sampling_params_seed"]:
        errors.append("engine_seed and sampling_params_seed must be identical")
    if not config.get("prompt_template_source"):
        errors.append("prompt_template_source must be the official Qwen3-VL MMMU template")
    if not config["image"].get("resize"):
        errors.append("image.resize must use qwen_vl_utils.process_vision_info (smart_resize)")
    if not config["image"].get("marker_handling"):
        errors.append("image.marker_handling does not match the required policy")
    if not config.get("logging", {}).get("save_raw_generation"):
        errors.append("logging.save_raw_generation must be true")
    if not config.get("logging", {}).get("save_env_snapshot"):
        errors.append("logging.save_env_snapshot must be true")
    if not config.get("scoring", {}).get("report_parse_failure_rate"):
        errors.append("scoring.report_parse_failure_rate must be true")
    if errors:
        raise ValueError("Config violates the fixed baseline settings:\n- " + "\n- ".join(errors))
    return config

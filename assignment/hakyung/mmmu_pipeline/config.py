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


IMAGE_RESIZE = "qwen_vl_utils.process_vision_info -> fetch_image -> smart_resize"


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

BUDGET_INCREASE_FIXED = {
    "experiment.kind": "truncation_budget_increase",
    "selection.finish_reason": "length",
    "selection.expected_source_examples": 900,
    "selection.expected_examples": 230,
    "selection.source_generation_budget.max_model_len": 9048,
    "selection.source_generation_budget.max_new_tokens": 2048,
    "generation_budget.max_model_len": 16384,
    "generation_budget.max_new_tokens": 8192,
    "comparison_context.experiment_a_judge_final_failures": 26,
    "comparison_context.experiment_a_length_failures": 25,
}

PRESENCE_PENALTY_FIXED = {
    "experiment.kind": "presence_penalty_stratified",
    "experiment.conditions": [0.0, 0.5],
    "selection.method": "stratified_by_subject",
    "selection.seed": 20260917,
    "selection.expected_source_examples": 900,
    "selection.expected_examples": 200,
    "sampling.presence_penalty": None,
    "comparison.reference_presence_penalty": 1.5,
    "comparison.exp0_length_count": 230,
}

IMAGE_LAYOUT_FIXED = {
    "experiment.kind": "image_layout_multi_image",
    "experiment.conditions": ["inline", "prefix"],
    "selection.method": "question_text_distinct_image_markers_gte_2",
    "selection.expected_source_examples": 900,
    "selection.expected_examples": 23,
    "selection.expected_subject_counts": {
        "Architecture_and_Engineering": 1,
        "Art_Theory": 5,
        "Chemistry": 2,
        "Clinical_Medicine": 1,
        "Computer_Science": 1,
        "Diagnostics_and_Laboratory_Medicine": 1,
        "Economics": 2,
        "History": 2,
        "Manage": 1,
        "Math": 1,
        "Mechanical_Engineering": 1,
        "Music": 3,
        "Pharmacy": 1,
        "Psychology": 1,
    },
    "image.layout": None,
    "image.marker_handling": (
        "inline은 마커를 이미지 블록으로 치환; prefix는 마커를 유지하고 "
        "참조 이미지를 원래 순서대로 텍스트 앞 배치"
    ),
}

EXPERIMENT_FIXED_OVERRIDES = {
    "truncation_budget_increase": BUDGET_INCREASE_FIXED,
    "presence_penalty_stratified": PRESENCE_PENALTY_FIXED,
    "image_layout_multi_image": IMAGE_LAYOUT_FIXED,
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
    selection = config.get("selection")
    if selection is not None and "source_predictions" in selection:
        source_predictions = Path(selection["source_predictions"])
        if not source_predictions.is_absolute():
            source_predictions = path.parent / source_predictions
        selection["source_predictions"] = str(source_predictions.resolve())
    errors = []
    if config.get("enforce_fixed_baseline", False):
        expected_settings = dict(FIXED)
        experiment_kind = config.get("experiment", {}).get("kind")
        expected_settings.update(EXPERIMENT_FIXED_OVERRIDES.get(experiment_kind, {}))
        for key, expected in expected_settings.items():
            try:
                actual = _get(config, key)
            except KeyError:
                errors.append(f"{key}: missing (expected {expected!r})")
                continue
            if actual != expected:
                errors.append(f"{key}: {actual!r} (expected {expected!r})")

    if selection is not None and "source_predictions" in selection:
        source_path = Path(selection["source_predictions"])
        if not source_path.is_file():
            errors.append(f"selection.source_predictions does not exist: {source_path}")
        if source_path.parent.resolve() == output_dir.resolve():
            errors.append("selection.source_predictions must not be inside the experiment output_dir")

    if config["sampling"]["engine_seed"] != config["sampling"]["sampling_params_seed"]:
        errors.append("engine_seed and sampling_params_seed must be identical")
    if not config.get("prompt_template_source"):
        errors.append("prompt_template_source must be the official Qwen3-VL MMMU template")
    actual_resize = config.get("image", {}).get("resize")
    if actual_resize != IMAGE_RESIZE:
        errors.append(
            f"image.resize: {actual_resize!r} (expected exactly {IMAGE_RESIZE!r})"
        )
    if not config["image"].get("marker_handling"):
        errors.append("image.marker_handling does not match the required policy")
    if not config.get("logging", {}).get("save_raw_generation"):
        errors.append("logging.save_raw_generation must be true")
    if not config.get("logging", {}).get("save_env_snapshot"):
        errors.append("logging.save_env_snapshot must be true")
    if not config.get("scoring", {}).get("report_parse_failure_rate"):
        errors.append("scoring.report_parse_failure_rate must be true")
    if errors:
        raise ValueError("Config violates the fixed experiment settings:\n- " + "\n- ".join(errors))
    return config

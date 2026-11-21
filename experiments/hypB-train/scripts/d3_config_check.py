"""Write the authorized D3 config diff and check ms-swift arguments on CPU."""

from dataclasses import fields
import json
import os

from classify_answers import ROOT, WORKSPACE, write_json
from check_dpo_pairs import PROCESSOR


def main():
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", MODELSCOPE_OFFLINE="1",
                      MODELSCOPE_CACHE=os.path.relpath(ROOT / "data/d3_cpu_cache", WORKSPACE))
    validation = json.loads((ROOT / "reports/d3_pair_validation.json").read_bytes())
    assert validation["status"] == "PASS" and validation["pairs"] >= 500 and validation["by_kind"]["concise"] >= 50
    assert validation["longest"]["longest"] <= 10240
    original = json.loads((ROOT / "scripts/dpo_config.json").read_bytes())
    config = {**original, "learning_rate": 2e-5, "save_total_limit": 2}
    assert {key for key in config if config[key] != original[key]} == {"learning_rate", "save_total_limit"}
    path = ROOT / "scripts/d3_config.json"
    if path.exists():
        raise FileExistsError(path)
    write_json(path, config)

    from dpo_train import arguments
    from swift.llm import RLHFArguments

    assert {key for key in config if key != "disable_dropout"} <= {field.name for field in fields(RLHFArguments)}
    dataset = str((ROOT / "data/d3_pairs_swift.jsonl").resolve())
    options = {**config, "dataset": [dataset], "model": str(PROCESSOR.resolve()), "model_revision": None,
               "bf16": False, "torch_dtype": "float32", "use_cpu": True,
               "output_dir": str(ROOT / "data/d3_cpu_cache/argument_check")}
    args = arguments(**options)
    actual = args.training_args
    assert args.dataset == [dataset] and args.max_steps == -1
    assert actual.learning_rate == 2e-5 and actual.save_total_limit == 2 and actual.num_train_epochs == 2
    assert actual.beta == 0.1 and actual.rpo_alpha == 1.0 and actual.max_length == 10240
    assert not actual.disable_dropout and not actual.reference_free
    assert not args.adapters and not args.ref_adapters and args.ref_model is None and args.resume_from_checkpoint is None
    result = {"status": "PASS", "changed_keys": {key: {"before": original[key], "after": config[key]}
                                                   for key in config if config[key] != original[key]},
              "dataset_argument": args.dataset, "max_steps": args.max_steps,
              "training_args": {key: getattr(actual, key) for key in ("learning_rate", "save_total_limit", "num_train_epochs",
                              "beta", "rpo_alpha", "max_length", "disable_dropout", "reference_free")},
              "cpu_only_overrides": ["model points to local weight-free processor", "model_revision=None", "bf16=False", "torch_dtype=float32", "use_cpu=True"],
              "model_weights_loaded": False, "trainer_created": False,
              "dataset_rule": "Same as D1: dataset path is supplied to arguments(dataset=[...]) rather than stored in the config JSON."}
    write_json(ROOT / "reports/d3_config_check.json", result)
    print("D3 config arguments PASS", flush=True)


if __name__ == "__main__":
    main()

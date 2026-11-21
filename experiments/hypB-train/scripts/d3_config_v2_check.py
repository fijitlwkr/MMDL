"""Copy the unchanged D3 config and verify the v2 dataset argument on CPU."""

import json
import os

from classify_answers import ROOT, WORKSPACE, write_json
from check_dpo_pairs import PROCESSOR
from d3_prepare_v2 import PAIRS, verify_inputs
from sample_m0 import sha


def main():
    before = verify_inputs()
    validation = json.loads((ROOT / "reports/d3_pair_v2_validation.json").read_bytes())
    assert validation["status"] == "PASS"
    assert validation["pairs"] >= 500 and validation["by_kind"]["concise"] >= 40
    assert validation["longest"]["longest"] <= 10240
    original = ROOT / "scripts/d3_config.json"
    path = ROOT / "scripts/d3_config_v2.json"
    with path.open("xb") as output:
        output.write(original.read_bytes())
    config = json.loads(path.read_bytes())
    assert "dataset" not in config
    os.environ.update(CUDA_VISIBLE_DEVICES="-1", HF_HUB_OFFLINE="1", MODELSCOPE_OFFLINE="1",
                      MODELSCOPE_CACHE=os.path.relpath(ROOT / "data/d3_cpu_cache_v2", WORKSPACE))
    from dpo_train import arguments

    dataset = str(PAIRS.resolve())
    options = {**config, "dataset": [dataset], "model": str(PROCESSOR.resolve()), "model_revision": None,
               "bf16": False, "torch_dtype": "float32", "use_cpu": True,
               "output_dir": str(ROOT / "data/d3_cpu_cache_v2/argument_check")}
    args = arguments(**options)
    actual = args.training_args
    assert args.dataset == [dataset] and args.max_steps == -1
    assert actual.learning_rate == 2e-5 and actual.save_total_limit == 2 and actual.num_train_epochs == 2
    assert actual.beta == 0.1 and actual.rpo_alpha == 1.0 and actual.max_length == 10240
    assert not actual.disable_dropout and not actual.reference_free
    assert not args.adapters and not args.ref_adapters and args.ref_model is None and args.resume_from_checkpoint is None
    assert sha(path) == sha(original) and verify_inputs() == before
    result = {"status": "PASS", "config_json_changed_keys": [], "config_byte_identical": True,
              "config_sha256": sha(path), "dataset_argument_before": "data/d3_pairs_swift.jsonl",
              "dataset_argument_after": "data/d3_pairs_v2_swift.jsonl", "actual_dataset_argument": args.dataset,
              "max_steps": args.max_steps,
              "training_args": {key: getattr(actual, key) for key in ("learning_rate", "save_total_limit", "num_train_epochs",
                              "beta", "rpo_alpha", "max_length", "disable_dropout", "reference_free")},
              "cpu_only_overrides": ["model points to local weight-free processor", "model_revision=None", "bf16=False", "torch_dtype=float32", "use_cpu=True"],
              "model_weights_loaded": False, "trainer_created": False,
              "dataset_rule": "As in D1 and D3 v1, supply the dataset separately through arguments(dataset=[...])."}
    write_json(ROOT / "reports/d3_config_v2_check.json", result)
    print("D3 v2 config arguments PASS", flush=True)


if __name__ == "__main__":
    main()

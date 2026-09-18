"""Registry of per-experiment hooks used by run_mmmu_eval.py.

Adding a new experiment (D, E, F, ...) means adding one entry here.
run_mmmu_eval.py's run()/dry_run() should never need to change again.
"""
import json

from . import subset as _subset
from . import presence_penalty as _presence_penalty
from . import image_layout as _image_layout
from . import seed_repro as _seed_repro


def _truncation_dry_run_extra(config, selection_data):
    print(
        f"selection=finish_reason:{config['selection']['finish_reason']} "
        f"{len(selection_data['selected_rows'])}/{len(selection_data['source_rows'])}"
    )
    print("selection_by_subject=" + json.dumps(
        selection_data["subject_counts"], ensure_ascii=False, sort_keys=True
    ))
    print(
        "generation_budget="
        f"{config['generation_budget']['max_new_tokens']}/"
        f"{config['generation_budget']['max_model_len']}"
    )


def _truncation_post_run(config, selection_data, rows, output_dir):
    _subset.write_subset_summary(config, selection_data, output_dir)
    comparison = _subset.build_comparison(config, selection_data, rows)
    _subset.write_comparison(comparison, output_dir)
    print(f"Comparison:      {output_dir / 'comparison.md'}")


def _presence_penalty_dry_run_extra(config, selection_data):
    print(
        f"presence_penalty={config['sampling']['presence_penalty']} "
        f"condition={config['active_condition']['name']}"
    )
    print(
        f"stratified_selection={len(selection_data['selected_ids'])}/"
        f"{len(selection_data['source_rows'])} seed={config['selection']['seed']}"
    )
    print("selection_by_subject=" + json.dumps(
        selection_data["subject_counts"], ensure_ascii=False, sort_keys=True
    ))


def _presence_penalty_pre_run(config, selection_data, output_dir):
    _presence_penalty.write_or_validate_manifest(selection_data, config["experiment_output_root"])


def _image_layout_dry_run_extra(config, selection_data):
    print(
        f"image_layout={config['image']['layout']} "
        f"condition={config['active_condition']['name']}"
    )
    print(
        f"multi_image_selection={len(selection_data['selected_ids'])}/"
        f"{selection_data['source_count']}"
    )
    print("selection_by_subject=" + json.dumps(
        selection_data["subject_counts"], ensure_ascii=False, sort_keys=True
    ))
    print("selection_ids=" + json.dumps(
        selection_data["selected_ids"], ensure_ascii=False
    ))


def _image_layout_pre_run(config, selection_data, output_dir):
    _image_layout.install_layout_builder(config)
    _image_layout.write_or_validate_manifest(
        selection_data, config["experiment_output_root"]
    )


def _image_layout_post_run(config, selection_data, rows, output_dir):
    _image_layout.maybe_write_comparison(config)


def _seed_repro_dry_run_extra(config, selection_data):
    print(
        f"seed={config['sampling']['engine_seed']} "
        f"condition={config['active_condition']['name']}"
    )
    print("selection=full_validation_set (900/900)")


def _seed_repro_post_run(config, selection_data, rows, output_dir):
    _seed_repro.maybe_write_comparison(config)


# Each handler may define: load_selection (required), pre_run, post_run, dry_run_extra.
# Missing keys simply mean "do nothing at that step" for that experiment.
REGISTRY = {
    "truncation_budget_increase": {
        "load_selection": _subset.load_truncation_selection,
        "post_run": _truncation_post_run,
        "dry_run_extra": _truncation_dry_run_extra,
    },
    "presence_penalty_stratified": {
        "load_selection": _presence_penalty.build_stratified_selection,
        "pre_run": _presence_penalty_pre_run,
        # post_run is intentionally absent: the 3-way comparison needs both
        # presence_penalty conditions to exist first, so it's built separately
        # by experiments/expC_presence_penalty/compare_conditions.py.
        "dry_run_extra": _presence_penalty_dry_run_extra,
    },
    "image_layout_multi_image": {
        "load_selection": _image_layout.load_multi_image_selection,
        "pre_run": _image_layout_pre_run,
        "post_run": _image_layout_post_run,
        "dry_run_extra": _image_layout_dry_run_extra,
    },
    "seed_reproducibility": {
        "load_selection": _seed_repro.load_selection,
        "post_run": _seed_repro_post_run,
        "dry_run_extra": _seed_repro_dry_run_extra,
    },
}


def get_handler(experiment_kind):
    return REGISTRY.get(experiment_kind)

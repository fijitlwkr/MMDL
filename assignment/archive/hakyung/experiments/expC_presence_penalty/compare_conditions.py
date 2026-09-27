#!/usr/bin/env python3
import argparse
from pathlib import Path

from mmmu_pipeline.config import load_config
from mmmu_pipeline.presence_penalty import (
    build_stratified_selection,
    build_three_way_comparison,
    write_three_way_comparison,
)


SCRIPT_DIR = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Compare Experiment C's three conditions")
    parser.add_argument("--config", default=str(SCRIPT_DIR / "config.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.dry_run:
        selection = build_stratified_selection(config)
        output_root = Path(config["output_dir"])
        print(f"selected_examples={len(selection['selected_ids'])}")
        print(f"sampling_seed={selection['manifest']['sampling_seed']}")
        print(f"expected_penalty_0={output_root / 'presence_penalty_0_0' / 'predictions.jsonl'}")
        print(f"expected_penalty_0_5={output_root / 'presence_penalty_0_5' / 'predictions.jsonl'}")
        print("compare_dry_run=OK (condition outputs were not read or written)")
        return
    comparison = build_three_way_comparison(config)
    json_path, markdown_path = write_three_way_comparison(comparison, config["output_dir"])
    print(f"Comparison JSON: {json_path}")
    print(f"Comparison report: {markdown_path}")


if __name__ == "__main__":
    main()

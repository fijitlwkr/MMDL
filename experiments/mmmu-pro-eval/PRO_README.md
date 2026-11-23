# MMMU-Pro standard (10 options) evaluation

This package is the MMMU test evaluation package (`experiments/mmmu-test-eval`) with an MMMU-Pro branch added. Generation, image, prompt, Judge and scoring settings are the same as the MMMU test evaluation. Every code difference is listed in `PRO_CHANGES.md`.

| Item | Value |
|---|---|
| Dataset | `MMMU/MMMU_Pro`, config `standard (10 options)`, split `test`, revision `0d7426df4ccb3d8704a992fe6850abee7c262127` |
| Rows | 1,730 questions, 30 subjects (50 to 60 each), all multiple-choice |
| ID set | SHA-256 of sorted IDs joined by newlines: `782771460a58c18f550793866fc2cddc8575650f40450b57661d3d26b71b49fb` |
| Options | 10 options: 1,213 rows; 9: 221; 4: 125; others: 171 (maximum 12) |
| Prompt | Same structure as MMMU (`Question` / `Options` A to L / "Please select the correct answer from the options above."). The official MMMU-Pro prompts are not used, so results are not directly comparable with leaderboard values |
| Scoring | `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, with the `Final Answer` letter range widened from A-I to A-L. The rule accepts only labels present in the question's options, so results for questions with 9 or fewer options are unchanged |
| GPU | One RTX 4090, one process for all subjects |

## Overlap with MMMU validation

577 of the 1,730 rows have MMMU validation IDs (`validation_*`). Report both the full 1,730 rows and the 1,153 rows with `test_*` IDs. The overlap rule is the ID prefix. `tools/pro_metadata.json` also lists 31 `test_*` rows whose normalized question text equals a validation question. These are not counted as overlap.

## Files

- `code/`, `scripts/`: the evaluation package. `code/config_pro.yaml` differs from `code/config_test.yaml` only in the `dataset` block.
- `scripts/run_pro.sh`: one-GPU smoke and full generation.
- `tools/inspect_pro.py`: reads the text columns of the pinned parquet files and writes `pro_metadata.json` (row counts, subject counts, ID hash, option counts, validation overlap).
- `tools/build_pro_package.py`: builds this package from `experiments/mmmu-test-eval` and `pro_metadata.json`, and writes `PRO_CHANGES.md` and `PRO_FILE_HASHES.json`.
- `tools/test_pro_package.py`: CPU check with fake MMMU-Pro rows (loader, A-J prompt, ID check, scoring routes, `Final Answer` J).
- `tools/pro_pod_pipeline.sh`, `tools/pro_pod_resume.sh`: the pod run order used for B_best.

## Run

1. Verify the base model, adapter and merged model hashes as in the MMMU test package.
2. `bash scripts/setup_test_generation.sh code <records>/environment`
3. Unit tests: `code/tests` and `code/scoring/tests`. Two tests that need a `/tmp/preflight-venv` fixture fail in a plain pod. The same two are recorded as pre-existing failures in the MMMU test package regression gate.
4. Download the dataset once (`datasets.load_dataset` with the config values), then set `HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1`.
5. `python code/preflight.py --config code/config_pro.yaml --model_path "$MODEL" --data_root "$DATA_CACHE" --out <records>/preflight`. Confirm 1,730 rows, no validation failures and no input above the prompt budget.
6. `bash scripts/run_pro.sh smoke code code/config_pro.yaml "$MODEL" "$DATA_CACHE" "$OUTPUT_ROOT"`, then the same with `full`.
7. `python scripts/prepare_test_scoring.py --code code --config code/config_pro.yaml --raw "$OUTPUT_ROOT/full/raw.jsonl" --out "$SCORING_DIR" --expect-total 1730`
8. After separate approval, `bash scripts/run_test_judge.sh code "$SCORING_DIR"`.

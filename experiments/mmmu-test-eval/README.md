# MMMU test evaluation

This package runs one MMMU test evaluation with the frozen D3-e1 validation inference settings. It takes the local model directory as an input.

| Item | Fixed value |
|---|---|
| Base model | Qwen/Qwen3-VL-4B-Instruct at `ebb281ec70b05090aa6165b016eac8ec08e71b17`, bf16 |
| Dataset | MMMU/MMMU at `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`, test, 30 subjects, 10,500 questions |
| Inference | Torch 2.8.0+cu128, vLLM 0.11.0, Python 3.12.3, max model length 16,384, max new tokens 8,192 |
| Sampling | Temperature 0.7, top_p 0.8, top_k 20, repetition penalty 1.0, presence penalty 1.5, sampling and engine seed 3407 |
| Images | Original image slot order followed by question text, min 1,003,520 pixels and max 4,014,080 pixels |
| Scoring | hybrid100_mc_qwen_ab_open_no_length_gate_v2 |
| Judge | gpt-4.1-mini-2025-04-14, temperature 0, top_p 1, seed 3407, max_tokens 8 |

| Worker | Questions | Subjects |
|---|---:|---|
| GPU 0 | 5,321 | Agriculture, Architecture_and_Engineering, Art, Art_Theory, Basic_Medical_Science, Biology, Clinical_Medicine, Design, Electronics, Finance, Geography, Marketing, Materials, Music, Public_Health |
| GPU 1 | 5,179 | Accounting, Chemistry, Computer_Science, Diagnostics_and_Laboratory_Medicine, Economics, Energy_and_Power, History, Literature, Manage, Math, Mechanical_Engineering, Pharmacy, Physics, Psychology, Sociology |

Each worker sees one RTX 4090 through CUDA_VISIBLE_DEVICES and uses tensor parallel size 1. Each writes its own raw, environment manifest, metadata, and physical GPU memory samples. The fixed subject order and per-subject counts are in `code/config_test.yaml`.

## Run

1. Select the existing base Python in the pinned CUDA 12.8 image. Set `HF_HOME`, `MODEL`, `DATA_CACHE` and `OUTPUT_ROOT` in the shell. Verify each RTX 4090 with `nvidia-smi` and at least 35 GB free on the storage volume with `df -h` (about 30 GB required).
2. For adapter evaluation, use a separate PEFT 0.17.1 environment. Supply expected SHA-256 values in shard filename order. The merge command checks base and adapter hashes, copies the original processor/tokenizer/template files, and records output hashes.

   ```bash
   "$MERGE_PYTHON" scripts/test_merge_adapter.py --base "$BASE" --adapter "$ADAPTER" --out "$MODEL" \
     --base-sha256 "$BASE_SHA1" "$BASE_SHA2" --adapter-sha256 "$ADAPTER_SHA" \
     --merged-sha256 "$MERGED_SHA1" "$MERGED_SHA2"
   ```

   If a merge is new and output hashes are unavailable, omit the last option and preserve the receipt. Use the pinned base directory directly for baseline. Reuse a verified existing merge if its shard and sidecar hashes match.
3. Run the setup once and check model input lengths before generation.

   ```bash
   bash scripts/setup_test_generation.sh code "${OUTPUT_ROOT}-environment"
   python code/preflight.py --config code/config_test.yaml --model_path "$MODEL" --data_root "$DATA_CACHE" --out "${OUTPUT_ROOT}-preflight"
   ```

   Confirm all 10,500 rows in preflight, no validation failures, and no input above the fixed prompt budget. The dataset loader checks the expected test IDs and rejects missing answers.
4. Set `GPU_COUNT=1` for one RTX 4090 or `GPU_COUNT=2` for two. The one-card run uses all 30 subjects in one process and is expected to take about 12 hours. The two-card run uses the assignment above and is expected to take about 6 hours. Run smoke and the full test in separate folders. After the full workers exit successfully, the script checks their settings and validates the combined raw in configured subject and numeric ID order.

   ```bash
   bash scripts/run_test_dual.sh smoke code code/config_test.yaml "$MODEL" "$DATA_CACHE" "$OUTPUT_ROOT" "$GPU_COUNT"
   bash scripts/run_test_dual.sh full code code/config_test.yaml "$MODEL" "$DATA_CACHE" "$OUTPUT_ROOT" "$GPU_COUNT"
   ```

5. Transfer the raw files and metadata and verify the hashes recorded in `full/merge_receipt.json`. Keep the model shard hashes and the raw prompt token counts `num_prompt_tokens` for comparison across models. Run preparation on the verified combined raw. The preparation prints the request count and conservative cost estimate and uses no network.

   ```bash
   python scripts/prepare_test_scoring.py --code code --config code/config_test.yaml --raw "$OUTPUT_ROOT/full/raw.jsonl" --out "$SCORING_DIR"
   ```

6. Once approved separately, run Judge in an interactive terminal and enter the key only at the hidden prompt. The scorer keeps request receipts and leaves failed calls pending.

   ```bash
   bash scripts/run_test_judge.sh code "$SCORING_DIR"
   ```

The validation config and prompt, image, and Judge behavior are retained. The test config and split-aware checks add test counts and IDs. The test macro average is unweighted across subjects, while the overall score is weighted by question count. The runner passes the expected count for each worker and records physical VRAM separately.

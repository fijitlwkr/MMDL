# MMMU test evaluation code changes

Only the test split, subject counts, ID checks, metadata, and equal-count assumption were adapted in the evaluation code. The original validation config, generation settings, prompts, and grading policy are preserved. New scripts run the fixed GPU split and verify outputs.

```diff
--- a/code/check_env.py
+++ b/code/check_env.py
@@ -22,6 +22,11 @@
 from packaging.requirements import Requirement
 from packaging.utils import canonicalize_name
 import yaml
+
+try:
+    from .common import expected_subject_counts
+except ImportError:
+    from common import expected_subject_counts
 
 
 SECTION_NAMES = ("system", "packages", "vllm_import", "gpu", "qwen_vl_utils", "model", "data")
@@ -357,6 +362,7 @@
 def data_section(config, args):
     from datasets import load_dataset
     setting = config["dataset"]
+    expected_by_subject = expected_subject_counts(setting)
     subjects = args.subjects or setting["subjects"]
     checks = []
     total = 0
@@ -370,12 +376,13 @@
             columns_equal = first_columns is None or details["columns"] == first_columns
             if first_columns is None:
                 first_columns = details["columns"]
-            status = "PASS" if details["rows"] == setting["expected_rows_per_subject"] and columns_equal and details["ids_unique"] else "FAIL"
+            expected_rows = expected_by_subject[subject]
+            status = "PASS" if details["rows"] == expected_rows and columns_equal and details["ids_unique"] else "FAIL"
             checks.append(check(status, "subject", subject=subject, columns_match=columns_equal, **details))
         except Exception as exc:
             checks.append(check("SKIP" if is_network_error(exc) else "FAIL", "subject", subject=subject,
                                 reason=str(exc), traceback=traceback.format_exc()))
-    expected = setting["expected_total_rows"] if len(subjects) == len(setting["subjects"]) else setting["expected_rows_per_subject"] * len(subjects)
+    expected = setting["expected_total_rows"] if len(subjects) == len(setting["subjects"]) else sum(expected_by_subject[subject] for subject in subjects)
     skipped = any(item["status"] == "SKIP" for item in checks)
     checks.append(check("SKIP" if skipped else "PASS" if total == expected else "FAIL", "total_rows",
                         expected=expected, actual=total, selected_subjects=len(subjects)))
--- a/code/common.py
+++ b/code/common.py
@@ -56,10 +56,22 @@
     return list(parsed)
 
 
+def expected_subject_counts(setting: dict) -> dict[str, int]:
+    table = setting.get("expected_rows_by_subject")
+    if table is None:
+        return {subject: setting["expected_rows_per_subject"] for subject in setting["subjects"]}
+    if (set(table) != set(setting["subjects"])
+            or any(type(n) is not int or n <= 0 for n in table.values())
+            or sum(table.values()) != setting["expected_total_rows"]):
+        raise ValueError("expected_rows_by_subject must match the subject list and total")
+    return table
+
+
 def load_samples(cfg: dict, data_root: str | None, subjects: list[str] | None = None) -> list[Sample]:
     from datasets import load_dataset
 
     setting = cfg["dataset"]
+    expected = expected_subject_counts(setting)
     selected = subjects or setting["subjects"]
     unknown = set(selected) - set(setting["subjects"])
     if unknown:
@@ -71,8 +83,16 @@
             continue
         dataset = load_dataset(setting["repo_id"], subject, split=setting["split"],
                                revision=setting["revision"], cache_dir=data_root)
-        if len(dataset) != setting["expected_rows_per_subject"]:
-            raise ValueError(f"{subject}: expected {setting['expected_rows_per_subject']} rows, got {len(dataset)}")
+        if len(dataset) != expected[subject]:
+            raise ValueError(f"{subject}: expected {expected[subject]} rows, got {len(dataset)}")
+        if setting["split"] == "test":
+            ids = dataset.data.column("id").to_pylist()
+            if set(ids) != {f"test_{subject}_{i}" for i in range(1, expected[subject] + 1)}:
+                raise ValueError(f"{subject}: unexpected test IDs")
+            missing = sum(answer is None or str(answer).strip() in ("", "?")
+                          for answer in dataset.data.column("answer").to_pylist())
+            if missing:
+                raise ValueError(f"{subject}: {missing} test answers are missing")
         image_columns = sorted((int(match.group(1)), name) for name in dataset.column_names
                                if (match := IMAGE_COLUMN.fullmatch(name)))
         image_present = {name: [not missing for missing in dataset.data.column(name).is_null().to_pylist()]
--- a/code/metadata.py
+++ b/code/metadata.py
@@ -246,7 +246,8 @@
             "repo_id": cfg["dataset"]["repo_id"],
             "revision": cfg["dataset"]["revision"],
             "split": cfg["dataset"]["split"],
-            "expected_rows_per_subject": cfg["dataset"]["expected_rows_per_subject"],
+            **{key: cfg["dataset"][key] for key in ("expected_rows_per_subject", "expected_rows_by_subject")
+               if key in cfg["dataset"]},
             "expected_total_rows": cfg["dataset"]["expected_total_rows"],
             "subjects": cfg["dataset"]["subjects"],
             "loaded_subjects_count": len(stats["subject_counts"]) or len(cfg["dataset"]["subjects"]),
--- a/code/preflight.py
+++ b/code/preflight.py
@@ -136,6 +136,8 @@
     summary = {
         "processed": len(rows), "selected": len(samples),
         "partial": len(samples) != cfg["dataset"]["expected_total_rows"],
+        **({"expected_rows_by_subject": cfg["dataset"]["expected_rows_by_subject"]}
+           if "expected_rows_by_subject" in cfg["dataset"] else {}),
         "total_tokens": _distribution(counts), "by_image_count": image_counts,
         "exceeds_count": len(over), "exceeds": over,
         "max_model_len_for_zero_skips": (max(counts) + budget["max_new_tokens"]
--- a/code/scoring/evaluate.py
+++ b/code/scoring/evaluate.py
@@ -150,11 +150,24 @@
     return module
 
 
-def validate_raw(rows):
+def validate_raw(rows, dataset=None):
     unique(rows, "raw")
-    require(len(rows) == 900, "Expected all 900 validation items")
-    require(Counter(row.get("subject") for row in rows) == Counter({subject: 30 for subject in SUBJECTS}), "Expected the fixed 30 subjects x 30 items")
-    require(Counter(row.get("question_type") for row in rows) == Counter({"multiple-choice": 847, "open": 53}), "Expected MC 847 / open 53")
+    dataset = dataset or {}
+    split = dataset.get("split", "validation")
+    total = dataset.get("expected_total_rows", 900)
+    expected = dataset.get("expected_rows_by_subject")
+    if expected is None:
+        expected = {subject: dataset.get("expected_rows_per_subject", 30)
+                    for subject in dataset.get("subjects", SUBJECTS)}
+    require(len(rows) == total, f"Expected all {total} {split} items")
+    require(Counter(row.get("subject") for row in rows) == Counter(expected), "Subject counts differ from the configuration")
+    kinds = Counter(row.get("question_type") for row in rows)
+    if split == "validation":
+        require(kinds == Counter({"multiple-choice": 847, "open": 53}), "Expected MC 847 / open 53")
+    else:
+        require(set(kinds) <= {"multiple-choice", "open"}, "Unknown question type")
+    expected_ids = {f"{split}_{subject}_{number}": subject
+                    for subject, count in expected.items() for number in range(1, count + 1)}
     fields = {"schema_version", "synthetic", "id", "subject", "subfield", "topic_difficulty", "img_type", "question_type", "gold", "options", "options_raw", "image_indices", "prompt", "status", "reason", "error", "raw_text", "output_token_ids", "output_tokens", "finish_reason", "stop_reason", "max_new_tokens", "num_prompt_tokens", "precomputed_prompt_tokens"}
     for row in rows:
         label = row["id"] + ": "
@@ -164,7 +177,7 @@
         for key in ("subfield", "topic_difficulty", "img_type"):
             require(row[key] is None or isinstance(row[key], str), label + key + " must be a string or null")
         require(row["schema_version"] == "0", label + "unsupported raw schema version")
-        require(row["id"] in {f"validation_{row['subject']}_{number}" for number in range(1, 31)}, label + "ID does not belong to the fixed subject validation split")
+        require(expected_ids.get(row["id"]) == row["subject"], label + "ID does not belong to the fixed subject split")
         require(row["synthetic"] is False, label + "synthetic data not accepted")
         require(row["status"] == "ok" and row["error"] is None and row["reason"] is None, label + "inference error or unfinished row")
         require(row["raw_text"].strip() and row["prompt"].strip() and row["gold"].strip(), label + "empty input/output/reference")
@@ -223,7 +236,8 @@
     for label, field in (("by_subject", "subject"), ("by_type", "question_type"), ("by_finish", "finish_reason"), ("by_route", "route")):
         result[label] = {name: score_group([row for row in rows if row[field] == name]) for name in sorted({row[field] for row in rows})}
     result["macro_accuracy"] = None if result["overall"]["pending"] else sum(group["accuracy"] for group in result["by_subject"].values()) / len(result["by_subject"])
-    require(result["macro_accuracy"] is None or abs(result["macro_accuracy"] - result["overall"]["accuracy"]) < 1e-12, "Macro / overall mismatch")
+    if len({group["total"] for group in result["by_subject"].values()}) <= 1:
+        require(result["macro_accuracy"] is None or abs(result["macro_accuracy"] - result["overall"]["accuracy"]) < 1e-12, "Macro / overall mismatch")
     return result
 
 
@@ -252,12 +266,14 @@
 
 
 def prepare(raw, out, config, judge_model=None):
+    import yaml
+
     raw, out = Path(raw).resolve(), Path(out).resolve()
     config_data, judge_settings, prices = load_scoring_config(config, judge_model)
     data = raw.read_bytes()
     source_hash = sha(data)
     rows = [json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]
-    validate_raw(rows)
+    validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
     parsers = load_parsers()
     items = [derive_item(row, parsers) for row in rows]
     requests = [make_request(row, item, judge_settings, parsers, source_hash) for row, item in zip(rows, items) if item["route"] != "auto"]
@@ -287,6 +303,8 @@
 
 
 def load_inputs(out):
+    import yaml
+
     out = Path(out).resolve()
     manifest = read_json(out / "manifest.json")
     require(manifest.get("schema_version") == "portable-evaluation-1" and manifest["policy_id"] == POLICY, "Unsupported manifest/policy")
@@ -305,7 +323,7 @@
     for filename, key in (("items.jsonl", "items_sha256"), ("requests.jsonl", "requests_sha256")):
         require(sha((out / filename).read_bytes()) == manifest[key], filename + " hash mismatch")
     rows = read_rows(source)
-    validate_raw(rows)
+    validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
     parsers = load_parsers()
     items = read_rows(out / "items.jsonl")
     requests = read_rows(out / "requests.jsonl")
@@ -536,7 +554,7 @@
     out.mkdir(parents=True, exist_ok=True)
     write_json(out / "comparison.json", result)
     write_rows(out / "paired_results.jsonl", change_rows)
-    report = ["# 두 추론 출력의 동일 채점 정책 비교", "", "900개 ID·질문 문맥·정답·선택지·기록된 이미지 정보 및 Judge 모델/설정/채점 정책이 같은지 확인했다. API를 호출하지 않았다.", "",
+    report = ["# 두 추론 출력의 동일 채점 정책 비교", "", f"{len(lfinal)}개 ID·질문 문맥·정답·선택지·기록된 이미지 정보 및 Judge 모델/설정/채점 정책이 같은지 확인했다. API를 호출하지 않았다.", "",
               "| 항목 | left | right |", "|---|---|---|",
               f"| 기록된 max_new_tokens | {ls['max_new_tokens_values']} | {rs['max_new_tokens_values']} |",
               f"| 전체 | {format_score(ls['overall'])} | {format_score(rs['overall'])} |",
@@ -547,7 +565,7 @@
               f"| length 점수 | {format_score(ls['by_finish'].get('length', {'accuracy': None}))} | {format_score(rs['by_finish'].get('length', {'accuracy': None}))} |",
               f"| MMMU 규칙 단독 | {format_score(lmm['overall'])} | {format_score(rmm['overall'])} |",
               f"| Judge 비용 추정 | ${ls['estimated_recorded_response_cost_usd']:.6f} | ${rs['estimated_recorded_response_cost_usd']:.6f} |", "",
-              f"완료 쌍 {len(common)}/900. 오른쪽 정답 증가 {gains}, 감소 {losses}. 전체 점수 차이: " + ("pending" if not complete else f"{result['right_minus_left_accuracy_pp']:+.2f}%p") + ".", "",
+              f"완료 쌍 {len(common)}/{len(lfinal)}. 오른쪽 정답 증가 {gains}, 감소 {losses}. 전체 점수 차이: " + ("pending" if not complete else f"{result['right_minus_left_accuracy_pp']:+.2f}%p") + ".", "",
               "미완료가 있는 집단의 정확도는 pending이다. 두 파일의 length/stop 집단은 서로 다른 문항일 수 있으므로 조건부 점수를 동일 문항 비교로 해석하지 않는다.",
               "**cap만 바꾼 실험이라는 사실은 검증되지 않았다.** raw만으로 모델·데이터 revision, 생성 seed/샘플링 설정, 추론 코드 commit, 이미지 전처리·실제 이미지, 실행 환경의 일치를 증명할 수 없다. 따라서 점수 차이를 cap의 인과 효과로 단정하지 않는다. 별도 실행 메타데이터가 필요하다.",
               "Final Answer 100자는 채점 규칙이며 출력 길이 제한이 아니다. 높은 점수만으로 원문 답 추출의 충실도가 검증되는 것은 아니다.", ""]
--- a/code/validate_raw.py
+++ b/code/validate_raw.py
@@ -11,9 +11,9 @@
 import yaml
 
 try:
-    from .common import check_invariants, validate_record
+    from .common import check_invariants, expected_subject_counts, validate_record
 except ImportError:
-    from common import check_invariants, validate_record
+    from common import check_invariants, expected_subject_counts, validate_record
 
 try:
     from .metadata import validate_run_metadata
@@ -45,8 +45,7 @@
         errors.append(f"row count {len(records)} != expected {expected}")
     if expected == config["dataset"]["expected_total_rows"]:
         counts = Counter(record["subject"] for record in records)
-        required = config["dataset"]["expected_rows_per_subject"]
-        for subject in config["dataset"]["subjects"]:
+        for subject, required in expected_subject_counts(config["dataset"]).items():
             if counts[subject] != required:
                 errors.append(f"subject {subject}: {counts[subject]} != {required}")
     invariant_count = 0
--- /dev/null
+++ b/code/config_test.yaml
@@ -0,0 +1,167 @@
+model:
+  repo_id: Qwen/Qwen3-VL-4B-Instruct
+  revision: ebb281ec70b05090aa6165b016eac8ec08e71b17
+  dtype: bfloat16
+dataset:
+  repo_id: MMMU/MMMU
+  revision: 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68
+  split: test
+  expected_rows_by_subject:
+    Accounting: 380
+    Agriculture: 287
+    Architecture_and_Engineering: 551
+    Art: 231
+    Art_Theory: 429
+    Basic_Medical_Science: 326
+    Biology: 345
+    Chemistry: 603
+    Clinical_Medicine: 325
+    Computer_Science: 371
+    Design: 169
+    Diagnostics_and_Laboratory_Medicine: 162
+    Economics: 267
+    Electronics: 256
+    Energy_and_Power: 432
+    Finance: 355
+    Geography: 565
+    History: 278
+    Literature: 112
+    Manage: 245
+    Marketing: 181
+    Materials: 458
+    Math: 505
+    Mechanical_Engineering: 429
+    Music: 334
+    Pharmacy: 430
+    Physics: 408
+    Psychology: 305
+    Public_Health: 509
+    Sociology: 252
+  expected_total_rows: 10500
+  subjects:
+    - Accounting
+    - Agriculture
+    - Architecture_and_Engineering
+    - Art
+    - Art_Theory
+    - Basic_Medical_Science
+    - Biology
+    - Chemistry
+    - Clinical_Medicine
+    - Computer_Science
+    - Design
+    - Diagnostics_and_Laboratory_Medicine
+    - Economics
+    - Electronics
+    - Energy_and_Power
+    - Finance
+    - Geography
+    - History
+    - Literature
+    - Manage
+    - Marketing
+    - Materials
+    - Math
+    - Mechanical_Engineering
+    - Music
+    - Pharmacy
+    - Physics
+    - Psychology
+    - Public_Health
+    - Sociology
+environment:
+  expected_packages:
+    python: "3.12.3"
+    torch: "2.8.0+cu128"
+    vllm: "0.11.0"
+    transformers: "4.57.1"
+    tokenizers: "0.22.2"
+  min_driver_major: 570 # RunPod RTX 4090 파드(드라이버 570.211.01)에서 torch 2.8.0+cu128의 cuda.is_available()이 True였음; 환경 게이트 값이며 출력 조건이 아님
+  env_vars:
+    VLLM_ENABLE_V1_MULTIPROCESSING: "0"
+    VLLM_WORKER_MULTIPROC_METHOD: "spawn"
+    TOKENIZERS_PARALLELISM: "false"
+    VLLM_USE_FLASHINFER_SAMPLER: "0"
+prompt:
+  verified: true
+  source:
+    repo: https://github.com/QwenLM/Qwen3-VL
+    path: evaluation/mmmu/run_mmmu.py
+    commit: f8dca99056bb6352cf6ab36d4ea1848a09c54b5b
+    license: Apache-2.0
+sampling:
+  do_sample: true
+  temperature: 0.7
+  top_p: 0.8
+  top_k: 20
+  repetition_penalty: 1.0
+  presence_penalty: 1.5
+  seed: 3407 # SamplingParams seed: team addition; not specified in the README
+  engine_seed: 3407 # LLM seed: follows README Instruct evaluation seed
+  skip_special_tokens: true
+  stop_token_ids: [] # Pass to SamplingParams in Step 3; script and README vLLM example use [].
+  # Pinned model card (VL): https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct/blob/ebb281ec70b05090aa6165b016eac8ec08e71b17/README.md
+  # GitHub README (Instruct): https://github.com/QwenLM/Qwen3-VL/blob/main/README.md
+  # MMMU script: https://github.com/QwenLM/Qwen3-VL/blob/f8dca99056bb6352cf6ab36d4ea1848a09c54b5b/evaluation/mmmu/run_mmmu.py
+  # GitHub README Evaluation Reproduction > Generation Hyperparameters > Instruct models:
+  # seed=3407 and out_seq_length=32768. The script fixes LLM seed to 42 and has no SamplingParams seed.
+  # Pinned model card recommends VL out_seq_length=16384; script default is 32768.
+budget:
+  max_model_len: 16384
+  max_new_tokens: 8192 # Team choice: target <= $2 for one RunPod RTX 4090 run.
+  # Length references: pinned model card 16384; GitHub README and script 32768.
+  prompt_safety_margin: 128
+image:
+  min_pixels: 1003520
+  max_pixels: 4014080
+  image_patch_size: 16
+  spatial_merge_size: 2 # Pinned vision_config; combined image grid factor is 32.
+engine:
+  gpu_memory_utilization: 0.9
+  limit_mm_per_prompt: { image: 10, video: 0 }
+  trust_remote_code: true
+  max_num_batched_tokens: 8192
+  max_num_seqs: 256
+  mm_processor_kwargs: null
+run:
+  first_chunk_size: 16
+  chunk_size: 150
+  vram_sample_interval_seconds: 1
+  min_free_disk_gb: 20 # Resource gate threshold; not an output/reporting condition.
+  abort_error_fraction: 0.1 # 중단 기준이며 출력 조건이 아님.
+  raw_filename: raw.jsonl
+  env_filename: env.json
+  metadata_filename: run_metadata.json
+schema:
+  version: "0"
+reproducibility_note: >
+  seed를 고정해도 vLLM의 배치 구성, GPU, 라이브러리 버전에 따라 출력이 bit 단위로 재현되지는 않는다.
+  chunk_size, first_chunk_size, max_num_seqs, gpu_memory_utilization은 배치 구성을 바꿔 출력에 영향을 줄 수 있으므로 config 해시에 포함된다.
+
+# Experiment-team evaluator settings; existing inference settings above are unchanged.
+# This snapshot describes scoring, not the historical generation config of each raw.
+scoring:
+  policy: hybrid100_mc_qwen_ab_open_no_length_gate_v2
+  judge:
+    model: gpt-4.1-mini-2025-04-14
+    temperature: 0
+    top_p: 1
+    seed: 3407
+    max_tokens: 8
+  # USD per million tokens, recorded 2026-09-21; estimates, not invoice totals.
+  # https://developers.openai.com/api/docs/models/gpt-4.1-mini
+  # https://developers.openai.com/api/docs/models/gpt-3.5-turbo
+  # https://developers.openai.com/api/docs/models/gpt-4o-mini
+  prices_usd_per_million:
+    gpt-4.1-mini-2025-04-14:
+      input: 0.4
+      cached_input: 0.1
+      output: 1.6
+    gpt-3.5-turbo-0125:
+      input: 0.5
+      cached_input: 0.5
+      output: 1.5
+    gpt-4o-mini-2024-07-18:
+      input: 0.15
+      cached_input: 0.075
+      output: 0.6
--- /dev/null
+++ b/scripts/test_merge_adapter.py
@@ -0,0 +1,70 @@
+"""Verify and merge one adapter into the supplied Qwen3-VL base."""
+
+import argparse
+import hashlib
+import json
+from pathlib import Path
+import shutil
+from tempfile import TemporaryDirectory
+
+
+def sha(path):
+    with path.open("rb") as stream:
+        return hashlib.file_digest(stream, "sha256").hexdigest()
+
+
+def shards(folder):
+    return {path.name: sha(path) for path in sorted(folder.glob("model*.safetensors"))}
+
+
+def main():
+    parser = argparse.ArgumentParser(description=__doc__)
+    for name in ("base", "adapter", "out"):
+        parser.add_argument(f"--{name}", type=Path, required=True)
+    parser.add_argument("--base-sha256", nargs="+", required=True)
+    parser.add_argument("--adapter-sha256", required=True)
+    parser.add_argument("--merged-sha256", nargs="+")
+    args = parser.parse_args()
+    if args.out.exists():
+        parser.error("use a new output directory")
+    original = shards(args.base)
+    if list(original.values()) != args.base_sha256:
+        raise ValueError("Base shard hashes differ")
+    if sha(args.adapter / "adapter_model.safetensors") != args.adapter_sha256:
+        raise ValueError("Adapter hash differs")
+
+    from importlib.metadata import version
+    import torch
+    from peft import PeftModel
+    from transformers import Qwen3VLForConditionalGeneration
+
+    if version("peft") != "0.17.1" or torch.__version__ != "2.8.0+cu128":
+        raise ValueError("Expected PEFT 0.17.1 and Torch 2.8.0+cu128")
+    model = Qwen3VLForConditionalGeneration.from_pretrained(
+        args.base, dtype=torch.bfloat16, attn_implementation="sdpa", device_map="cpu")
+    merged = PeftModel.from_pretrained(model, args.adapter).merge_and_unload(safe_merge=True)
+    args.out.parent.mkdir(parents=True, exist_ok=True)
+    with TemporaryDirectory(dir=args.out.parent) as temp:
+        staged = Path(temp) / "merged"
+        merged.save_pretrained(staged, safe_serialization=True)
+        copied = {}
+        for source in args.base.iterdir():
+            if source.is_file() and source.suffix in {".json", ".jinja", ".txt"} and source.name not in {
+                    "config.json", "model.safetensors.index.json"}:
+                dest = staged / source.name
+                shutil.copyfile(source, dest)
+                copied[dest.name] = sha(dest)
+                if copied[dest.name] != sha(source):
+                    raise ValueError(f"Sidecar hash differs: {source.name}")
+        result = shards(staged)
+        if args.merged_sha256 and list(result.values()) != args.merged_sha256:
+            raise ValueError(f"Merged shard hashes differ: {result}")
+        receipt = {"base_sha256": original, "adapter_sha256": args.adapter_sha256,
+                   "merged_sha256": result, "sidecar_sha256": copied}
+        (staged / "merge_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
+        staged.rename(args.out)
+    print(json.dumps(receipt, indent=2))
+
+
+if __name__ == "__main__":
+    main()
--- /dev/null
+++ b/scripts/test_shards.py
@@ -0,0 +1,130 @@
+"""Fixed MMMU test GPU assignment and completed-shard verification."""
+
+import argparse
+from collections import Counter
+import csv
+import hashlib
+import json
+from pathlib import Path
+import statistics
+import sys
+
+import yaml
+
+GPU0 = """Agriculture Architecture_and_Engineering Art Art_Theory Basic_Medical_Science
+Biology Clinical_Medicine Design Electronics Finance Geography Marketing Materials Music Public_Health""".split()
+
+
+def load(path):
+    return json.loads(path.read_bytes())
+
+
+def sha(path):
+    with path.open("rb") as stream:
+        return hashlib.file_digest(stream, "sha256").hexdigest()
+
+
+def plan(config):
+    dataset = yaml.safe_load(config.read_bytes())["dataset"]
+    counts, subjects = dataset["expected_rows_by_subject"], dataset["subjects"]
+    if dataset["split"] != "test" or sum(counts.values()) != 10500 or dataset["expected_total_rows"] != 10500:
+        raise ValueError("Expected the fixed test dataset configuration")
+    if set(counts) != set(subjects) or not set(GPU0) < set(subjects) or len(subjects) != 30:
+        raise ValueError("Unexpected subject list")
+    shards = [GPU0, [subject for subject in subjects if subject not in GPU0]]
+    if [sum(counts[s] for s in group) for group in shards] != [5321, 5179]:
+        raise ValueError("Unexpected GPU shard counts")
+    return counts, subjects, shards
+
+
+def merge(root, config):
+    counts, subjects, shards = plan(config)
+    config_sha = sha(config)
+    expected_ids = [f"test_{subject}_{i}" for subject in subjects for i in range(1, counts[subject] + 1)]
+    combined = root / "raw.jsonl"
+    receipt = root / "merge_receipt.json"
+    if combined.exists() or receipt.exists():
+        raise FileExistsError("Combined output already exists")
+    lines, settings, stats = {}, [], {}
+    for gpu, shard in enumerate(shards):
+        folder = root / f"gpu{gpu}"
+        raw = folder / "raw.jsonl"
+        env = load(folder / "env.json")
+        meta = load(folder / "run_metadata.json")
+        assert (folder / "worker.exit").read_text().strip() == "0"
+        assert env["config_sha256"] == meta["code_and_reproduction"]["config"]["sha256"] == config_sha
+        assert env["subjects"] == shard and env["limit"] is None and not env["dry_run"]
+        assert len(env["invocations"]) == 1 and not env["engine_overrides"]
+        settings.append({key: meta[key] for key in ("model", "generation", "prompt", "image_processing", "environment")})
+        assert settings[-1]["environment"]["parallelism"]["tensor_parallel_size"] == 1
+        assert settings[-1]["environment"]["env_vars"].pop("CUDA_VISIBLE_DEVICES") == str(gpu)
+        digest = sha(raw)
+        assert digest == meta["run"]["raw_file"]["sha256"]
+        expected = {f"test_{subject}_{i}" for subject in shard for i in range(1, counts[subject] + 1)}
+        seen, finishes, tokens, input_tokens = set(), Counter(), [], 0
+        with raw.open("rb") as stream:
+            for line in stream:
+                assert line.endswith(b"\n")
+                row = json.loads(line)
+                qid = row["id"]
+                assert qid in expected and qid not in lines and row["status"] == "ok" and not row["synthetic"]
+                assert row["finish_reason"] in {"stop", "length"}
+                assert row["precomputed_prompt_tokens"] == row["num_prompt_tokens"] > 0
+                assert 0 < row["output_tokens"] == len(row["output_token_ids"]) <= row["max_new_tokens"] == 8192
+                assert row["finish_reason"] != "length" or row["output_tokens"] == 8192
+                seen.add(qid)
+                lines[qid] = line
+                finishes[row["finish_reason"]] += 1
+                tokens.append(row["output_tokens"])
+                input_tokens += row["num_prompt_tokens"]
+        assert seen == expected and sum(tokens) == meta["run"]["token_stats"]["total"]
+        with (folder / "physical_gpu_memory.csv").open(encoding="utf-8") as stream:
+            samples = [int(row[2]) for row in csv.reader(stream) if len(row) == 4 and int(row[1]) == gpu]
+        assert samples
+        stats[f"gpu{gpu}"] = {"rows": len(seen), "raw_sha256": digest, "length": finishes["length"],
+                             "output_tokens_total": sum(tokens), "output_tokens_mean": statistics.mean(tokens),
+                             "output_tokens_median": statistics.median(tokens), "prompt_tokens_total": input_tokens,
+                             "duration_seconds": meta["run"]["duration_seconds"], "max_vram_mib": max(samples)}
+    assert settings[0] == settings[1], "Shard generation settings differ"
+    assert set(lines) == set(expected_ids) and len(lines) == 10500
+    with combined.open("xb") as stream:
+        stream.writelines(lines[qid] for qid in expected_ids)
+    result = {"status": "PASS", "rows": len(lines), "errors": 0, "subject_counts": counts,
+              "config_sha256": config_sha, "raw_sha256": sha(combined), "gpu_shards": stats}
+    with receipt.open("x", encoding="utf-8") as stream:
+        json.dump(result, stream, indent=2)
+        stream.write("\n")
+    print(json.dumps(result))
+
+
+def main():
+    parser = argparse.ArgumentParser(description=__doc__)
+    parser.add_argument("--config", required=True, type=Path)
+    modes = parser.add_mutually_exclusive_group(required=True)
+    modes.add_argument("--gpu", type=int, choices=(0, 1))
+    modes.add_argument("--merge", type=Path)
+    modes.add_argument("--smoke", type=Path)
+    args = parser.parse_args()
+    if args.merge:
+        merge(args.merge, args.config)
+    elif args.smoke:
+        _, _, groups = plan(args.config)
+        for gpu, group in enumerate(groups):
+            folder = args.smoke / f"gpu{gpu}"
+            assert (folder / "worker.exit").read_text().strip() == "0"
+            rows = [json.loads(line) for line in (folder / "raw.jsonl").read_bytes().splitlines()]
+            assert len(rows) == len({row["id"] for row in rows}) == 3
+            for row in rows:
+                assert row["subject"] in group and row["status"] == "ok" and not row["synthetic"]
+                assert row["precomputed_prompt_tokens"] == row["num_prompt_tokens"] > 0
+                assert row["output_tokens"] > 0 and row["finish_reason"] in {"stop", "length"}
+        print("Smoke verified: 3 rows per GPU")
+    else:
+        counts, _, shards = plan(args.config)
+        group = shards[args.gpu]
+        print(",".join(group))
+        print(sum(counts[subject] for subject in group))
+
+
+if __name__ == "__main__":
+    main()
--- /dev/null
+++ b/scripts/run_test_dual.sh
@@ -0,0 +1,61 @@
+#!/usr/bin/env bash
+set -euo pipefail
+if [[ $# -ne 6 || ( "$1" != smoke && "$1" != full ) ]]; then
+  echo "Usage: run_test_dual.sh smoke|full CODE_DIR CONFIG_TEST MODEL_DIR DATA_CACHE OUTPUT_ROOT" >&2
+  exit 2
+fi
+mode=$1
+code=$(realpath "$2")
+config=$(realpath "$3")
+model=$(realpath "$4")
+data=$(realpath "$5")
+root=$(realpath -m "$6")
+scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
+: "${HF_HOME:?Set HF_HOME before running}"
+export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
+mapfile -t gpu_names < <(nvidia-smi --query-gpu=name --format=csv,noheader)
+[[ "${#gpu_names[@]}" == 2 && "${gpu_names[0]}" == "NVIDIA GeForce RTX 4090" && "${gpu_names[1]}" == "NVIDIA GeForce RTX 4090" ]]
+if [[ "$mode" == full ]]; then
+  python "$scripts/test_shards.py" --config "$config" --smoke "$root/smoke"
+fi
+mkdir -p "$root"
+mkdir "$root/$mode"
+run_worker() (
+  set -euo pipefail
+  gpu=$1
+  dir="$root/$mode/gpu$gpu"
+  mkdir "$dir"
+  mapfile -t plan < <(python "$scripts/test_shards.py" --config "$config" --gpu "$gpu")
+  [[ "${#plan[@]}" == 2 ]]
+  export CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES="$gpu"
+  python -c 'import torch; assert torch.__version__=="2.8.0+cu128" and torch.cuda.device_count()==1; assert "RTX 4090" in torch.cuda.get_device_name(0)'
+  nvidia-smi -i "$gpu" --query-gpu=timestamp,index,memory.used,memory.total --format=csv,noheader,nounits -l 1 > "$dir/physical_gpu_memory.csv" &
+  sampler=$!
+  trap 'rc=$?; kill "$sampler" 2>/dev/null || true; printf "%s\n" "$rc" > "$dir/worker.exit"' EXIT
+  flags=()
+  expected="${plan[1]}"
+  if [[ "$mode" == smoke ]]; then
+    expected=3
+    flags=(--limit 3)
+  fi
+  EXPECT_ROWS="$expected" bash "$code/run_generate.sh" --config "$config" --model_path "$model" \
+    --data_root "$data" --out "$dir" --subjects "${plan[0]}" "${flags[@]}" > "$dir/worker.log" 2>&1
+)
+run_worker 0 &
+pid0=$!
+run_worker 1 &
+pid1=$!
+rc0=0
+rc1=0
+wait "$pid0" || rc0=$?
+wait "$pid1" || rc1=$?
+printf 'gpu0=%s gpu1=%s\n' "$rc0" "$rc1"
+if (( rc0 || rc1 )); then
+  exit 1
+fi
+if [[ "$mode" == smoke ]]; then
+  python "$scripts/test_shards.py" --config "$config" --smoke "$root/smoke"
+else
+  python "$scripts/test_shards.py" --config "$config" --merge "$root/full"
+  python "$code/validate_raw.py" --config "$config" --raw "$root/full/raw.jsonl" --expect 10500
+fi
--- /dev/null
+++ b/scripts/setup_test_generation.sh
@@ -0,0 +1,41 @@
+#!/usr/bin/env bash
+set -euo pipefail
+if [[ $# -ne 2 ]]; then
+  echo "Usage: setup_test_generation.sh CODE_DIR NEW_RECORDS_DIR" >&2
+  exit 2
+fi
+SCRIPT_DIR=$(realpath "$1")
+OUT=$(realpath -m "$2")
+mkdir "$OUT"
+mkdir "$OUT/logs"
+export SCRIPT_DIR OUT INSTALL=1
+python - <<'PY'
+from importlib.metadata import version
+from pathlib import Path
+import os
+import torch
+assert version("torch") == torch.__version__ == "2.8.0+cu128"
+text = (Path(os.environ["SCRIPT_DIR"]) / "run_generate.sh").read_bytes()
+start = text.index(b"if (( INSTALL )); then\n")
+end = text.index(b"python -m pip freeze", start)
+(Path(os.environ["OUT"]) / "install_block.sh").write_bytes(text[start:end])
+PY
+python -m pip install --dry-run --break-system-packages --report "$OUT/install_plan.json" \
+  -r "$SCRIPT_DIR/requirements.txt" > "$OUT/install_plan.log" 2>&1
+python - "$OUT/install_plan.json" <<'PY'
+import json
+from pathlib import Path
+import sys
+plans = json.loads(Path(sys.argv[1]).read_bytes())["install"]
+assert "torch" not in {item["metadata"]["name"].lower() for item in plans}, "Torch replacement planned"
+PY
+bash -euo pipefail "$OUT/install_block.sh"
+python - <<'PY'
+from importlib.metadata import version
+import torch
+assert version("torch") == torch.__version__ == "2.8.0+cu128"
+assert version("vllm") == "0.11.0"
+print(version("torch"), torch.__version__, version("vllm"))
+PY
+python -m pip check | tee "$OUT/pip_check.txt"
+python -m pip freeze > "$OUT/packages.txt"
--- /dev/null
+++ b/scripts/prepare_test_scoring.py
@@ -0,0 +1,49 @@
+"""Prepare frozen v2 scoring offline and report the request budget."""
+
+import argparse
+from decimal import Decimal
+import json
+from pathlib import Path
+import runpy
+import socket
+import sys
+from unittest.mock import patch
+
+
+def main():
+    parser = argparse.ArgumentParser(description=__doc__)
+    for name in ("code", "config", "raw", "out"):
+        parser.add_argument(f"--{name}", type=Path, required=True)
+    args = parser.parse_args()
+    evaluator = args.code / "scoring/evaluate.py"
+    sys.argv = [str(evaluator), "prepare", "--config", str(args.config), "--raw", str(args.raw),
+                "--out", str(args.out)]
+    offline = RuntimeError("Network is disabled for offline scoring preparation")
+    with patch.object(socket, "socket", side_effect=offline), +         patch.object(socket, "create_connection", side_effect=offline):
+        try:
+            runpy.run_path(sys.argv[0], run_name="__main__")
+        except SystemExit as error:
+            if error.code not in (None, 0):
+                raise
+    manifest = json.loads((args.out / "manifest.json").read_bytes())
+    summary = json.loads((args.out / "summary.json").read_bytes())
+    requests = [json.loads(line) for line in (args.out / "requests.jsonl").read_bytes().splitlines()]
+    assert manifest["total"] == 10500 and len(requests) == summary["overall"]["pending"] == manifest["judge_count"]
+    assert summary["response_count"] == 0
+    prices = manifest["price_per_million_usd"]
+    input_bound = sum(len(json.dumps(row["request"], ensure_ascii=False, sort_keys=True,
+                                    separators=(",", ":")).encode("utf-8")) + 128 for row in requests)
+    output_bound = sum(row["request"]["max_tokens"] for row in requests)
+    cost = (input_bound * Decimal(str(prices["input"])) + output_bound * Decimal(str(prices["output"]))) / 1_000_000
+    result = {"raw_sha256": manifest["source_sha256"], "automatic": manifest["automatic_count"],
+              "judge": len(requests), "rule_extraction_failure": sum(r["route"] == "judge_rule_failure" for r in requests),
+              "conflict": sum(r["route"] == "judge_conflict" for r in requests), "api_calls": 0,
+              "conservative_cost_usd": str(cost), "input_tokens_bound": input_bound, "output_tokens_bound": output_bound}
+    with (args.out / "preparation_budget.json").open("x", encoding="utf-8") as stream:
+        json.dump(result, stream, indent=2)
+        stream.write("\n")
+    print(json.dumps(result))
+
+
+if __name__ == "__main__":
+    main()
--- /dev/null
+++ b/scripts/run_test_judge.sh
@@ -0,0 +1,8 @@
+#!/usr/bin/env bash
+set -euo pipefail
+if [[ $# -ne 2 ]]; then
+  echo "Usage: run_test_judge.sh CODE_DIR APPROVED_PREPARED_SCORING_DIR" >&2
+  exit 2
+fi
+python "$1/scoring/evaluate.py" run --out "$2" --ask-key
+python "$1/scoring/evaluate.py" summarize --out "$2"
```


## Scoring-time handling of trailing empty options (2026-11-22)

Multiple-choice scoring uses the contiguous nonblank options after trimming trailing blank entries. Preparation records affected IDs and option counts. The test preparation wrapper saves routing and request budgets without computing scores.

```diff
diff --git a/README.md b/README.md
index a1fcd68..acae145 100644
--- a/README.md
+++ b/README.md
@@ -49,0 +50 @@ Each worker sees one RTX 4090 through CUDA_VISIBLE_DEVICES and uses tensor paral
+   Trailing blank multiple-choice options are removed from the scoring choices and listed in `manifest.json`, with the raw and input prompt preserved. Preparation saves routing and Judge requests without calculating scores.
diff --git a/code/scoring/evaluate.py b/code/scoring/evaluate.py
index 6052422..74d35ca 100644
--- a/code/scoring/evaluate.py
+++ b/code/scoring/evaluate.py
@@ -152,0 +153,7 @@ def load_parsers():
+def mc_scoring_options(options):
+    end = len(options)
+    while end and not options[end - 1].strip():
+        end -= 1
+    return options[:end]
+
+
@@ -171,0 +179 @@ def validate_raw(rows, dataset=None):
+    removed = []
@@ -186 +194,2 @@ def validate_raw(rows, dataset=None):
-        require(isinstance(row["options"], list) and all(isinstance(text, str) and text.strip() for text in row["options"]), label + "invalid options list")
+        options = row["options"]
+        require(isinstance(options, list) and all(isinstance(text, str) for text in options), label + "invalid options list")
@@ -188 +197,6 @@ def validate_raw(rows, dataset=None):
-            require(2 <= len(row["options"]) <= 26 and row["gold"] in [chr(65 + index) for index in range(len(row["options"]))], label + "invalid MC gold/options")
+            scoring_options = mc_scoring_options(options)
+            require(all(text.strip() for text in scoring_options), label + "invalid options list")
+            count = len(scoring_options)
+            require(2 <= count <= 26 and row["gold"] in [chr(65 + index) for index in range(count)], label + "invalid MC gold/options")
+            if count != len(options):
+                removed.append({"id": row["id"], "option_count_before": len(options), "option_count_after": count})
@@ -190 +204 @@ def validate_raw(rows, dataset=None):
-            require(row["options"] == [], label + "open options must be empty")
+            require(options == [], label + "open options must be empty")
@@ -199,0 +214 @@ def validate_raw(rows, dataset=None):
+    return removed
@@ -204 +219 @@ def derive_item(row, parsers):
-    choices = {"A": row["gold"], "B": "Other Answers"} if is_open else {chr(65 + index): value for index, value in enumerate(row["options"])}
+    choices = {"A": row["gold"], "B": "Other Answers"} if is_open else {chr(65 + index): value for index, value in enumerate(mc_scoring_options(row["options"]))}
@@ -249 +264 @@ def mmmu_diagnostic(rows, parsers):
-            choices = {chr(65 + index): text for index, text in enumerate(row["options"])}
+            choices = {chr(65 + index): text for index, text in enumerate(mc_scoring_options(row["options"]))}
@@ -268 +283 @@ def mmmu_diagnostic(rows, parsers):
-def prepare(raw, out, config, judge_model=None):
+def prepare(raw, out, config, judge_model=None, *, requests_only=False):
@@ -276 +291 @@ def prepare(raw, out, config, judge_model=None):
-    validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
+    removed = validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
@@ -280 +295,2 @@ def prepare(raw, out, config, judge_model=None):
-    diagnostic, diagnostic_rows = mmmu_diagnostic(rows, parsers)
+    if not requests_only:
+        diagnostic, diagnostic_rows = mmmu_diagnostic(rows, parsers)
@@ -292,0 +309 @@ def prepare(raw, out, config, judge_model=None):
+                    "trailing_empty_mc_options_removed": removed,
@@ -296 +313,2 @@ def prepare(raw, out, config, judge_model=None):
-                    "policy_notes": ["MC gold hidden from Judge; open A contains verbatim gold and B is Other Answers.", "Only rule failures and MC rule conflicts go to Judge, regardless of backbone finish_reason; no random fallback or retries of completed Z.", "Pinned prompt lists A-D/Z; parsing permits all actual option labels.", "Raw snapshot is byte-identical; original input was not modified."]}
+                    "policy_notes": ["MC gold hidden from Judge; open A contains verbatim gold and B is Other Answers.", "Only rule failures and MC rule conflicts go to Judge, regardless of backbone finish_reason; no random fallback or retries of completed Z.", "Pinned prompt lists A-D/Z; parsing permits all actual option labels.", "Raw snapshot is byte-identical; original input was not modified.",
+                                     "Trailing whitespace-only MC options are dropped from scoring choices; the raw record and input prompt are kept verbatim."]}
@@ -297,0 +316,3 @@ def prepare(raw, out, config, judge_model=None):
+        require(sha(raw.read_bytes()) == source_hash, "Original input changed during preparation")
+        if requests_only:
+            return {"automatic_count": manifest["automatic_count"], "judge_count": manifest["judge_count"]}
@@ -300,3 +321 @@ def prepare(raw, out, config, judge_model=None):
-        require(sha(raw.read_bytes()) == source_hash, "Original input changed during preparation")
-        result = summarize(out)
-    return result
+        return summarize(out)
@@ -326 +345,2 @@ def load_inputs(out):
-    validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
+    removed = validate_raw(rows, yaml.safe_load(config_data).get("dataset"))
+    require(manifest["trailing_empty_mc_options_removed"] == removed, "Trailing empty option metadata differs from the raw")
@@ -583,0 +604 @@ def main():
+    p.add_argument("--requests-only", action="store_true", help="Save routing and requests without calculating scores")
@@ -597 +618 @@ def main():
-            result = prepare(args.raw, args.out, args.config, args.judge_model)
+            result = prepare(args.raw, args.out, args.config, args.judge_model, requests_only=args.requests_only)
diff --git a/code/scoring/tests/test_evaluate.py b/code/scoring/tests/test_evaluate.py
index 9ea6974..cf3e45c 100644
--- a/code/scoring/tests/test_evaluate.py
+++ b/code/scoring/tests/test_evaluate.py
@@ -203,0 +204,49 @@ class EvaluationTests(unittest.TestCase):
+    def test_trailing_empty_choices_are_removed_only_for_scoring(self):
+        self.rows[0].update(options=["first option", "second option", "third option", "", " \t"],
+                            options_raw="['first option', 'second option', 'third option', '', ' \\t']",
+                            prompt="Fixture question\nA. first option\nB. second option\nC. third option\nD. \nE. \t",
+                            raw_text="D")
+        ev.write_rows(self.raw, self.rows)
+        before = self.raw.read_bytes()
+        with patch.object(ev, "summarize", side_effect=AssertionError("Scoring is disabled")), \
+             patch.object(ev, "mmmu_diagnostic", side_effect=AssertionError("Scoring is disabled")):
+            result = ev.prepare(self.raw, self.out, CONFIG, requests_only=True)
+        self.assertEqual(result, {"automatic_count": 898, "judge_count": 2})
+        output = ev.load_inputs(self.out)
+        self.assertEqual(output[1]["trailing_empty_mc_options_removed"],
+                         [{"id": self.rows[0]["id"], "option_count_before": 5, "option_count_after": 3}])
+        self.assertEqual(output[2][0], self.rows[0])
+        self.assertEqual(output[3][0]["choices"], {"A": "first option", "B": "second option", "C": "third option"})
+        self.assertEqual(output[3][0]["route"], "judge_rule_failure")
+        self.assertEqual(self.raw.read_bytes(), before)
+        self.assertEqual((self.out / "input/raw.jsonl").read_bytes(), before)
+        self.assertFalse((self.out / "summary.json").exists())
+        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-secret"}), \
+             patch.object(ev.urllib.request, "urlopen", return_value=FakeHTTP("D")) as api:
+            ev.run(self.out, limit=1)
+        api.assert_called_once()
+        result = ev.read_rows(self.out / "final_results.jsonl")[0]
+        self.assertFalse(result["final_correct"])
+        self.assertEqual(result["final_status"], "extraction_failure")
+
+    def test_internal_empty_choice_is_rejected(self):
+        self.rows[0]["options"] = ["first option", " \t", "third option", ""]
+        with self.assertRaisesRegex(ValueError, "invalid options list"):
+            ev.validate_raw(self.rows)
+
+    def test_invalid_mc_gold_or_too_few_choices_after_trimming_is_rejected(self):
+        for gold, options in (("C", ["first option", "second option", ""]), ("A", ["first option", ""])):
+            with self.subTest(gold=gold, options=options):
+                self.rows[0].update(gold=gold, options=options)
+                with self.assertRaisesRegex(ValueError, "invalid MC gold/options"):
+                    ev.validate_raw(self.rows)
+
+    def test_nonempty_choices_keep_the_existing_labels_and_routing(self):
+        self.assertEqual(ev.validate_raw(self.rows), [])
+        self.prepare()
+        manifest = ev.read_json(self.out / "manifest.json")
+        self.assertEqual(manifest["trailing_empty_mc_options_removed"], [])
+        items = ev.read_rows(self.out / "items.jsonl")
+        self.assertEqual(items[2]["choices"], {"A": "first option", "B": "second option"})
+        self.assertEqual((items[2]["route"], items[2]["auto_answer"]), ("auto", "A"))
+
diff --git a/scripts/prepare_test_scoring.py b/scripts/prepare_test_scoring.py
index fe0d3e4..47a1395 100644
--- a/scripts/prepare_test_scoring.py
+++ b/scripts/prepare_test_scoring.py
@@ -20 +20 @@ def main():
-                "--out", str(args.out)]
+                "--out", str(args.out), "--requests-only"]
@@ -32 +31,0 @@ def main():
-    summary = json.loads((args.out / "summary.json").read_bytes())
@@ -34,2 +33,2 @@ def main():
-    assert manifest["total"] == 10500 and len(requests) == summary["overall"]["pending"] == manifest["judge_count"]
-    assert summary["response_count"] == 0
+    assert manifest["total"] == 10500 and len(requests) == manifest["judge_count"]
+    assert manifest["automatic_count"] + len(requests) == manifest["total"]
```

# PRO_CHANGES

- base: `experiments/mmmu-test-eval` (branch `exp/mmmu-test-eval`)
- metadata sha256: `69c9f22433023db481ba0e5a3a86797eb25e9a5d310bdb56442177236c5a2100`
- 생성·이미지·프롬프트·채점 규칙 코드는 그대로다. 아래 diff가 전부다(+ 새 파일 `scripts/run_pro.sh`).

```diff
--- a/code/common.py
+++ b/code/common.py
@@ -65,6 +65,57 @@
             or sum(table.values()) != setting["expected_total_rows"]):
         raise ValueError("expected_rows_by_subject must match the subject list and total")
     return table
+
+
+def ids_digest(ids: list[str]) -> str:
+    import hashlib
+
+    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()
+
+
+def _load_pro_samples(setting: dict, data_root: str | None, selected: list[str],
+                      expected: dict[str, int]) -> list[Sample]:
+    """MMMU-Pro standard: one config, one split; every row is multiple-choice."""
+    from collections import Counter
+    from datasets import load_dataset
+
+    if not setting.get("expected_ids_sha256"):
+        raise ValueError("dataset.expected_ids_sha256 must be pinned before loading MMMU-Pro")
+    dataset = load_dataset(setting["repo_id"], setting["config_name"], split=setting["split"],
+                           revision=setting["revision"], cache_dir=data_root)
+    if len(dataset) != setting["expected_total_rows"]:
+        raise ValueError(f"expected {setting['expected_total_rows']} rows, got {len(dataset)}")
+    ids = dataset.data.column("id").to_pylist()
+    if len(set(ids)) != len(ids) or ids_digest(ids) != setting["expected_ids_sha256"]:
+        raise ValueError("MMMU-Pro IDs differ from the pinned ID set")
+    subjects = dataset.data.column("subject").to_pylist()
+    if dict(Counter(subjects)) != expected:
+        raise ValueError("MMMU-Pro subject counts differ from the configuration")
+    image_columns = sorted((int(match.group(1)), name) for name in dataset.column_names
+                           if (match := IMAGE_COLUMN.fullmatch(name)))
+    image_present = {name: [not missing for missing in dataset.data.column(name).is_null().to_pylist()]
+                     for _, name in image_columns}
+    metadata = dataset.remove_columns([name for _, name in image_columns])
+    wanted = set(selected)
+    samples = []
+    for subject in setting["subjects"]:
+        if subject not in wanted:
+            continue
+        for index in (i for i, value in enumerate(subjects) if value == subject):
+            row = metadata[index]
+            raw = row["options"]
+            if not isinstance(raw, str):
+                raise TypeError(f"{row['id']}: options is not a string")
+            options = _parse_options(raw, "multiple-choice")
+            if row["answer"] not in [chr(65 + i) for i in range(len(options))]:
+                raise ValueError(f"{row['id']}: answer is not an option letter")
+            present = [number for number, name in image_columns if image_present[name][index]]
+            samples.append(Sample(id=row["id"], subject=subject, subfield=None,
+                                  topic_difficulty=row.get("topic_difficulty"), img_type=row.get("img_type"),
+                                  question_type="multiple-choice", question=row["question"],
+                                  options=options, options_raw=raw, answer=row["answer"],
+                                  image_indices=present, dataset=dataset, row_index=index))
+    return samples
 
 
 def load_samples(cfg: dict, data_root: str | None, subjects: list[str] | None = None) -> list[Sample]:

--- a/code/common.py
+++ b/code/common.py
@@ -128,6 +128,11 @@
     if unknown:
         raise ValueError(f"unknown subjects: {sorted(unknown)}")
     selected_set = set(selected)
+    if setting.get("format") == "mmmu_pro":
+        samples = _load_pro_samples(setting, data_root, selected, expected)
+        if len(selected_set) == len(setting["subjects"]) and len(samples) != setting["expected_total_rows"]:
+            raise ValueError(f"expected {setting['expected_total_rows']} total rows, got {len(samples)}")
+        return samples
     samples = []
     for subject in setting["subjects"]:
         if subject not in selected_set:

--- a/code/metadata.py
+++ b/code/metadata.py
@@ -419,10 +419,10 @@
 
     # Check dataset info
     ds = data.get("dataset", {})
-    if ds.get("repo_id") != "MMMU/MMMU":
-        errors.append(f"unexpected dataset repo_id: {ds.get('repo_id')}")
-    if ds.get("revision") != "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68":
-        errors.append(f"unexpected dataset revision: {ds.get('revision')}")
+    pinned_datasets = {("MMMU/MMMU", "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"),
+                       ("MMMU/MMMU_Pro", "0d7426df4ccb3d8704a992fe6850abee7c262127")}
+    if (ds.get("repo_id"), ds.get("revision")) not in pinned_datasets:
+        errors.append(f"unexpected dataset: {ds.get('repo_id')} @ {ds.get('revision')}")
 
     # Check raw_file connection if raw_path is available
     if raw_path is None and "raw_file" in data.get("run", {}):

--- a/code/scoring/evaluate.py
+++ b/code/scoring/evaluate.py
@@ -173,8 +173,15 @@
         require(kinds == Counter({"multiple-choice": 847, "open": 53}), "Expected MC 847 / open 53")
     else:
         require(set(kinds) <= {"multiple-choice", "open"}, "Unknown question type")
-    expected_ids = {f"{split}_{subject}_{number}": subject
-                    for subject, count in expected.items() for number in range(1, count + 1)}
+    if dataset.get("format") == "mmmu_pro":
+        pinned = dataset.get("expected_ids_sha256")
+        require(bool(pinned) and sha("\n".join(sorted(row["id"] for row in rows)).encode("utf-8")) == pinned,
+                "IDs differ from the pinned MMMU-Pro ID set")
+        require(set(kinds) == {"multiple-choice"}, "MMMU-Pro rows must be multiple-choice")
+        expected_ids = {row["id"]: row["subject"] for row in rows}
+    else:
+        expected_ids = {f"{split}_{subject}_{number}": subject
+                        for subject, count in expected.items() for number in range(1, count + 1)}
     fields = {"schema_version", "synthetic", "id", "subject", "subfield", "topic_difficulty", "img_type", "question_type", "gold", "options", "options_raw", "image_indices", "prompt", "status", "reason", "error", "raw_text", "output_token_ids", "output_tokens", "finish_reason", "stop_reason", "max_new_tokens", "num_prompt_tokens", "precomputed_prompt_tokens"}
     removed = []
     for row in rows:

--- a/code/scoring/frozen/parsers.py
+++ b/code/scoring/frozen/parsers.py
@@ -60,7 +60,7 @@
 # Exact legacy rule from our 2048/9048 experiments. It is a candidate under audit,
 # NOT an official MMMU rule and NOT proof that the model committed to this answer.
 FINAL_ANSWER_RE = re.compile(
-    r"(?i)\b(?:the\s+)?final\s+answer\s*(?:is\s*)?(?::|=|-)?\s*\*{0,2}\s*\(?([A-I])\)?\b"
+    r"(?i)\b(?:the\s+)?final\s+answer\s*(?:is\s*)?(?::|=|-)?\s*\*{0,2}\s*\(?([A-L])\)?\b"
 )
 
 

--- a/scripts/prepare_test_scoring.py
+++ b/scripts/prepare_test_scoring.py
@@ -14,6 +14,7 @@
     parser = argparse.ArgumentParser(description=__doc__)
     for name in ("code", "config", "raw", "out"):
         parser.add_argument(f"--{name}", type=Path, required=True)
+    parser.add_argument("--expect-total", type=int, default=10500)
     args = parser.parse_args()
     evaluator = args.code / "scoring/evaluate.py"
     sys.argv = [str(evaluator), "prepare", "--config", str(args.config), "--raw", str(args.raw),

--- a/scripts/prepare_test_scoring.py
+++ b/scripts/prepare_test_scoring.py
@@ -31,7 +31,7 @@
                 raise
     manifest = json.loads((args.out / "manifest.json").read_bytes())
     requests = [json.loads(line) for line in (args.out / "requests.jsonl").read_bytes().splitlines()]
-    assert manifest["total"] == 10500 and len(requests) == manifest["judge_count"]
+    assert manifest["total"] == args.expect_total and len(requests) == manifest["judge_count"]
     assert manifest["automatic_count"] + len(requests) == manifest["total"]
     prices = manifest["price_per_million_usd"]
     input_bound = sum(len(json.dumps(row["request"], ensure_ascii=False, sort_keys=True,

--- a/code/config_test.yaml
+++ b/code/config_pro.yaml
@@ -3,72 +3,75 @@
   revision: ebb281ec70b05090aa6165b016eac8ec08e71b17
   dtype: bfloat16
 dataset:
-  repo_id: MMMU/MMMU
-  revision: 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68
+  format: mmmu_pro
+  repo_id: MMMU/MMMU_Pro
+  revision: 0d7426df4ccb3d8704a992fe6850abee7c262127
+  config_name: "standard (10 options)"
   split: test
   expected_rows_by_subject:
-    Accounting: 380
-    Agriculture: 287
-    Architecture_and_Engineering: 551
-    Art: 231
-    Art_Theory: 429
-    Basic_Medical_Science: 326
-    Biology: 345
-    Chemistry: 603
-    Clinical_Medicine: 325
-    Computer_Science: 371
-    Design: 169
-    Diagnostics_and_Laboratory_Medicine: 162
-    Economics: 267
-    Electronics: 256
-    Energy_and_Power: 432
-    Finance: 355
-    Geography: 565
-    History: 278
-    Literature: 112
-    Manage: 245
-    Marketing: 181
-    Materials: 458
-    Math: 505
-    Mechanical_Engineering: 429
-    Music: 334
-    Pharmacy: 430
-    Physics: 408
-    Psychology: 305
-    Public_Health: 509
-    Sociology: 252
-  expected_total_rows: 10500
+    "Accounting": 58
+    "Agriculture": 60
+    "Architecture_and_Engineering": 60
+    "Art": 53
+    "Art_Theory": 55
+    "Basic_Medical_Science": 52
+    "Biology": 59
+    "Chemistry": 60
+    "Clinical_Medicine": 59
+    "Computer_Science": 60
+    "Design": 60
+    "Diagnostics_and_Laboratory_Medicine": 60
+    "Economics": 59
+    "Electronics": 60
+    "Energy_and_Power": 58
+    "Finance": 60
+    "Geography": 52
+    "History": 56
+    "Literature": 52
+    "Manage": 50
+    "Marketing": 59
+    "Materials": 60
+    "Math": 60
+    "Mechanical_Engineering": 59
+    "Music": 60
+    "Pharmacy": 57
+    "Physics": 60
+    "Psychology": 60
+    "Public_Health": 58
+    "Sociology": 54
+  expected_total_rows: 1730
+  expected_ids_sha256: 782771460a58c18f550793866fc2cddc8575650f40450b57661d3d26b71b49fb
   subjects:
-    - Accounting
-    - Agriculture
-    - Architecture_and_Engineering
-    - Art
-    - Art_Theory
-    - Basic_Medical_Science
-    - Biology
-    - Chemistry
-    - Clinical_Medicine
-    - Computer_Science
-    - Design
-    - Diagnostics_and_Laboratory_Medicine
-    - Economics
-    - Electronics
-    - Energy_and_Power
-    - Finance
-    - Geography
-    - History
-    - Literature
-    - Manage
-    - Marketing
-    - Materials
-    - Math
-    - Mechanical_Engineering
-    - Music
-    - Pharmacy
-    - Physics
-    - Psychology
-    - Public_Health
-    - Sociology
+    - "Accounting"
+    - "Agriculture"
+    - "Architecture_and_Engineering"
+    - "Art"
+    - "Art_Theory"
+    - "Basic_Medical_Science"
+    - "Biology"
+    - "Chemistry"
+    - "Clinical_Medicine"
+    - "Computer_Science"
+    - "Design"
+    - "Diagnostics_and_Laboratory_Medicine"
+    - "Economics"
+    - "Electronics"
+    - "Energy_and_Power"
+    - "Finance"
+    - "Geography"
+    - "History"
+    - "Literature"
+    - "Manage"
+    - "Marketing"
+    - "Materials"
+    - "Math"
+    - "Mechanical_Engineering"
+    - "Music"
+    - "Pharmacy"
+    - "Physics"
+    - "Psychology"
+    - "Public_Health"
+    - "Sociology"
 environment:
   expected_packages:
     python: "3.12.3"

```

"""Shared, dependency-free input validation and result IO."""
import json
import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SUBJECTS = "Accounting Agriculture Architecture_and_Engineering Art Art_Theory Basic_Medical_Science Biology Chemistry Clinical_Medicine Computer_Science Design Diagnostics_and_Laboratory_Medicine Economics Electronics Energy_and_Power Finance Geography History Literature Manage Marketing Materials Math Mechanical_Engineering Music Pharmacy Physics Psychology Public_Health Sociology".split()
MODEL = "Qwen/Qwen3-VL-4B-Instruct"
MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DATA_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"

def read_rows(path, predictions=False):
    path = Path(path)
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    validate(rows, predictions)
    return rows

def validate(rows, predictions=False):
    if not rows:
        raise ValueError("Input must contain at least one row")
    seen = set()
    for row in rows:
        uid = row.get("uid")
        if not isinstance(uid, str) or not uid or uid in seen:
            raise ValueError(f"Missing or duplicate UID: {uid!r}")
        seen.add(uid)
        if row.get("subject") not in SUBJECTS:
            raise ValueError(f"Unknown subject: {row.get('subject')!r}")
        if not isinstance(row.get("question"), str):
            raise ValueError(f"Missing question: {uid}")
        if row.get("question_type") not in {"multiple-choice", "open"}:
            raise ValueError(f"Unknown question type: {uid}")
        answer = row.get("answer")
        answers = answer if isinstance(answer, list) else [answer]
        if not answers or any(not isinstance(x, str) or not x.strip() for x in answers):
            raise ValueError(f"Invalid gold answer: {uid}")
        choices = row.get("options")
        if not isinstance(choices, dict):
            raise ValueError(f"Options must be a dictionary: {uid}")
        if row['question_type'] == 'multiple-choice':
            missing_gold = any(a not in choices for a in answers)
            known_import_issue = (row.get('provenance', {}).get('source') == 'imported_qwen_jsonl'
                                  and row.get('data_issue', {}).get('type') == 'missing_gold_option_text')
            if len(choices) < 2 or (missing_gold and not known_import_issue):
                raise ValueError(f"Invalid MC gold/options: {uid}")
            if any(len(k) != 1 or k not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' or not isinstance(v, str) or not v.strip() for k, v in choices.items()):
                raise ValueError(f"Invalid option label/text: {uid}")
        if not isinstance(row.get('images'), list) or any(not isinstance(x, str) for x in row['images']):
            raise ValueError(f"Images must contain file paths: {uid}")
        if predictions:
            if not isinstance(row.get('prediction'), str):
                raise ValueError(f"Missing prediction (empty string is valid): {uid}")
            if row.get('inference_error'):
                raise ValueError(f"Inference failed for {uid}; repair before scoring")

def full_validation(rows):
    counts = Counter(r['subject'] for r in rows)
    return len(rows) == 900 and counts == Counter({s: 30 for s in SUBJECTS}) and all(r.get('split') == 'validation' for r in rows)

def input_metadata(path, rows):
    return {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'num_examples': len(rows), 'full_validation': full_validation(rows),
            'data_issue_uids': [r['uid'] for r in rows if r.get('data_issue')],
            'provenance': [json.loads(s) for s in sorted({json.dumps(r.get('provenance', {}), sort_keys=True) for r in rows})]}

def check_output(path, force=False):
    if Path(path).exists() and not force:
        raise FileExistsError(f"Output exists: {path}. Use --force to replace it explicitly.")

def write_text(path, text, force=False):
    path = Path(path)
    check_output(path, force)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def write_json(path, data, force=False):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', force)

def write_rows(path, rows, force=False):
    write_text(path, ''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows), force)

def aggregate(records):
    subjects = {}
    for subject in SUBJECTS:
        subset = [r for r in records if r['subject'] == subject]
        if subset:
            correct = sum(r['correct'] for r in subset)
            subjects[subject] = {'num_examples': len(subset), 'correct': correct, 'accuracy': correct / len(subset)}
    return {'num_examples': len(records), 'correct': sum(r['correct'] for r in records),
            'subjects': subjects, 'macro_accuracy': sum(s['accuracy'] for s in subjects.values()) / len(subjects),
            'micro_accuracy': sum(r['correct'] for r in records) / len(records)}

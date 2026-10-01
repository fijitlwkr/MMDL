#!/usr/bin/env python3
"""Shrink finished run dirs into commit-sized bundles (raw.jsonl.gz + compact item_results.jsonl)."""
import argparse, gzip, json, shutil
from pathlib import Path

KEEP = ["config_used.yaml", "config_used.diff.json", "run_metadata.json", "env.json", "env_check.json"]
KEEP_LOGS = ["03_generate.log", "04_validate_raw.log"]
KEEP_SCORING = ["summary.json", "manifest.json", "REPORT.md"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--work", type=Path, required=True); ap.add_argument("--dest", type=Path, required=True)
    a = ap.parse_args()
    for d in sorted(p for p in a.work.iterdir() if p.is_dir() and ".partial." not in p.name and p.name != a.dest.name):
        fr = d / "scoring" / "final_results.jsonl"
        if not (d / "raw.jsonl").exists():
            continue
        t = a.dest / d.name; t.mkdir(parents=True, exist_ok=True)
        with open(d / "raw.jsonl", "rb") as s, gzip.open(t / "raw.jsonl.gz", "wb") as g:
            shutil.copyfileobj(s, g)
        for f in KEEP:
            if (d / f).exists(): shutil.copy2(d / f, t / f)
        (t / "logs").mkdir(exist_ok=True)
        for f in KEEP_LOGS:
            if (d / "logs" / f).exists(): shutil.copy2(d / "logs" / f, t / "logs" / f)
        if fr.exists():
            for f in KEEP_SCORING:
                if (d / "scoring" / f).exists(): shutil.copy2(d / "scoring" / f, t / f"scoring_{f}")
            with open(fr, encoding="utf-8") as s, open(t / "item_results.jsonl", "w", encoding="utf-8") as o:
                for line in s:
                    r = json.loads(line)
                    o.write(json.dumps({k: r.get(k) for k in ("id", "subject", "question_type", "finish_reason", "output_tokens",
                                                               "final_answer", "final_correct", "final_status")}, ensure_ascii=False) + "\n")
        print("packed", t)


if __name__ == "__main__":
    main()

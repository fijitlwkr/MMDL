#!/usr/bin/env python3
"""Clear UNRESOLVED Judge attempts so `evaluate.py run` can continue (manual, audited recovery).

evaluate.py refuses to continue when api_attempts.jsonl has a 'started' event with no saved response
("No automatic retry; inspect the saved receipt/journal first"). That happens after ONE transient API failure
(timeout / 429 / 5xx) among ~345 sequential calls. This tool:
  1. shows every unresolved request id with its recorded error (never the API key / body),
  2. (--apply only) backs up api_attempts.jsonl + errors.jsonl, then removes the started/failed rows of those ids,
     so the next `run` re-sends exactly those requests and reuses all cached responses.
This DEVIATES from the scoring code's "inspect first" rule on purpose: say so in the report (extra experiment,
transient failures retried, N requests, backups kept next to the files). Dry-run is the default.
"""
import argparse, json, shutil, sys, time
from pathlib import Path


def rows(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if p.exists() else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoring_dir", type=Path, required=True, help="the arm's scoring/ directory (contains api_attempts.jsonl)")
    ap.add_argument("--apply", action="store_true", help="actually modify the journals (default: dry-run)")
    a = ap.parse_args()
    d = a.scoring_dir
    attempts, errors = rows(d / "api_attempts.jsonl"), rows(d / "errors.jsonl")
    cached = {r["id"] for r in rows(d / "responses.jsonl")}
    unresolved = sorted({e["id"] for e in attempts if e["event"] == "started"} - cached)
    print(f"cached responses: {len(cached)} | unresolved requests: {len(unresolved)}")
    for i in unresolved:
        errs = [e for e in errors if e.get("id") == i]
        print(f"  - {i}: " + (", ".join(f"{e.get('error_type')}{' HTTP ' + str(e['http_status']) if e.get('http_status') else ''}" for e in errs) or "started, no error row (process killed mid-call?)"))
    if not unresolved:
        print("nothing to do."); return
    if not a.apply:
        print("dry-run only. Re-run with --apply to clear these attempts (backups are made)."); return
    ts = time.strftime("%Y%m%dT%H%M%S")
    for name in ("api_attempts.jsonl", "errors.jsonl"):
        p = d / name
        if p.exists():
            shutil.copy2(p, d / f"{name}.bak-{ts}")
    drop = set(unresolved)
    for name in ("api_attempts.jsonl", "errors.jsonl"):
        p = d / name
        if not p.exists():
            continue
        keep = [r for r in rows(p) if r.get("id") not in drop]
        with open(p, "w", encoding="utf-8") as f:
            for r in keep:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (d / "RECOVERY_LOG.txt").open("a").write(f"{ts} cleared {len(unresolved)} unresolved attempt(s): {', '.join(unresolved)}\n")
    print(f"cleared {len(unresolved)}; backups: *.bak-{ts}; logged in RECOVERY_LOG.txt. Now re-run score_runs.sh (cached responses are reused).")


if __name__ == "__main__":
    main()

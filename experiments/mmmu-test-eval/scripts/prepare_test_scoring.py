"""Prepare frozen v2 scoring offline and report the request budget."""

import argparse
from decimal import Decimal
import json
from pathlib import Path
import runpy
import socket
import sys
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("code", "config", "raw", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    evaluator = args.code / "scoring/evaluate.py"
    sys.argv = [str(evaluator), "prepare", "--config", str(args.config), "--raw", str(args.raw),
                "--out", str(args.out)]
    offline = RuntimeError("Network is disabled for offline scoring preparation")
    with patch.object(socket, "socket", side_effect=offline), +         patch.object(socket, "create_connection", side_effect=offline):
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        except SystemExit as error:
            if error.code not in (None, 0):
                raise
    manifest = json.loads((args.out / "manifest.json").read_bytes())
    summary = json.loads((args.out / "summary.json").read_bytes())
    requests = [json.loads(line) for line in (args.out / "requests.jsonl").read_bytes().splitlines()]
    assert manifest["total"] == 10500 and len(requests) == summary["overall"]["pending"] == manifest["judge_count"]
    assert summary["response_count"] == 0
    prices = manifest["price_per_million_usd"]
    input_bound = sum(len(json.dumps(row["request"], ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")) + 128 for row in requests)
    output_bound = sum(row["request"]["max_tokens"] for row in requests)
    cost = (input_bound * Decimal(str(prices["input"])) + output_bound * Decimal(str(prices["output"]))) / 1_000_000
    result = {"raw_sha256": manifest["source_sha256"], "automatic": manifest["automatic_count"],
              "judge": len(requests), "rule_extraction_failure": sum(r["route"] == "judge_rule_failure" for r in requests),
              "conflict": sum(r["route"] == "judge_conflict" for r in requests), "api_calls": 0,
              "conservative_cost_usd": str(cost), "input_tokens_bound": input_bound, "output_tokens_bound": output_bound}
    with (args.out / "preparation_budget.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()

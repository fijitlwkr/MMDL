"""Binary R1 reward with the archived v2 automatic extraction path."""
from functools import lru_cache

from frozen_v2 import evaluate

MC_FORMATS = ("mc_letter", "mc_value")
OPEN_FORMATS = ("numeric", "short_rule", "open_audit")


@lru_cache(maxsize=1)
def parsers():
    return evaluate.load_parsers()


def extract(response, finish_reason, item):
    """Expose the ungated extraction for comparison against archived v2."""
    kind = item["format"]
    if kind == "excluded":
        return None, None, "excluded"
    if kind not in (*MC_FORMATS, *OPEN_FORMATS):
        raise ValueError(f"Unsupported format: {kind}")
    mc = kind in MC_FORMATS
    row = {"raw_text": response, "finish_reason": finish_reason,
           "question_type": "multiple-choice" if mc else "open", "gold": item["answer"],
           "options": list(item["choices"].values()) if mc else [],
           "id": "", "subject": "", "output_tokens": 0}
    parsed = evaluate.derive_item(row, parsers())
    return parsed["auto_answer"], parsed["gt"], parsed["route"]


def reward(response, finish_reason, item):
    if finish_reason == "length":
        return 0, "truncated"
    if finish_reason != "stop":
        raise ValueError(f"Unknown finish reason: {finish_reason!r}")
    answer, gold, _ = extract(response, finish_reason, item)
    if answer is None:
        return 0, "extract_fail"
    return (1, "correct") if answer == gold else (0, "wrong")

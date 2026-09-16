"""
Answer extraction and scoring logic for MMMU evaluation.
Ensures deterministic and reproducible parsing from raw model output for both
Multiple-Choice and Open-Ended questions.
"""

import math
import re
from typing import Any, List, Optional


def parse_multiple_choice(output_text: str) -> str:
    """
    Extracts the predicted multiple-choice option letter (A, B, C, D...)
    from raw model output.
    """
    if not output_text or not isinstance(output_text, str):
        return ""

    text = output_text.strip()

    # Rule 1: Output is directly a single letter or parenthesized letter, e.g. "A", "(B)", "C."
    match_exact = re.match(r"^\s*[\(\[\{]?([A-Ha-h])[\)\]\}]?[\.\:\)]?\s*$", text)
    if match_exact:
        return match_exact.group(1).upper()

    # Rule 2: LaTeX boxed answer, e.g. \boxed{A}, \boxed{(B)}, \boxed{\text{C}}
    match_boxed = re.findall(r"\\boxed\{([^}]+)\}", text)
    if match_boxed:
        for cand in reversed(match_boxed):
            cand_clean = cand.strip()
            m_let = re.search(r"\b([A-Ha-h])\b", cand_clean)
            if m_let:
                return m_let.group(1).upper()

    # Rule 3: Explicit answer conclusion patterns (prioritize end of generation)
    primary_patterns = [
        r"(?:final\s+answer|the\s+answer|correct\s+answer|correct\s+option|correct\s+choice)\s*(?:is|should\s+be|:)?\s*[\(\[\{]?([A-Ha-h])[\)\]\}]?(?:[\.\s,\n]|$)",
        r"(?:option|choice|select)\s*[\(\[\{]?([A-Ha-h])[\)\]\}]?(?:[\.\s,\n]|$)",
        r"(?:therefore|thus|hence|conclude|conclusion)\s*,?\s*(?:the\s+answer\s+is|the\s+correct\s+choice\s+is)?\s*[\(\[\{]?([A-Ha-h])[\)\]\}]?(?:[\.\s,\n]|$)",
        r"[\(\[\{]([A-Ha-h])[\)\]\}]\s*(?:is|should\s+be)\s*(?:the\s+)?(?:correct|answer)",
        r"answer\s*:\s*[\(\[\{]?([A-Ha-h])[\)\]\}]?",
    ]

    for pattern in primary_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            # Pick the last match since models usually conclude at the end
            return matches[-1].group(1).upper()

    # Rule 4: Fallback - Look for isolated parenthesized letter like (A) or [A] in the tail
    tail = text[-400:] if len(text) > 400 else text
    parenthesized = re.findall(r"[\(\[\{]([A-Ha-h])[\)\]\}]", tail)
    if parenthesized:
        return parenthesized[-1].upper()

    # Rule 5: Fallback - Search for letter followed by period/colon/parenthesis at start of a line
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in reversed(lines[-5:]):
        m_start = re.match(r"^[\(\[\{]?([A-Ha-h])[\)\]\}]?[\.\:\)]", line)
        if m_start:
            return m_start.group(1).upper()

    # Rule 6: Final Fallback - Look for any isolated single letter A-D in the last line
    if lines:
        isolated_letters = re.findall(r"\b([A-D])\b", lines[-1])
        if isolated_letters:
            return isolated_letters[-1].upper()

    return ""


def parse_open_response(output_text: str) -> str:
    """
    Extracts the core predicted value from raw model output for open-ended questions.
    """
    if not output_text or not isinstance(output_text, str):
        return ""

    text = output_text.strip()

    # Rule 1: Boxed answer
    match_boxed = re.findall(r"\\boxed\{([^}]+)\}", text)
    if match_boxed:
        cand = match_boxed[-1].strip()
        cand = re.sub(r"\\text\{([^}]+)\}", r"\1", cand)
        return cand.strip()

    # Rule 2: Explicit answer prefix
    patterns = [
        r"(?:final\s+answer|the\s+answer|correct\s+answer)\s*(?:is|should\s+be|:)?\s*([^\.\n]+)",
        r"(?:therefore|thus|hence)\s*,?\s*(?:the\s+answer\s+is)?\s*([^\.\n]+)",
    ]
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            cand = matches[-1].group(1).strip()
            if cand:
                return cand

    # Rule 3: Last non-empty line
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if lines:
        return lines[-1]

    return ""


def parse_answer(
    output_text: str,
    question_type: str = "multiple-choice",
    options: Optional[List[Any]] = None,
) -> str:
    """
    Extracts predicted answer from model output based on question type.
    Maintains full backward compatibility.
    """
    # If options exist, treat as multiple-choice
    if options and len(options) > 0:
        return parse_multiple_choice(output_text)

    if question_type in ["multiple-choice", ""]:
        # Check if output is a multiple choice letter
        mc_pred = parse_multiple_choice(output_text)
        if mc_pred:
            return mc_pred
        return parse_open_response(output_text)

    return parse_open_response(output_text)


def _to_float(val: Any) -> Optional[float]:
    """Helper to convert string/fraction to float for numerical comparison."""
    if val is None:
        return None
    s = str(val).strip()
    s = re.sub(r"[\$,%]", "", s)
    s = s.rstrip(".")
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                num = float(parts[0].strip())
                den = float(parts[1].strip())
                if den != 0:
                    return num / den
            except ValueError:
                pass
    try:
        return float(s)
    except ValueError:
        return None


def is_correct(
    prediction: str,
    ground_truth: str,
    question_type: str = "multiple-choice",
) -> bool:
    """
    Compares predicted answer with ground truth.
    Supports both multiple-choice and open-ended questions.
    """
    if not prediction or not ground_truth:
        return False

    clean_gt = str(ground_truth).strip()
    clean_pred = str(prediction).strip()

    # 1. Multiple-choice evaluation
    if len(clean_gt) == 1 and clean_gt.upper() in "ABCDEFGH":
        if len(clean_pred) > 1 and clean_pred[0] in "ABCDEFGH" and clean_pred[1] in [".", ":", " ", ")"]:
            clean_pred = clean_pred[0]
        return clean_pred.upper() == clean_gt.upper()

    if len(clean_gt) > 1 and clean_gt[0] in "ABCDEFGH" and clean_gt[1] in [".", ":", " ", ")"]:
        clean_gt_letter = clean_gt[0].upper()
        if clean_pred.upper() == clean_gt_letter:
            return True

    # 2. Numerical evaluation (if both convert to float)
    f_gt = _to_float(clean_gt)
    f_pred = _to_float(clean_pred)
    if f_gt is not None and f_pred is not None:
        return math.isclose(f_gt, f_pred, rel_tol=1e-2, abs_tol=1e-3)

    # 3. String equivalence (case-insensitive, normalized punctuation)
    norm_gt = re.sub(r"[^a-zA-Z0-9]", "", clean_gt).lower()
    norm_pred = re.sub(r"[^a-zA-Z0-9]", "", clean_pred).lower()
    if norm_gt and norm_gt == norm_pred:
        return True

    if norm_gt and len(norm_gt) > 3 and norm_gt in norm_pred:
        return True

    return False

"""
Answer extraction and scoring logic for MMMU evaluation.
Ensures deterministic and reproducible parsing from raw model output to option letters (A, B, C, D...).
"""

import re
from typing import Optional


def parse_answer(output_text: str) -> str:
    """
    Extracts the predicted multiple-choice option letter from raw model output.
    Returns uppercase option letter (e.g. 'A', 'B', 'C', 'D') or empty string '' if parsing fails.
    """
    if not output_text or not isinstance(output_text, str):
        return ""

    text = output_text.strip()

    # Rule 1: Output is directly a single letter (e.g., "A", "b", " C ")
    match_exact = re.match(r"^([A-Ha-h])[\.\:\)]?$", text)
    if match_exact:
        return match_exact.group(1).upper()

    # Rule 2: LaTeX boxed answer, e.g. \boxed{A}
    match_boxed = re.search(r"\\boxed\{([A-Ha-h])\}", text)
    if match_boxed:
        return match_boxed.group(1).upper()

    # Rule 3: Common explicit answer patterns
    primary_patterns = [
        r"(?:the\s+)?(?:correct\s+)?answer\s+(?:is|should\s+be)\s*[:\s]*\(?([A-Ha-h])\)?",
        r"(?:correct\s+)?option\s+(?:is|should\s+be)\s*[:\s]*\(?([A-Ha-h])\)?",
        r"choice\s+[:\s]*\(?([A-Ha-h])\)?",
        r"answer\s*:\s*\(?([A-Ha-h])\)?",
        r"\(([A-Ha-h])\)\s+is\s+(?:the\s+)?correct",
        r"therefore,?\s*(?:the\s+answer\s+is\s*)?\(?([A-Ha-h])\)?",
        r"thus,?\s*(?:the\s+answer\s+is\s*)?\(?([A-Ha-h])\)?",
        r"conclusion\s*[:\s]*\(?([A-Ha-h])\)?",
    ]

    for pattern in primary_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    # Rule 4: Fallback - Look for isolated parenthesized letter like (A) or [A]
    parenthesized = re.findall(r"[\(\[\{]([A-Ha-h])[\)\]\}]", text)
    if parenthesized:
        return parenthesized[-1].upper()

    # Rule 5: Fallback - Search for standard letter followed by period/colon at the end or start
    match_end = re.search(r"\b([A-Ha-h])[\.\:\)]\s*$", text)
    if match_end:
        return match_end.group(1).upper()

    match_start = re.search(r"^\s*([A-Ha-h])[\.\:\)]", text)
    if match_start:
        return match_start.group(1).upper()

    # Rule 6: Final Fallback - Look for any isolated single letter A-D in the last line
    last_line = text.split("\n")[-1]
    isolated_letters = re.findall(r"\b([A-D])\b", last_line)
    if isolated_letters:
        return isolated_letters[-1].upper()

    return ""


def is_correct(prediction: str, ground_truth: str) -> bool:
    """
    Compares predicted letter with ground truth answer.
    """
    if not prediction or not ground_truth:
        return False
    
    clean_gt = str(ground_truth).strip().upper()
    clean_pred = str(prediction).strip().upper()
    
    # In some MMMU samples, GT might be "A" or "A. xxx"
    if len(clean_gt) > 1 and clean_gt[0] in "ABCDEFGH" and clean_gt[1] in [".", ":", " ", ")"]:
        clean_gt = clean_gt[0]
        
    return clean_pred == clean_gt

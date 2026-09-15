"""
Prompt formatting utilities for MMMU benchmark evaluation on Qwen3-VL.
"""

import ast
import json
from typing import Any, Dict, List, Optional
from PIL import Image


def parse_options(options_data: Any) -> List[str]:
    """
    Parse the options field from an MMMU sample.
    MMMU options can be a list of strings, or a stringified list (e.g. "['opt1', 'opt2']").
    """
    if isinstance(options_data, list):
        return options_data
    if isinstance(options_data, str):
        try:
            parsed = ast.literal_eval(options_data)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        try:
            parsed = json.loads(options_data)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        # Fallback: single string or custom format
        return [options_data]
    return []


def format_options_text(options_list: List[str]) -> str:
    """
    Format a list of options into standard lettered format:
    A. option1
    B. option2
    ...
    """
    letters = ["A", "B", "C", "D", "E", "F", "G", "H"]
    formatted_lines = []
    
    for idx, opt in enumerate(options_list):
        opt_str = str(opt).strip()
        letter = letters[idx] if idx < len(letters) else f"({idx+1})"
        
        # If the option text already starts with the letter (e.g. "A. xxx" or "A: xxx")
        if len(opt_str) >= 2 and opt_str[0].upper() == letter and opt_str[1] in [".", ":", " ", ")"]:
            formatted_lines.append(opt_str)
        else:
            formatted_lines.append(f"{letter}. {opt_str}")
            
    return "\n".join(formatted_lines)


def format_mmmu_prompt(question: str, options: Any) -> str:
    """
    Construct the final prompt text sent to Qwen3-VL.
    Matches standard MMMU evaluation practice for multiple choice questions.
    """
    options_list = parse_options(options)
    options_text = format_options_text(options_list)
    
    if options_text:
        prompt = (
            f"{question.strip()}\n"
            f"{options_text}\n\n"
            f"Answer with the option's letter from the given choices directly."
        )
    else:
        prompt = (
            f"{question.strip()}\n\n"
            f"Answer the question directly."
        )
    return prompt


def extract_images_from_sample(sample: Dict[str, Any]) -> List[Image.Image]:
    """
    MMMU samples can contain up to 7 images: image_1, image_2, ..., image_7.
    Returns a list of valid PIL Images.
    """
    images = []
    for i in range(1, 8):
        key = f"image_{i}"
        if key in sample and sample[key] is not None:
            img = sample[key]
            if isinstance(img, Image.Image):
                # Ensure RGB
                if img.mode != "RGB":
                    img = img.convert("RGB")
                images.append(img)
    return images

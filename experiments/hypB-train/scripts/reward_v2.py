"""Conservative terminal multiple-choice fallback for the original R1 reward."""

import re
import unicodedata

import reward as legacy


TAIL_CHARS = 512
NOTE_CHARS = 210
ANSWER = re.compile(
    r"^(?:(?:(?:final|correct)\s+)?answer|correct\s+(?:choice|option)|"
    r"(?:最终|正确)?答案|정답)\s*(?::\s*|\s+is\s+|$)"
    r"|^(?:(?:so|thus|therefore)[, ]+)?(?:the\s+)?"
    r"(?:correct\s+)?(?:answer|choice)\s+is\s*:?\s*",
    re.IGNORECASE,
)
LABEL = re.compile(r"^(?:\(([A-Za-z])\)|([A-Za-z])(?:[.):](?=\s|$)|$))\s*(.*)$")
MULTIPLE = re.compile(
    r"^\(?[A-Za-z]\)?\s*(?:(?:and|or|및)\s+|[/,;&、]\s*)"
    r"\(?[A-Za-z]\)?(?=\s|[.,);/&、]|$)",
    re.IGNORECASE,
)
NOTE = re.compile(r"^\*?\((?:Note:|With the understanding\b)|^This\s", re.IGNORECASE)
BOX_CUE = re.compile(r"^So(?:\s*[,—–-])?\s+", re.IGNORECASE)
INVALID = object()


def presentation(text):
    text = unicodedata.normalize("NFC", text).translate(str.maketrans("：．（）", ":.()"))
    return " ".join(text.split())


def unwrap(text):
    text = text.strip().removesuffix("✅").strip()
    for left, right in (("**", "**"), ("$$", "$$"), ("$", "$"), (r"\(", r"\)")):
        if len(text) > len(left) + len(right) and text.startswith(left) and text.endswith(right):
            text = text[len(left):-len(right)].strip()
    return text


def command_group(text, command):
    """Return the first balanced argument and following text of a LaTeX command."""
    prefix = command + "{"
    if not text.startswith(prefix):
        return None
    depth = 1
    for index in range(len(prefix), len(text)):
        if text[index - 1] == "\\":
            continue
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[len(prefix):index], text[index + 1:]
    return None


def resolve(payload, choices):
    if payload.endswith("**."):
        payload = payload[:-1]
    payload = unwrap(payload)
    box = command_group(payload, r"\boxed")
    if box and not box[1].strip(" .$"):
        payload = box[0].strip()
    inner = command_group(payload, r"\text")
    if inner:
        payload = (inner[0] + inner[1]).strip()
    payload = unwrap(payload)
    if MULTIPLE.match(payload):
        return INVALID
    label = LABEL.fullmatch(payload)
    if label:
        letter = (label[1] or label[2]).upper()
        if letter not in choices or (LABEL.fullmatch(label[3]) and label[3].upper() != letter):
            return INVALID
        return letter
    exact = [letter for letter, content in choices.items() if payload == unwrap(presentation(content))]
    if len(exact) > 1:
        return INVALID
    return exact[0] if exact else None


def standalone(line):
    unboxed = BOX_CUE.sub("", unwrap(line))
    if unboxed.startswith(r"\boxed{"):
        return unboxed
    if line.startswith("**") and line.removesuffix("✅").strip().endswith("**"):
        return line
    return None


def fallback_extract(response, choices):
    response = response.rstrip()
    if len(response) > TAIL_CHARS:
        start = len(response) - TAIL_CHARS
        response = response[start:] if response[start - 1] == "\n" else response[start:].partition("\n")[2]
    lines = []
    for raw in response.splitlines():
        line = re.sub(r"^(?:#{1,6}\s+|>\s*|✅\s*)+", "", presentation(raw))
        if line and not re.fullmatch(r"(?:[-*_]{3,}|\$\$|\\[\[\]])", line):
            lines.append(line)
    if not lines:
        return None
    end = len(lines) - 1
    if end and len(lines[end]) <= NOTE_CHARS and NOTE.match(lines[end]):
        end -= 1

    candidates = {}
    for index, line in enumerate(lines[:end + 1]):
        plain = unwrap(line)
        declaration = ANSWER.match(plain)
        if declaration:
            value = plain[declaration.end():].strip()
            if value:
                candidates[index] = resolve(value, choices)
            elif index < end and not ANSWER.match(unwrap(lines[index + 1])):
                candidates[index + 1] = resolve(lines[index + 1], choices)

    # A standalone choice must be part of the terminal answer block.
    for index in range(end, -1, -1):
        if index in candidates:
            continue
        value = standalone(lines[index])
        if value is None:
            break
        candidates[index] = resolve(value, choices)

    resolved = set(candidates.values()) - {None}
    terminal = candidates.get(end)
    return terminal if terminal in choices and resolved == {terminal} else None


def reward(response, finish_reason, item):
    original = legacy.reward(response, finish_reason, item)
    if original[1] != "extract_fail" or item["format"] not in legacy.MC_FORMATS:
        return original
    letter = fallback_extract(response, item["choices"])
    if letter is None:
        return original
    if letter == item["answer"]:
        return 1, "fallback_correct"
    return 0, "fallback_wrong"

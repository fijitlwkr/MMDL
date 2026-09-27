#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MMMU 프롬프트 빌더 — 템플릿 3종과 이미지/텍스트 교차 배치(FACTS 11).

## 템플릿 3종

MMMU가 제공하는 프롬프트는 LLaVA 시절에 만들어진 범용 프롬프트 하나뿐이고,
교수님도 그것이 Qwen3-VL에 맞지 않을 수 있다고 명시했습니다(FACTS 11). 템플릿에 따라
MMMU 점수가 몇 점씩 움직이므로, 보고서에는 **어떤 템플릿을 썼는지 반드시 적어야 합니다.**

- `official` : MMMU 공식 프롬프트(mmmu/configs/llava1.5.yaml)를 FACTS 11에 인용된 형태
  그대로 쓴 것입니다. 선택지는 "(A) text" 형식입니다.
- `llava`    : 같은 문장이지만 구분자가 개행 한 칸인 LLaVA-1.5 원형입니다.
  공백 배치가 점수에 주는 영향을 분리해 보려면 이쪽과 `official`을 비교하면 됩니다.
- `anchored` : 공식 프레이밍을 유지하면서 파싱 앵커("Answer: X")를 덧붙인 것입니다.
  기본 권장값입니다. 공식 파서는 '**C**', 'C) $8', 'c' 같은 답을 파싱하지 못하고
  `random.choice`로 찍어 버리므로(FACTS 4c), 앵커를 강제하면 "모델은 맞혔는데 파서가
  놓쳐서 틀린" 손실을 줄일 수 있습니다. 그래서 `anchored`와 `official`의 점수 차이는
  그 자체로 좋은 분석 재료입니다(FACTS 11).

## 선택지 문자

선택지 문자는 **반드시 `len(options)`에서 유도**합니다. 847개 객관식 중 241개는 선택지가
4개가 아니며(2, 3, 5, 6, 7, 9개) 정답 문자는 'I'까지 나옵니다(FACTS 4).
`['A','B','C','D']`를 하드코딩하면 그 241문항이 조용히 망가집니다.

## 메시지 구조

`build_messages`는 프롬프트 문자열을 `<image N>` 마커에서 잘라, 이미지 블록과 텍스트
블록을 **원문 배치 그대로** 교차시킵니다. 이것이 `processor.apply_chat_template`과
vLLM의 `llm.chat()`이 함께 먹는 구조입니다. 마커를 무시하고 이미지를 앞에 몰아 넣으면
"아래 <image 2>를 보라" 같은 지시문이 깨집니다.
시스템 메시지는 넣지 않습니다. Qwen3-VL은 Qwen2.5-VL과 달리 기본 시스템 프롬프트가
없으며, 채팅 템플릿 오버헤드는 10~12토큰입니다(FACTS 3).

단독 실행 시 자체 점검을 수행합니다: `python src/mmmu_prompt.py`
"""

from __future__ import annotations

import re
import string
import sys
from typing import Any

# mmmu_data는 최상위에서 표준 라이브러리만 임포트하므로(datasets/PIL은 지연 임포트)
# 이 임포트는 가볍습니다. 두 가지 임포트 방식(src를 sys.path에 넣는 방식 /
# python -m src.mmmu_prompt)을 모두 지원하기 위해 이중 임포트를 씁니다.
try:  # pragma: no cover
    from mmmu_data import IMAGE_MARKER_RE, MMMUSample
except ImportError:  # pragma: no cover
    from src.mmmu_data import IMAGE_MARKER_RE, MMMUSample

__all__ = [
    "PROMPT_TEMPLATES",
    "MC_INSTRUCTIONS",
    "OPEN_INSTRUCTIONS",
    "OPTION_STYLE_BY_TEMPLATE",
    "index_letters",
    "format_options",
    "build_prompt",
    "build_messages",
]

# --------------------------------------------------------------------------------------
# 템플릿 정의
# --------------------------------------------------------------------------------------

#: 템플릿 본문 레이아웃. 값에 쓰이는 플레이스홀더는 {question}, {options}, {instruction} 입니다.
#: 'official'은 FACTS 11에 인용된 공식 문자열
#: "{question}\n\n{options}\n\nAnswer with the option's letter from the given choices directly."
#: 와 정확히 같은 배치입니다(지시문만 아래 표로 분리).
PROMPT_TEMPLATES: dict[str, str] = {
    "official": "{question}\n\n{options}\n\n{instruction}",
    "llava": "{question}\n{options}\n{instruction}",
    "anchored": "{question}\n\n{options}\n\n{instruction}",
}

#: 객관식 지시문. 공식 문장은 영어 원문이므로 그대로 인용합니다.
#: anchored의 앵커 문장은 FACTS 4c의 파서 실패 사례(마크다운 굵게, 'C)' 형태)를
#: 명시적으로 금지하는 방향으로 작성했습니다.
MC_INSTRUCTIONS: dict[str, str] = {
    "official": "Answer with the option's letter from the given choices directly.",
    "llava": "Answer with the option's letter from the given choices directly.",
    "anchored": (
        "Answer with the option's letter from the given choices directly.\n"
        'Write your final answer on the last line in exactly this form: "Answer: X", '
        "where X is one of {letters}. "
        "Do not add bold, parentheses, quotation marks, or any other formatting around the letter."
    ),
}

#: 개방형(단답형) 지시문. 공식 mmmu/configs/llava1.5.yaml의 short_ans_example_format 문장입니다.
OPEN_INSTRUCTIONS: dict[str, str] = {
    "official": "Answer the question using a single word or phrase.",
    "llava": "Answer the question using a single word or phrase.",
    "anchored": (
        "Answer the question using a single word or phrase.\n"
        'Write your final answer on the last line in exactly this form: "Answer: <your answer>".'
    ),
}

#: 템플릿별 선택지 표기 방식. FACTS 11의 공식 형식이 "(A) text"이므로 세 템플릿 모두 paren입니다.
#: 'dot' 스타일은 템플릿 비교 실험용으로 format_options가 지원합니다.
OPTION_STYLE_BY_TEMPLATE: dict[str, str] = {
    "official": "paren",
    "llava": "paren",
    "anchored": "paren",
}

#: format_options가 지원하는 표기 방식.
OPTION_STYLES: tuple[str, ...] = ("paren", "dot")

#: validation 정답 문자는 A..I까지만 존재합니다(FACTS 4). 그 이상은 데이터가 바뀐 신호입니다.
MAX_VERIFIED_OPTIONS: int = 9

# 템플릿 표들의 키가 어긋나면 조용히 잘못된 프롬프트가 나가므로 임포트 시점에 검증합니다.
for _table_name, _table in (
    ("MC_INSTRUCTIONS", MC_INSTRUCTIONS),
    ("OPEN_INSTRUCTIONS", OPEN_INSTRUCTIONS),
    ("OPTION_STYLE_BY_TEMPLATE", OPTION_STYLE_BY_TEMPLATE),
):
    if set(_table) != set(PROMPT_TEMPLATES):
        raise RuntimeError(
            f"{_table_name}의 키가 PROMPT_TEMPLATES와 다릅니다: "
            f"{sorted(_table)} != {sorted(PROMPT_TEMPLATES)}"
        )

_warned_once: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _warned_once:
        return
    _warned_once.add(key)
    print(f"[mmmu_prompt] 경고: {message}", file=sys.stderr, flush=True)


def _attr(sample: Any, name: str, default: Any = None) -> Any:
    """MMMUSample(객체) 과 dict 를 모두 받아들입니다(드라이런 도구 편의)."""
    if isinstance(sample, dict):
        return sample.get(name, default)
    return getattr(sample, name, default)


# --------------------------------------------------------------------------------------
# 선택지 문자와 선택지 블록
# --------------------------------------------------------------------------------------


def index_letters(n: int) -> list[str]:
    """선택지 개수 n에서 ['A', 'B', ...]를 만듭니다. A~D 하드코딩 금지(FACTS 4)."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"선택지 개수는 int여야 합니다: {n!r}")
    if n < 1:
        raise ValueError(f"선택지 개수가 {n}입니다. 객관식이라면 최소 2개여야 합니다.")
    if n > len(string.ascii_uppercase):
        raise ValueError(f"선택지 {n}개는 A~Z로 표기할 수 없습니다.")
    if n > MAX_VERIFIED_OPTIONS:
        # FACTS 4에서 검증된 최대는 9개(정답 문자 'I')입니다. 그보다 많으면 데이터셋이
        # 바뀐 것이므로 크게 경고하되, 평가 중 전체 실행이 죽지는 않게 계속 진행합니다.
        _warn_once(
            f"letters:{n}",
            f"선택지가 {n}개인 문항이 있습니다. FACTS 4에서 검증된 최대는 "
            f"{MAX_VERIFIED_OPTIONS}개(A~I)이므로 데이터셋 리비전을 확인하십시오.",
        )
    return list(string.ascii_uppercase[:n])


def format_options(options: list[str], style: str) -> str:
    """선택지 블록을 만듭니다. style='paren' -> "(A) text", 'dot' -> "A. text".

    줄바꿈으로 이어 붙이며, 선택지 **본문은 절대 수정하지 않습니다**. 공식 파서의
    선택지 텍스트 매칭 패스가 원문 그대로의 문자열을 비교하기 때문입니다(FACTS 4c).
    """
    if style not in OPTION_STYLES:
        raise ValueError(f"알 수 없는 선택지 표기 방식 {style!r}. 가능한 값: {OPTION_STYLES}")
    if not options:
        return ""  # 개방형 문항: 선택지 블록 없음
    letters = index_letters(len(options))
    if style == "paren":
        # 공식 construct_prompt는 f"({chr}) {option}\n"로 줄마다 개행을 붙입니다.
        # 여기서는 마지막 줄의 개행만 빼고 동일한 블록을 만들고, 블록 사이 구분자는
        # 템플릿이 담당합니다(FACTS 11의 인용 형태와 일치).
        return "\n".join(f"({letter}) {text}" for letter, text in zip(letters, options))
    return "\n".join(f"{letter}. {text}" for letter, text in zip(letters, options))


def _letters_phrase(letters: list[str]) -> str:
    """앵커 지시문에 넣을 "A, B, C, D" 문구."""
    return ", ".join(letters)


def _layout(template: str, has_options: bool) -> str:
    """개방형 문항에서는 템플릿의 {options} 자리와 뒤따르는 구분자를 함께 제거합니다.

    **템플릿 문자열만** 손대므로 질문 본문의 개행은 어떤 경우에도 변형되지 않습니다.
    (포맷한 결과에서 빈 줄을 정규식으로 지우는 방식은, 표가 들어간 질문의 빈 줄까지
    망가뜨리기 때문에 쓰지 않습니다.)
    """
    layout = PROMPT_TEMPLATES[template]
    if has_options:
        return layout
    layout = re.sub(r"\{options\}\n+", "", layout)
    if "{options}" in layout:  # {options}가 맨 끝에 오는 템플릿을 위한 대비
        layout = re.sub(r"\n+\{options\}", "", layout)
    if "{options}" in layout:
        layout = layout.replace("{options}", "")
    return layout


# --------------------------------------------------------------------------------------
# 프롬프트 / 메시지 생성
# --------------------------------------------------------------------------------------


def build_prompt(sample: Any, template: str) -> tuple[str, list[str]]:
    """(프롬프트 텍스트, 선택지 문자 리스트)를 돌려줍니다.

    반환되는 프롬프트 텍스트에는 `<image N>` 마커가 **그대로 남아 있습니다.** 마커 위치가
    곧 이미지가 들어갈 자리이고, 그 교차 배치는 build_messages가 처리합니다.
    개방형 문항의 선택지 문자 리스트는 빈 리스트입니다.
    """
    if template not in PROMPT_TEMPLATES:
        raise ValueError(
            f"알 수 없는 템플릿 {template!r}. 가능한 값: {sorted(PROMPT_TEMPLATES)}"
        )

    sample_id = _attr(sample, "id", "?")
    question = _attr(sample, "question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"[{sample_id}] question이 비어 있습니다.")
    # 앞뒤 공백만 제거합니다(내용은 그대로). 템플릿 구분자를 정확히 유지하기 위한 조치입니다.
    question = question.strip()

    options = list(_attr(sample, "options", []) or [])
    question_type = _attr(sample, "question_type")

    # 공식 construct_prompt와 동일하게 question_type만으로 분기합니다.
    if question_type == "multiple-choice":
        if len(options) < 2:
            raise ValueError(
                f"[{sample_id}] multiple-choice인데 선택지가 {len(options)}개입니다."
            )
        letters = index_letters(len(options))
        options_block = format_options(options, OPTION_STYLE_BY_TEMPLATE[template])
        instruction = MC_INSTRUCTIONS[template].format(letters=_letters_phrase(letters))
    elif question_type == "open":
        letters = []
        options_block = ""
        instruction = OPEN_INSTRUCTIONS[template]
        if options:
            _warn_once(
                "open_with_options",
                f"[{sample_id}] open 문항에 선택지가 있지만 프롬프트에 넣지 않습니다"
                "(공식 동작과 동일).",
            )
    else:
        raise ValueError(
            f"[{sample_id}] question_type이 {question_type!r}입니다. "
            "'multiple-choice' 또는 'open'이어야 합니다(FACTS 4)."
        )

    layout = _layout(template, bool(options_block))
    prompt_text = layout.format(
        question=question, options=options_block, instruction=instruction
    )
    return prompt_text, letters


def build_messages(sample: Any, prompt_text: str) -> list[dict]:
    """프롬프트 텍스트를 이미지/텍스트 블록으로 교차 배치한 user 메시지 하나를 돌려줍니다.

    반환 형식:
        [{"role": "user", "content": [{"type": "image", "image": <PIL>},
                                      {"type": "text",  "text": "..."}, ...]}]

    마커 N은 `sample.image_indices`에서 N이 있는 위치의 이미지, 즉 원본 컬럼 image_N에
    대응합니다(FACTS 4a). 같은 마커가 여러 번 나오면 **같은 이미지 객체**가 여러 번
    들어갑니다(validation_Math_19의 [1, 2, 1, 1, 2] 사례).

    다음 두 경우에는 조용히 넘어가지 않고 예외를 냅니다.
      1) 마커에 대응하는 이미지가 없는 경우 — 이미지 한 장이 빠진 채 추론되면 오답의
         원인을 추적할 수 없습니다.
      2) 표본이 들고 있는 이미지가 프롬프트 안에서 한 번도 참조되지 않은 경우 —
         멀티이미지 문항 43개가 조용히 단일 이미지로 추론되는 사고를 막는 안전장치입니다.
    """
    sample_id = _attr(sample, "id", "?")
    images = list(_attr(sample, "images", []) or [])
    indices = [int(n) for n in (_attr(sample, "image_indices", []) or [])]

    if len(images) != len(indices):
        raise ValueError(
            f"[{sample_id}] images({len(images)}장)와 image_indices({len(indices)}개)의 "
            "길이가 다릅니다. 로더가 손상되었습니다."
        )
    position_of: dict[int, int] = {}
    for position, n in enumerate(indices):
        if n in position_of:
            raise ValueError(f"[{sample_id}] image_indices에 중복된 인덱스 {n}이 있습니다.")
        position_of[n] = position

    content: list[dict] = []
    cursor = 0
    used: set[int] = set()
    for match in IMAGE_MARKER_RE.finditer(prompt_text):
        chunk = prompt_text[cursor : match.start()]
        if chunk:  # 빈 문자열 블록은 넣지 않습니다(공백만 있는 블록은 배치 정보이므로 보존).
            content.append({"type": "text", "text": chunk})
        n = int(match.group(1))
        if n not in position_of:
            raise ValueError(
                f"[{sample_id}] 프롬프트의 `<image {n}>`에 대응하는 이미지가 없습니다. "
                f"보유 인덱스: {indices}. 마커를 조용히 버리지 않고 중단합니다(FACTS 4a)."
            )
        content.append({"type": "image", "image": images[position_of[n]]})
        used.add(n)
        cursor = match.end()

    tail = prompt_text[cursor:]
    if tail:
        content.append({"type": "text", "text": tail})

    unused = sorted(set(indices) - used)
    if unused:
        raise ValueError(
            f"[{sample_id}] 이미지 {unused}이(가) 프롬프트 안에서 참조되지 않았습니다. "
            "마커가 options에만 있는 문항에서 선택지 블록이 빠졌을 때 생기는 증상입니다"
            "(FACTS 4a의 13행). 이미지를 조용히 버리지 않고 중단합니다."
        )
    if not content:
        raise ValueError(f"[{sample_id}] 생성된 메시지 내용이 비어 있습니다.")

    # 시스템 메시지 없음: Qwen3-VL Instruct는 기본 시스템 프롬프트가 없습니다(FACTS 3).
    return [{"role": "user", "content": content}]


# --------------------------------------------------------------------------------------
# 자체 점검 (python src/mmmu_prompt.py)
# --------------------------------------------------------------------------------------


class _DummyImage:
    """자체 점검용 가짜 이미지. pillow 없이도 구조를 확인할 수 있게 합니다."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:
        return f"<IMG {self.label}>"


def _demo_sample(
    sample_id: str,
    question: str,
    options: list[str],
    question_type: str,
    indices: list[int],
) -> MMMUSample:
    subject = sample_id.split("_")[1]
    return MMMUSample(
        id=sample_id,
        subject=subject,
        category="Science",
        question=question,
        options=options,
        options_raw=repr(options),
        answer="B",
        question_type=question_type,
        images=[_DummyImage(f"image_{n}") for n in indices],
        image_indices=list(indices),
        subfield="demo",
        topic_difficulty="Medium",
    )


def _describe(messages: list[dict]) -> str:
    parts = []
    for block in messages[0]["content"]:
        if block["type"] == "image":
            parts.append(f"[IMG {block['image'].label}]")
        else:
            parts.append(f"[TXT {block['text']!r}]")
    return "\n      ".join(parts)


def _self_check() -> int:
    failures = 0

    def check(label: str, got: Any, want: Any) -> None:
        nonlocal failures
        if got == want:
            print(f"PASS {label}")
        else:
            failures += 1
            print(f"FAIL {label}\n     측정={got!r}\n     기대={want!r}")

    # validation_Math_19 형태: 마커 순서 [1, 2, 1, 1, 2], 이미지는 2장
    math19 = _demo_sample(
        "validation_Math_19",
        "Compare <image 1> with <image 2>, then check <image 1> and <image 1> against <image 2>.",
        ["yes", "no", "maybe"],
        "multiple-choice",
        [1, 2],
    )
    # validation_Biology_24 형태: 마커가 선택지에만 있음
    bio24 = _demo_sample(
        "validation_Biology_24",
        "Which structure is shown?",
        ["<image 1>", "<image 2>", "<image 3>"],
        "multiple-choice",
        [1, 2, 3],
    )
    open_sample = _demo_sample(
        "validation_Math_15",
        "Compute the ratio in <image 1>.",
        [],
        "open",
        [1],
    )

    print("=== mmmu_prompt 자체 점검 ===\n")
    print("--- 템플릿 3종 출력(객관식, 선택지 3개) ---")
    for name in ("official", "llava", "anchored"):
        text, letters = build_prompt(math19, name)
        print(f"\n[{name}] letters={letters}")
        print(text)
    print("\n--- 개방형(anchored) ---")
    text_open, letters_open = build_prompt(open_sample, "anchored")
    print(text_open)

    print("\n--- 메시지 교차 배치 ---")
    for sample in (math19, bio24, open_sample):
        prompt_text, _ = build_prompt(sample, "anchored")
        messages = build_messages(sample, prompt_text)
        print(f"\n  {sample.id}:\n      {_describe(messages)}")

    print("\n--- 검증 항목 ---")
    # 선택지 문자
    check("index_letters(4)", index_letters(4), ["A", "B", "C", "D"])
    check("index_letters(9) 는 I 까지", index_letters(9), list("ABCDEFGHI"))
    check("index_letters(2)", index_letters(2), ["A", "B"])
    for bad in (0, -1, 27):
        try:
            index_letters(bad)
            check(f"index_letters({bad}) 거부", False, True)
        except ValueError:
            check(f"index_letters({bad}) 거부", True, True)
    try:
        index_letters(4.0)  # type: ignore[arg-type]
        check("index_letters(float) 거부", False, True)
    except TypeError:
        check("index_letters(float) 거부", True, True)

    # 선택지 블록
    check("format_options paren", format_options(["x", "y"], "paren"), "(A) x\n(B) y")
    check("format_options dot", format_options(["x", "y"], "dot"), "A. x\nB. y")
    check("format_options 개방형", format_options([], "paren"), "")
    try:
        format_options(["x"], "bullet")
        check("알 수 없는 style 거부", False, True)
    except ValueError:
        check("알 수 없는 style 거부", True, True)

    # 템플릿 키와 공식 문구
    check("PROMPT_TEMPLATES 키", sorted(PROMPT_TEMPLATES), ["anchored", "llava", "official"])
    official_text, _ = build_prompt(math19, "official")
    check(
        "official 은 FACTS 11 인용 형태와 일치",
        official_text,
        "Compare <image 1> with <image 2>, then check <image 1> and <image 1> against "
        "<image 2>.\n\n(A) yes\n(B) no\n(C) maybe\n\n"
        "Answer with the option's letter from the given choices directly.",
    )
    llava_text, _ = build_prompt(math19, "llava")
    check("llava 는 개행 한 칸", "maybe\nAnswer with" in llava_text, True)
    anchored_text, _ = build_prompt(math19, "anchored")
    check("anchored 에 앵커 포함", '"Answer: X"' in anchored_text, True)
    check("anchored 에 선택지 문자 나열", "one of A, B, C" in anchored_text, True)

    # 개방형: 빈 줄이 남지 않아야 합니다.
    check("개방형에 빈 줄 없음", "\n\n\n" not in text_open, True)
    check("개방형에 선택지 블록 없음", "(A)" not in text_open, True)
    check("개방형 letters 는 빈 리스트", letters_open, [])
    check(
        "개방형 구조",
        text_open,
        "Compute the ratio in <image 1>.\n\n"
        "Answer the question using a single word or phrase.\n"
        'Write your final answer on the last line in exactly this form: "Answer: <your answer>".',
    )

    # 교차 배치
    prompt_text, _ = build_prompt(math19, "anchored")
    blocks = build_messages(math19, prompt_text)[0]["content"]
    check("메시지는 user 하나", len(build_messages(math19, prompt_text)), 1)
    check("role", build_messages(math19, prompt_text)[0]["role"], "user")
    image_blocks = [b for b in blocks if b["type"] == "image"]
    check("마커 5개 -> 이미지 블록 5개", len(image_blocks), 5)
    check(
        "마커 N -> image_N 매핑",
        [b["image"].label for b in image_blocks],
        ["image_1", "image_2", "image_1", "image_1", "image_2"],
    )
    check(
        "반복 참조는 동일 객체",
        image_blocks[0]["image"] is image_blocks[2]["image"],
        True,
    )
    check("빈 텍스트 블록 없음", all(b["text"] for b in blocks if b["type"] == "text"), True)
    check(
        "텍스트 블록을 이어 붙이면 원문 복원",
        "".join(
            b["text"] if b["type"] == "text" else f"<image {b['image'].label.split('_')[1]}>"
            for b in blocks
        ),
        prompt_text,
    )

    # 선택지에만 마커가 있는 경우 이미지 3장이 모두 들어가야 합니다.
    bio_prompt, _ = build_prompt(bio24, "anchored")
    bio_blocks = build_messages(bio24, bio_prompt)[0]["content"]
    check(
        "options 에만 마커 -> 이미지 3장 모두 전달",
        [b["image"].label for b in bio_blocks if b["type"] == "image"],
        ["image_1", "image_2", "image_3"],
    )

    # 방어 동작
    try:
        build_messages(math19, "보이나요? <image 3>")
        check("대응 이미지 없는 마커 거부", False, True)
    except ValueError:
        check("대응 이미지 없는 마커 거부", True, True)
    try:
        build_messages(math19, "마커 없는 프롬프트")
        check("참조되지 않은 이미지 거부", False, True)
    except ValueError:
        check("참조되지 않은 이미지 거부", True, True)
    try:
        build_prompt(math19, "nope")
        check("알 수 없는 템플릿 거부", False, True)
    except ValueError:
        check("알 수 없는 템플릿 거부", True, True)
    bad_type = _demo_sample("validation_Math_1", "q <image 1>", ["a", "b"], "short", [1])
    try:
        build_prompt(bad_type, "anchored")
        check("알 수 없는 question_type 거부", False, True)
    except ValueError:
        check("알 수 없는 question_type 거부", True, True)

    # 선택지가 9개인 문항도 A~I로 정상 동작해야 합니다(FACTS 4).
    nine = _demo_sample(
        "validation_Pharmacy_22",
        "See <image 1>.",
        [f"opt{i}" for i in range(9)],
        "multiple-choice",
        [1],
    )
    nine_text, nine_letters = build_prompt(nine, "anchored")
    check("9지 선다 문자", nine_letters, list("ABCDEFGHI"))
    check("9지 선다 마지막 줄 표기", "(I) opt8" in nine_text, True)

    print()
    if failures:
        print(f">>> 실패 {failures}건.")
    else:
        print(">>> 모든 항목 통과.")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _self_check() else 0)

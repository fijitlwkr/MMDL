"""MMMU 공식 채점기(mmmu/utils/eval_utils.py)의 동작 호환 재구현.

이 모듈의 목표는 "더 똑똑한 파서"가 아니라 **공식 파서와 똑같이 틀리는 파서**입니다.
교수님 보고서에서 비교 대상으로 쓰는 공개 점수(MMMU validation 67.4, FACTS 0)는
MMMU-Benchmark/MMMU 저장소의 `mmmu/utils/eval_utils.py` 알고리즘으로 산출된 값이므로,
파서를 '개선'하면 우리 점수와 67.4는 더 이상 같은 자 위에서 비교되지 않습니다.
그래서 아래 구현은 공식 코드의 기묘한 부분(대소문자 민감, 토큰 5개 게이트,
무작위 찍기, 소문자화 후의 죽은 정규식 분기)까지 의도적으로 보존합니다.

다만 **무작위 fallback은 숨기지 않습니다.** :func:`score_sample` 은 fallback이 발동하면
``unparseable=True`` 를 돌려주므로, 호출자(src/eval_mmmu.py)가 그 개수를
metrics.json 의 ``n_unparseable`` 로 보고할 수 있습니다(FACTS 4c, INTERFACES).

공식 구현과 다르게 한 점은 다음 두 가지뿐이며, 채점 결과(정답/오답)에는 영향이 없습니다.
  1) ``numpy.argmax`` 대신 순수 파이썬 :func:`_argmax` 를 사용합니다
     (동점일 때 '첫 번째 최대값'을 고르는 numpy 동작까지 동일하게 맞춤).
  2) :func:`parse_open_response` 의 중복 제거 결과를 결정적으로 정렬해서 돌려줍니다.
     공식 코드는 ``list(set(...))`` 이라 순서가 실행마다 달라질 수 있는데,
     open 채점은 "하나라도 맞으면 정답"이라 순서가 점수에 영향을 주지 않습니다.
     팀원 4명이 predictions.jsonl 을 diff 해서 원인을 가려야 하므로(FACTS 7)
     기록되는 문자열은 결정적이어야 합니다.

참고 소스: MMMU-Benchmark/MMMU 의 mmmu/utils/eval_utils.py, mmmu/utils/data_utils.py
(FACTS 4: 현재 main 에는 eval/ 디렉터리가 없습니다).
"""

from __future__ import annotations

import ast
import json
import logging
import random
import re
import unicodedata
from typing import Any

__all__ = [
    "OFFICIAL_PARSER_SEED",
    "FALLBACK_BEHAVIOUR",
    "FALLBACK_BEHAVIOUR_NOTE",
    "OPTION_TEXT_MATCH_MIN_TOKENS",
    "MC_QUESTION_TYPE",
    "OPEN_QUESTION_TYPES",
    "seed_official_parser",
    "get_multi_choice_info",
    "parse_multi_choice_response",
    "parse_multi_choice_response_ex",
    "parse_open_response",
    "eval_multi_choice",
    "eval_open",
    "check_is_number",
    "normalize_str",
    "extract_numbers",
    "normalize_gold_answer",
    "score_sample",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 공식 파서의 "설정값"들. 보고서가 그대로 인용할 수 있도록 모듈 상수로 고정합니다.
# ---------------------------------------------------------------------------

#: 공식 eval_utils.py 가 import 시점에 호출하는 시드 값 (FACTS 4c).
OFFICIAL_PARSER_SEED: int = 42

#: 어떤 패스로도 보기를 찾지 못했을 때 공식 파서가 하는 일. 보고서 인용용 상수.
FALLBACK_BEHAVIOUR: str = "random.choice(all_choices)"

#: 위 동작에 대한 한국어 설명. ENVIRONMENT.md / 보고서 각주에 그대로 붙일 수 있습니다.
FALLBACK_BEHAVIOUR_NOTE: str = (
    "MMMU 공식 파서(mmmu/utils/eval_utils.py::parse_multi_choice_response)는 "
    "괄호 패스·공백 패스·보기 본문 패스가 모두 실패하면 오답 처리 대신 "
    f"{FALLBACK_BEHAVIOUR} 로 보기 하나를 무작위로 찍습니다. "
    f"공식 모듈은 import 시점에 random.seed({OFFICIAL_PARSER_SEED}) 를 호출하므로 "
    "이 '찍기'의 결과는 전역 random 스트림, 즉 샘플 처리 순서에 의존합니다. "
    "따라서 채점 순서를 고정하고 채점 루프 직전에 다시 시드를 심어야 하며, "
    "발동 횟수(n_unparseable)를 반드시 함께 보고해야 합니다."
)

#: 보기 '본문' 매칭 패스의 게이트. 공식 코드는 len(response.split()) > 5 로 막아 두었고,
#: 그래서 'The correct option is $8'(정확히 5토큰)은 본문 매칭을 아예 시도하지 못하고
#: 무작위 찍기로 떨어집니다 (FACTS 4c, 경험적으로 확인됨).
OPTION_TEXT_MATCH_MIN_TOKENS: int = 5

#: 공식 파서가 응답 양끝에서 차례로 제거하는 문자들. 한 번에 strip 하지 않고
#: 리스트 순서대로 strip 을 7번 적용하는 점까지 동일해야 합니다('C.,' -> 'C').
_STRIP_CHARS: tuple[str, ...] = (",", ".", "!", "?", ";", ":", "'")

#: HF MMMU/MMMU 의 question_type 값 (FACTS 4: 'multiple-choice' 847개 / 'open' 53개).
MC_QUESTION_TYPE: str = "multiple-choice"
#: MMMU 저장소의 answer_dict_val.json 은 같은 문항을 'short-answer' 로 부르므로 함께 받습니다.
OPEN_QUESTION_TYPES: frozenset[str] = frozenset({"open", "short-answer"})

# 공식 모듈과 동일하게 import 시점에 전역 시드를 심습니다 (FACTS 4c).
# lmms-eval 의 사본은 이 한 줄이 없어서 점수가 미세하게 달라집니다.
# 주의: 이것은 전역 random 스트림을 건드리는 부작용입니다. eval_mmmu.py 는 이 시드에
# 의존하지 말고 채점 루프 직전에 seed_official_parser() 를 다시 호출해야 합니다.
random.seed(OFFICIAL_PARSER_SEED)


def seed_official_parser(seed: int = OFFICIAL_PARSER_SEED) -> None:
    """무작위 fallback이 쓰는 전역 random 스트림을 공식 시드로 되돌립니다.

    채점 루프 **직전에** 호출하십시오. 모델 로딩이나 샘플링이 중간에 random 을
    소비하면 fallback 결과가 달라지고, 팀원 간 점수 비교가 불가능해집니다.
    """
    random.seed(seed)


# ---------------------------------------------------------------------------
# 보기 정보 (mmmu/utils/data_utils.py::get_multi_choice_info)
# ---------------------------------------------------------------------------


def get_multi_choice_info(options: list[str]) -> tuple[dict[str, str], list[str]]:
    """보기 리스트로부터 ``(index2ans, all_choices)`` 를 만듭니다.

    'A' 부터 보기 개수만큼 글자를 자동 생성합니다. MMMU validation 에는 보기가
    2/3/4/5/6/7/9개인 문항이 섞여 있고(847개 중 241개가 4지선다가 아님, FACTS 4),
    정답 글자는 A..I 까지 나오므로 ``['A','B','C','D']`` 를 하드코딩하면
    보기 개수가 다른 문항에서 조용히 오답 처리됩니다.
    """
    start_chr = "A"
    all_choices: list[str] = []
    index2ans: dict[str, str] = {}
    for i, option in enumerate(options):
        letter = chr(ord(start_chr) + i)
        index2ans[letter] = option
        all_choices.append(letter)
    return index2ans, all_choices


def _argmax(values: list[int]) -> int:
    """``numpy.argmax`` 와 동일한 규칙(동점이면 가장 앞 인덱스)의 순수 파이썬 구현.

    공식 코드가 ``np.argmax(start_indexes)`` 를 쓰는 자리를 대체합니다.
    numpy 를 의존성에서 빼기 위한 것일 뿐, 동작은 같습니다.
    """
    best_i = 0
    best_v = values[0]
    for i in range(1, len(values)):
        if values[i] > best_v:
            best_v = values[i]
            best_i = i
    return best_i


# ---------------------------------------------------------------------------
# 객관식 파서
# ---------------------------------------------------------------------------


def parse_multi_choice_response_ex(
    response: str,
    all_choices: list[str],
    index2ans: dict[str, str],
) -> tuple[str, bool]:
    """공식 :func:`parse_multi_choice_response` + "무작위였는지" 플래그.

    Returns:
        ``(예측 글자, used_random_fallback)``. 두 번째 값이 True 면
        어떤 패스도 성공하지 못해 :data:`FALLBACK_BEHAVIOUR` 가 발동한 것입니다.

    공식 알고리즘(순서가 중요):
      1) 양끝 구두점 제거 → 앞뒤에 공백 한 칸 추가(부분 일치 방지).
      2) ``(A)`` 형태의 괄호 표기 탐색.
      3) 없으면 ``' A '`` 형태(양쪽이 공백인 단독 글자) 탐색. **대소문자 구분**이라
         'c' 같은 소문자 답은 절대 잡히지 않습니다(FACTS 4c).
      4) 그래도 없고 토큰 수가 5개를 넘으면 보기 **본문** 매칭.
      5) 전부 실패하면 무작위 찍기.
      6) 후보가 2개 이상이면 '마지막으로 등장한' 후보를 고릅니다(rfind + argmax).
    """
    if not all_choices:
        # 보기가 비어 있으면 random.choice 가 IndexError 를 냅니다. 조용히 넘기면
        # 전체 점수가 망가지므로 명시적으로 실패시킵니다.
        raise ValueError("all_choices 가 비어 있습니다. 객관식 문항의 options 가 비었는지 확인하십시오.")

    for char in _STRIP_CHARS:
        response = response.strip(char)
    response = " " + response + " "  # 부분 일치 방지용 패딩 (공식 코드와 동일)

    index_ans = True
    ans_with_brack = False
    candidates: list[str] = []

    # (1) '(A)' 형태
    for choice in all_choices:
        if f"({choice})" in response:
            candidates.append(choice)
            ans_with_brack = True

    # (2) ' A ' 형태. 양쪽 공백이 모두 필요하므로 '**C**' 나 'C) $8' 는 여기서도 실패합니다.
    if len(candidates) == 0:
        for choice in all_choices:
            if f" {choice} " in response:
                candidates.append(choice)

    # (3) 보기 본문 매칭. 게이트가 '> 5' 라서 정확히 5토큰인 응답은 제외됩니다(FACTS 4c).
    if len(candidates) == 0 and len(response.split()) > OPTION_TEXT_MATCH_MIN_TOKENS:
        for index, ans in index2ans.items():
            if str(ans).lower() in response.lower():
                candidates.append(index)
                index_ans = False  # 글자가 아니라 본문으로 맞춘 경우

    # (4) 끝까지 실패 → 무작위 찍기. 여기서만 전역 random 을 소비합니다.
    if len(candidates) == 0:
        pred_index = random.choice(all_choices)
        return pred_index, True

    if len(candidates) > 1:
        start_indexes: list[int] = []
        if index_ans:
            if ans_with_brack:
                for can in candidates:
                    start_indexes.append(response.rfind(f"({can})"))
            else:
                for can in candidates:
                    start_indexes.append(response.rfind(f" {can} "))
        else:
            for can in candidates:
                start_indexes.append(response.lower().rfind(str(index2ans[can]).lower()))
        # 가장 뒤에 등장한 후보를 채택 (공식 코드의 np.argmax(start_indexes))
        pred_index = candidates[_argmax(start_indexes)]
    else:
        pred_index = candidates[0]

    return pred_index, False


def parse_multi_choice_response(
    response: str,
    all_choices: list[str],
    index2ans: dict[str, str],
) -> str:
    """공식 파서와 **시그니처·반환값이 동일한** 래퍼.

    무작위 fallback 여부까지 알고 싶으면 :func:`parse_multi_choice_response_ex` 를
    쓰십시오. 두 함수의 random 소비량은 완전히 같습니다(fallback 경로에서 정확히 1회).
    """
    pred_index, _used_random = parse_multi_choice_response_ex(response, all_choices, index2ans)
    return pred_index


# ---------------------------------------------------------------------------
# 단답형(open) 파서 — 공식 eval_utils.py 의 숫자/문자열 정규화 그대로
# ---------------------------------------------------------------------------


def check_is_number(string: str) -> bool:
    """``float()`` 로 변환 가능한 문자열인지 판정합니다(천단위 콤마 허용)."""
    try:
        float(str(string).replace(",", ""))
        return True
    except ValueError:
        return False


def normalize_str(string: Any) -> list[Any]:
    """공식 정규화: 숫자면 float 로 바꿔 소수점 2자리로 반올림, 아니면 소문자화.

    길이 1인 문자열은 ``[" c", "c "]`` 처럼 공백을 붙인 두 변형으로 돌려줍니다.
    단답형 정답 중 4개가 맨 글자 하나('C','B','A','A', FACTS 4c)인데,
    공백을 붙이지 않으면 'd' 같은 응답 안에 'c' 가 우연히 포함되는 식의
    허위 정답(trivial match)이 생기기 때문입니다.
    """
    string = str(string).strip()
    if check_is_number(string):
        string = string.replace(",", "")
        value = round(float(string), 2)  # 공식 코드와 동일하게 소수 2자리
        return [value]
    string = string.lower()
    if len(string) == 1:
        return [" " + string, string + " "]
    return [string]


def extract_numbers(string: str) -> list[str]:
    """문자열에서 모든 형태의 숫자를 뽑아냅니다(공식 정규식 3종 그대로).

    콤마 숫자 / 지수 표기 / 일반 숫자를 각각 찾아 그냥 이어 붙이므로
    '1,024' 에서 '024' 가 중복 추출되는 등 잡음이 섞입니다.
    이 잡음도 공식 채점 결과의 일부이므로 '정리'하지 않습니다.
    """
    pattern_commas = r"-?\b\d{1,3}(?:,\d{3})+\b"
    pattern_scientific = r"-?\d+(?:\.\d+)?[eE][+-]?\d+"
    pattern_simple = r"-?(?:\d+\.\d+|\.\d+|\d+\b)(?![eE][+-]?\d+)(?![,\d])"

    numbers_with_commas = re.findall(pattern_commas, string)
    numbers_scientific = re.findall(pattern_scientific, string)
    numbers_simple = re.findall(pattern_simple, string)
    return numbers_with_commas + numbers_scientific + numbers_simple


def _get_key_subresponses(response: str) -> list[str]:
    """응답에서 '정답이 들어 있을 법한 뒷부분'들을 잘라냅니다(공식 내부 함수).

    주의: 공식 코드는 먼저 ``.lower()`` 를 호출한 뒤 ``r'\\.\\s(?=[A-Z])|\\n'`` 로
    분할합니다. 이미 소문자가 된 문자열에 ``[A-Z]`` 를 찾으므로 문장 분할 분기는
    사실상 죽은 코드이고 개행만 유효하게 동작합니다. 동작 호환성을 위해
    버그를 '고치지 않고' 그대로 둡니다.
    """
    response = response.strip().strip(".").lower()
    sub_responses = re.split(r"\.\s(?=[A-Z])|\n", response)
    indicators_of_keys = [
        "could be ",
        "so ",
        "is ",
        "thus ",
        "therefore ",
        "final ",
        "answer ",
        "result ",
    ]
    key_responses: list[str] = []
    for index, resp in enumerate(sub_responses):
        # 마지막 조각에서는 수식('=')도 단서로 인정 (공식 코드가 루프 안에서 extend 함)
        if index == len(sub_responses) - 1:
            indicators_of_keys.extend(["="])
        shortest_key_response = None  # 가장 짧은(= 가장 답에 가까운) 꼬리 조각
        for indicator in indicators_of_keys:
            if indicator in resp:
                tail = resp.split(indicator)[-1].strip()
                if not shortest_key_response:
                    shortest_key_response = tail
                elif len(tail) < len(shortest_key_response):
                    shortest_key_response = tail
        if shortest_key_response:
            if shortest_key_response.strip() not in [":", ",", ".", "!", "?", ";", ":", "'"]:
                key_responses.append(shortest_key_response)
    if len(key_responses) == 0:  # 단서를 못 찾으면 응답 전체를 후보로 사용
        return [response]
    return key_responses


def parse_open_response(response: str) -> list:
    """단답형 응답을 비교 가능한 후보 리스트로 정규화합니다.

    반환 리스트에는 문자열과 float 이 섞여 있습니다(공식 동작). 객관식과 달리
    **무작위 찍기가 없으므로** 단답형은 절대 ``unparseable`` 이 되지 않습니다.
    """
    key_responses = _get_key_subresponses(response)

    pred_list = list(key_responses)  # 원문 꼬리 조각도 후보로 유지
    for resp in key_responses:
        pred_list.extend(extract_numbers(resp))

    tmp_pred_list: list[Any] = []
    for item in pred_list:
        tmp_pred_list.extend(normalize_str(item))
    pred_list = tmp_pred_list

    # 공식 코드는 list(set(...)) 이라 순서가 비결정적입니다. 채점 결과는 순서와
    # 무관하므로, 팀원 간 predictions.jsonl diff 를 위해 결정적으로 정렬합니다.
    deduped = set(pred_list)
    return sorted(deduped, key=lambda v: (isinstance(v, str), str(v)))


# ---------------------------------------------------------------------------
# 정답 비교
# ---------------------------------------------------------------------------


def eval_multi_choice(gold_i: Any, pred_i: str) -> bool:
    """객관식 채점: 글자가 **정확히** 같을 때만 정답(정답이 리스트면 그중 하나와 일치)."""
    if isinstance(gold_i, list):
        for answer in gold_i:
            if answer == pred_i:
                return True
        return False
    return gold_i == pred_i


def eval_open(gold_i: Any, pred_list: list) -> bool:
    """단답형 채점: 후보 중 하나라도 정답과 맞으면 정답.

    문자열 후보는 '정답 문자열이 후보 안에 포함되는지'(부분 일치)로,
    숫자 후보는 소수 2자리로 반올림된 값의 완전 일치로 비교합니다.
    """
    if isinstance(gold_i, list):
        norm_answers: list[Any] = []
        for answer in gold_i:
            norm_answers.extend(normalize_str(answer))
    else:
        norm_answers = normalize_str(gold_i)

    for pred in pred_list:  # pred 는 parse 단계에서 이미 정규화됨
        if isinstance(pred, str):
            for norm_ans in norm_answers:
                if isinstance(norm_ans, str) and norm_ans in pred:
                    return True
        else:
            if pred in norm_answers:
                return True
    return False


# ---------------------------------------------------------------------------
# 샘플 단위 채점 (이 모듈의 공개 진입점)
# ---------------------------------------------------------------------------

_LIST_LITERAL_RE = re.compile(r"^\s*\[.*\]\s*$", re.DOTALL)


def normalize_gold_answer(answer: Any, question_type: str) -> Any:
    """parquet 의 ``answer`` 필드를 채점 가능한 형태로 바꿉니다.

    단답형 정답 3개가 파이썬 리스트를 문자열로 저장한 형태입니다(FACTS 4c):
    validation_Chemistry_30 ``"['$MgS$', 'MgS']"``, validation_Geography_4
    ``"['Tampa', 'Florida']"``, validation_Math_15 ``"['24/7', '3.429']"``.
    이들을 문자열 그대로 비교하면 정답을 맞혀도 오답으로 처리됩니다.
    ``options`` 와 같은 이유로 json.loads 가 아니라 ast.literal_eval 을 씁니다(FACTS 4).

    ``"[0, 5)"`` 처럼 리스트처럼 보이지만 리스트가 아닌 값은 literal_eval 이 실패하는데,
    이때는 원문 문자열을 그대로 쓰되 WARNING 을 남깁니다(조용히 넘기지 않음).
    """
    if isinstance(answer, (list, tuple)):
        return [str(a) for a in answer]
    if answer is None:
        raise ValueError("정답(answer)이 None 입니다. 데이터 로딩 단계를 확인하십시오.")

    text = str(answer).strip()
    if _LIST_LITERAL_RE.match(text):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            logger.warning(
                "정답 문자열이 리스트처럼 보이지만 literal_eval 에 실패했습니다. "
                "원문 그대로 채점합니다: %r",
                text,
            )
            return text
        if isinstance(parsed, (list, tuple)):
            return [str(p) for p in parsed]
        logger.warning("정답 literal_eval 결과가 리스트가 아닙니다(%r). 원문으로 채점합니다.", parsed)
        return text

    if question_type == MC_QUESTION_TYPE:
        return text  # 객관식 정답은 'A'..'I' 한 글자
    return text


def _coerce_response(response: Any, sample_id: str) -> str:
    """생성 실패로 None 이 들어오는 경우를 공식 파서의 빈 문자열 경로로 넘깁니다."""
    if response is None:
        logger.warning(
            "%s: 응답이 None 입니다. 공식 파서의 '' 경로(무작위 fallback)로 처리하고 "
            "unparseable 로 집계합니다.",
            sample_id,
        )
        return ""
    if not isinstance(response, str):
        raise TypeError(f"{sample_id}: response 는 str 또는 None 이어야 합니다(받은 타입: {type(response)!r}).")
    return response


def score_sample(sample: Any, response: str | None) -> dict:
    """샘플 하나를 채점합니다.

    Args:
        sample: ``id``, ``question_type``, ``options``, ``answer`` 속성을 가진 객체
            (:class:`src.mmmu_data.MMMUSample`). 순환 import 를 피하려고 타입을
            강제하지 않고 속성만 읽습니다.
        response: 모델 원문 응답. None 이면 빈 문자열로 처리합니다.

    Returns:
        ``{"parsed": str, "correct": bool, "unparseable": bool}``
        (키는 INTERFACES 계약과 정확히 일치, 추가 키 없음)

        * 객관식: ``parsed`` 는 예측 글자, ``unparseable`` 은 무작위 찍기 발동 여부.
        * 단답형: ``parsed`` 는 정규화된 후보 리스트의 JSON 문자열,
          ``unparseable`` 은 항상 False(단답형 경로에는 무작위 찍기가 없음).
    """
    sample_id = str(getattr(sample, "id", "<unknown>"))
    if not hasattr(sample, "question_type") or not hasattr(sample, "answer"):
        raise AttributeError(
            f"{sample_id}: sample 에 question_type/answer 속성이 필요합니다(MMMUSample 을 넘기십시오)."
        )

    question_type = str(getattr(sample, "question_type"))
    options = getattr(sample, "options", None) or []
    gold_raw = getattr(sample, "answer")
    text = _coerce_response(response, sample_id)

    if question_type == MC_QUESTION_TYPE:
        if not options:
            # 보기 없이 객관식으로 채점하면 전 문항이 무작위가 됩니다. 조용한 실패 금지.
            raise ValueError(
                f"{sample_id}: question_type='{MC_QUESTION_TYPE}' 인데 options 가 비어 있습니다. "
                "mmmu_data 의 ast.literal_eval 단계를 확인하십시오."
            )
        index2ans, all_choices = get_multi_choice_info(list(options))
        pred, used_random = parse_multi_choice_response_ex(text, all_choices, index2ans)
        gold = normalize_gold_answer(gold_raw, question_type)
        if isinstance(gold, str) and gold not in all_choices:
            # 정답 글자가 보기 범위를 벗어나면 해당 문항은 영원히 오답이 됩니다.
            # 런을 죽이지는 않되(추론 시간이 아깝다) 반드시 눈에 띄게 기록합니다.
            logger.error(
                "%s: 정답 글자 %r 가 보기 범위 %s 밖입니다. 데이터/정답 키를 확인하십시오.",
                sample_id,
                gold,
                all_choices,
            )
        correct = eval_multi_choice(gold, pred)
        return {"parsed": pred, "correct": bool(correct), "unparseable": bool(used_random)}

    if question_type in OPEN_QUESTION_TYPES:
        if options:
            # FACTS 4: 단답형은 options == '[]' 이어야 합니다.
            logger.warning("%s: 단답형인데 options 가 비어 있지 않습니다(%d개). question_type 을 따릅니다.",
                           sample_id, len(options))
        pred_list = parse_open_response(text)
        gold = normalize_gold_answer(gold_raw, question_type)
        correct = eval_open(gold, pred_list)
        return {
            "parsed": json.dumps(pred_list, ensure_ascii=False),
            "correct": bool(correct),
            "unparseable": False,
        }

    raise ValueError(
        f"{sample_id}: 알 수 없는 question_type={question_type!r}. "
        f"'{MC_QUESTION_TYPE}' 또는 {sorted(OPEN_QUESTION_TYPES)} 중 하나여야 합니다."
    )


# ===========================================================================
# 자체 검증 (900문항 본 실행 전에 반드시 한 번 돌려 보십시오)
#   python src/mmmu_parser.py
# FACTS 4c 에 기록된 함정 사례를 그대로 통과시켜, 파서가 공식 동작과 같은지 확인합니다.
# ===========================================================================

if __name__ == "__main__":  # pragma: no cover
    import sys
    from dataclasses import dataclass, field

    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")

    RANDOM_SENTINEL = "<무작위>"

    @dataclass
    class _SelfTestSample:
        """MMMUSample 의 최소 대역(self-test 전용, src.mmmu_data 를 import 하지 않음)."""

        id: str
        question_type: str
        answer: str
        options: list = field(default_factory=list)

    def _display_width(text: str) -> int:
        """한글/전각 문자를 2칸으로 세어 표 정렬을 맞춥니다."""
        return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)

    def _pad(text: str, width: int) -> str:
        return text + " " * max(0, width - _display_width(text))

    rows: list[list[str]] = []
    n_pass = 0
    n_fail = 0

    def _check(kind: str, desc: str, expected: str, actual: str, ok: bool) -> None:
        global n_pass, n_fail
        if ok:
            n_pass += 1
        else:
            n_fail += 1
        rows.append([str(len(rows) + 1), kind, desc, expected, actual, "PASS" if ok else "FAIL"])

    # -------------------------------------------------------------------
    # 1) 객관식: FACTS 4c 의 함정 사례
    #    보기는 일부러 '$8' 을 포함시켜, 본문 매칭 게이트(>5토큰)의 효과를 드러냅니다.
    # -------------------------------------------------------------------
    OPTIONS_4 = ["$6", "$8", "$10", "$12"]
    MC_CASES: list[tuple[str, str, list[str], str]] = [
        # (설명, 응답, 보기, 기대 parsed)
        ("괄호 표기", "(B)", OPTIONS_4, "B"),
        ("Answer: 글자", "Answer: C", OPTIONS_4, "C"),
        ("글자 단독", "C", OPTIONS_4, "C"),
        ("끝 구두점 제거", "C.", OPTIONS_4, "C"),
        ("마지막 괄호 채택", "The answer is (A), but some say (D).", OPTIONS_4, "D"),
        ("공백패스 다중후보→뒤쪽", "Between A and B, I choose B", OPTIONS_4, "B"),
        ("본문 매칭(6토큰)", "The correct option here is $8", OPTIONS_4, "B"),
        ("[함정] 마크다운 굵게", "**C**", OPTIONS_4, RANDOM_SENTINEL),
        ("[함정] 'C) $8' 형식", "C) $8", OPTIONS_4, RANDOM_SENTINEL),
        ("[함정] 소문자 c", "c", OPTIONS_4, RANDOM_SENTINEL),
        ("[함정] 빈 응답", "", OPTIONS_4, RANDOM_SENTINEL),
        ("[함정] 정확히 5토큰", "The correct option is $8", OPTIONS_4, RANDOM_SENTINEL),
        ("[함정] 긴 문장 속 소문자 c", "I am fairly sure that the final answer is c", OPTIONS_4, RANDOM_SENTINEL),
    ]

    seed_official_parser()
    for desc, resp, opts, expected in MC_CASES:
        index2ans, all_choices = get_multi_choice_info(opts)
        pred, used_random = parse_multi_choice_response_ex(resp, all_choices, index2ans)
        if expected is RANDOM_SENTINEL:
            ok = used_random and pred in all_choices
            actual = f"{pred} (무작위={used_random})"
        else:
            ok = (pred == expected) and (not used_random)
            actual = f"{pred} (무작위={used_random})"
        _check("MC", f"{desc}: {resp!r}", expected, actual, ok)

    # 보기 9개(A..I)까지 글자가 자동 확장되는지 — FACTS 4: 정답은 A..I 범위
    _i2a9, _ac9 = get_multi_choice_info(["opt"] * 9)
    _check(
        "MC",
        "보기 9개 → all_choices",
        "A..I",
        "".join(_ac9),
        _ac9 == list("ABCDEFGHI"),
    )
    _pred9, _rand9 = parse_multi_choice_response_ex("Answer: I", _ac9, _i2a9)
    _check("MC", "9지선다 'Answer: I'", "I", f"{_pred9} (무작위={_rand9})", _pred9 == "I" and not _rand9)

    # -------------------------------------------------------------------
    # 2) 무작위 fallback 의 재현성 — 같은 시드 + 같은 순서 = 같은 결과
    # -------------------------------------------------------------------
    FALLBACK_RESPONSES = ["**C**", "C) $8", "c", ""]
    _i2a, _ac = get_multi_choice_info(OPTIONS_4)

    seed_official_parser()
    first = [parse_multi_choice_response(r, _ac, _i2a) for r in FALLBACK_RESPONSES]
    seed_official_parser()
    second = [parse_multi_choice_response(r, _ac, _i2a) for r in FALLBACK_RESPONSES]
    _check(
        "SEED",
        "시드 재설정 후 동일 순서 재현",
        "".join(first),
        "".join(second),
        first == second,
    )

    seed_official_parser()
    random.choice(_ac)  # 난수 1회를 미리 소비 = 샘플 순서가 하나 밀린 상황
    shifted = [parse_multi_choice_response(r, _ac, _i2a) for r in FALLBACK_RESPONSES]

    # -------------------------------------------------------------------
    # 3) 단답형: 문자열 리스트 정답, 맨 글자 정답, 숫자 반올림
    # -------------------------------------------------------------------
    OPEN_CASES: list[tuple[str, str, str, bool]] = [
        # (설명, 응답, parquet 의 answer 원문, 기대 correct)
        ("리스트형 정답(Chemistry_30)", "The product is MgS.", "['$MgS$', 'MgS']", True),
        ("리스트형 정답(Geography_4)", "It is Tampa", "['Tampa', 'Florida']", True),
        ("리스트형 정답(Math_15)", "Therefore the answer is 3.429", "['24/7', '3.429']", True),
        ("맨 글자 정답 C - 정답", "The answer is C", "C", True),
        ("맨 글자 정답 C - 오답", "The answer is D", "C", False),
        ("숫자 정답", "so the result is 8", "8", True),
        ("소수 2자리 반올림 허용", "thus the value is 3.4291", "3.429", True),
        ("빈 응답은 오답(무작위 없음)", "", "8", False),
    ]
    for desc, resp, gold, expected_correct in OPEN_CASES:
        s = _SelfTestSample(id=f"selftest_open_{len(rows)}", question_type="open", answer=gold)
        out = score_sample(s, resp)
        ok = (out["correct"] is expected_correct) and (out["unparseable"] is False)
        _check(
            "OPEN",
            f"{desc}: {resp!r} vs {gold}",
            f"correct={expected_correct}, unparseable=False",
            f"correct={out['correct']}, unparseable={out['unparseable']}",
            ok,
        )

    # -------------------------------------------------------------------
    # 4) 정규화 헬퍼 단위 검증
    # -------------------------------------------------------------------
    _check("UNIT", "check_is_number('1,234')", "True", str(check_is_number("1,234")), check_is_number("1,234") is True)
    _check("UNIT", "check_is_number('24/7')", "False", str(check_is_number("24/7")), check_is_number("24/7") is False)
    _check("UNIT", "normalize_str('1,234')", "[1234.0]", str(normalize_str("1,234")), normalize_str("1,234") == [1234.0])
    _check("UNIT", "normalize_str('C') 공백변형", "[' c', 'c ']", str(normalize_str("C")), normalize_str("C") == [" c", "c "])
    _check("UNIT", "normalize_str('MgS')", "['mgs']", str(normalize_str("MgS")), normalize_str("MgS") == ["mgs"])
    _nums = extract_numbers("the value is -3.5e2 and 1,024 and 7")
    _check(
        "UNIT",
        "extract_numbers 3종 정규식",
        "-3.5e2 / 1,024 / 7 포함",
        str(_nums),
        all(tok in _nums for tok in ("-3.5e2", "1,024", "7")),
    )
    _check("UNIT", "eval_multi_choice('B','B')", "True", str(eval_multi_choice("B", "B")), eval_multi_choice("B", "B") is True)
    _check(
        "UNIT",
        "eval_multi_choice(['A','B'],'B')",
        "True",
        str(eval_multi_choice(["A", "B"], "B")),
        eval_multi_choice(["A", "B"], "B") is True,
    )
    _check("UNIT", "eval_multi_choice('A','B')", "False", str(eval_multi_choice("A", "B")), eval_multi_choice("A", "B") is False)
    _check(
        "UNIT",
        "parse_open_response 결정적 정렬",
        "동일",
        "동일" if parse_open_response("so the result is 8") == parse_open_response("so the result is 8") else "불일치",
        parse_open_response("so the result is 8") == parse_open_response("so the result is 8"),
    )

    # -------------------------------------------------------------------
    # 5) score_sample 의 unparseable 집계 — 보고서의 n_unparseable 과 같은 경로
    # -------------------------------------------------------------------
    seed_official_parser()
    n_unparseable = 0
    for desc, resp, opts, expected in MC_CASES:
        s = _SelfTestSample(id=f"selftest_mc_{desc}", question_type=MC_QUESTION_TYPE, answer="B", options=opts)
        out = score_sample(s, resp)
        n_unparseable += int(out["unparseable"])
    expected_unparseable = sum(1 for c in MC_CASES if c[3] is RANDOM_SENTINEL)
    _check(
        "COUNT",
        "score_sample 의 unparseable 개수",
        str(expected_unparseable),
        str(n_unparseable),
        n_unparseable == expected_unparseable,
    )

    # None 응답도 빈 문자열 경로로 집계되는지 (생성 실패 방어)
    _s_none = _SelfTestSample(id="selftest_mc_none", question_type=MC_QUESTION_TYPE, answer="B", options=OPTIONS_4)
    _out_none = score_sample(_s_none, None)
    _check(
        "COUNT",
        "response=None → unparseable",
        "unparseable=True",
        f"unparseable={_out_none['unparseable']}",
        _out_none["unparseable"] is True,
    )

    # 계약 위반(객관식인데 options 없음)은 조용히 넘기지 말고 예외
    try:
        score_sample(_SelfTestSample(id="selftest_mc_empty", question_type=MC_QUESTION_TYPE, answer="A"), "(A)")
        _raised = False
    except ValueError:
        _raised = True
    _check("GUARD", "객관식인데 options=[] → ValueError", "예외 발생", "예외 발생" if _raised else "예외 없음", _raised)

    try:
        score_sample(_SelfTestSample(id="selftest_bad_type", question_type="essay", answer="A"), "x")
        _raised2 = False
    except ValueError:
        _raised2 = True
    _check("GUARD", "알 수 없는 question_type → ValueError", "예외 발생", "예외 발생" if _raised2 else "예외 없음", _raised2)

    # -------------------------------------------------------------------
    # 결과 표 출력
    # -------------------------------------------------------------------
    header = ["#", "구분", "사례", "기대", "실제", "판정"]
    table = [header] + rows
    widths = [max(_display_width(r[c]) for r in table) for c in range(len(header))]

    print()
    print("=" * (sum(widths) + 3 * (len(widths) - 1)))
    print("MMMU 공식 파서 동작 호환성 자체 검증 (FACTS 4c 함정 사례)")
    print("=" * (sum(widths) + 3 * (len(widths) - 1)))
    print(" | ".join(_pad(header[c], widths[c]) for c in range(len(header))))
    print("-+-".join("-" * widths[c] for c in range(len(header))))
    for r in rows:
        print(" | ".join(_pad(r[c], widths[c]) for c in range(len(header))))
    print("-" * (sum(widths) + 3 * (len(widths) - 1)))
    print(f"통과 {n_pass} / 전체 {n_pass + n_fail}   (실패 {n_fail})")
    print()
    print("[무작위 fallback 메모]")
    print(f"  동작          : {FALLBACK_BEHAVIOUR}")
    print(f"  공식 시드     : random.seed({OFFICIAL_PARSER_SEED})")
    print(f"  본문패스 게이트: len(response.split()) > {OPTION_TEXT_MATCH_MIN_TOKENS}")
    print(f"  시드 직후 순서: {first}")
    print(f"  난수 1회 소비 후: {shifted}")
    print("  → 같은 응답이라도 '찍기' 결과는 처리 순서에 따라 달라집니다.")
    print("    그래서 채점 순서를 고정하고, 채점 루프 직전에 seed_official_parser() 를 호출하며,")
    print("    n_unparseable 을 metrics.json 에 반드시 기록해야 합니다.")
    print()
    print(FALLBACK_BEHAVIOUR_NOTE)
    print()

    sys.exit(1 if n_fail else 0)

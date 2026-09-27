#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MMMU 데이터 로더 — MMMU의 까다로운 부분을 전부 이 모듈에서 처리합니다.

이 모듈은 MMMU(`MMMU/MMMU`)를 읽어 평가 스크립트가 그대로 쓸 수 있는
`MMMUSample` 리스트로 변환합니다. MMMU는 "조용한 버그"가 생기기 쉬운 데이터셋이라,
아래 다섯 가지 함정을 여기서 한 번에 막습니다. (근거: FACTS.md 4 / 4a)

1) `<image N>` 마커는 **정수 N이 가리키는 image_N 컬럼**에 대응합니다(FACTS 4a).
   등장 순서대로 이미지를 왼쪽부터 소비하면 안 됩니다. validation_Math_19의 마커
   순서는 [1, 2, 1, 1, 2]로 같은 이미지를 네 번 참조하므로, 순차 소비 방식은
   이 문항을 조용히 망가뜨립니다.
2) 마커는 `question`뿐 아니라 `options` 문자열 안에도 있습니다. 900행 중 13행은
   마커가 options에만 있고(예: validation_Biology_24), options 안에 마커가 있는
   행은 전부 16행입니다. 그래서 두 필드를 **모두** 훑습니다.
3) 참조되지 않은 "고아(orphan) 이미지"가 4행에 들어 있습니다
   (validation_Agriculture_26, validation_Materials_15, validation_Pharmacy_4,
   validation_Pharmacy_22). null이 아닌 이미지 컬럼을 전부 넘기면 비전 토큰 수가
   달라지고 정답까지 바뀔 수 있으므로 **참조된 이미지만** 넘깁니다.
4) `options`와 `img_type`은 JSON이 아니라 파이썬 repr 문자열입니다(FACTS 4).
   작은따옴표 때문에 `json.loads`는 예외를 냅니다. 반드시 `ast.literal_eval`을 씁니다.
5) MMMU에는 "all" config가 없고 **과목별 config 30개**만 있습니다(FACTS 4).
   따라서 30번 로드해서 이어 붙입니다. 과목별 경과 시간 측정이 자연스러워지는
   이유도 바로 이 구조입니다.

표본 순서는 (과목 알파벳순, id 뒤 정수 오름차순)으로 완전히 고정합니다.
공식 MMMU 파서가 파싱 실패 시 `random.choice`로 찍기 때문에 최종 점수가 표본
순서에 의존합니다(FACTS 4c). 순서가 흔들리면 재현이 불가능해집니다.

단독 실행 시 자체 점검을 수행합니다.

    python src/mmmu_data.py --data-path MMMU/MMMU
    python src/mmmu_data.py --data-path /workspace/data/MMMU
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------------------
# 상수
# --------------------------------------------------------------------------------------

#: MMMU 공식 6개 카테고리 -> 과목 목록. mmmu/utils/data_utils.py의
#: DOMAIN_CAT2SUB_CAT를 그대로 옮긴 것입니다(FACTS 4b). 삽입 순서가 곧 보고서 표 순서입니다.
DOMAIN_CAT2SUB_CAT: dict[str, list[str]] = {
    "Art and Design": ["Art", "Art_Theory", "Design", "Music"],
    "Business": ["Accounting", "Economics", "Finance", "Manage", "Marketing"],
    "Science": ["Biology", "Chemistry", "Geography", "Math", "Physics"],
    "Health and Medicine": [
        "Basic_Medical_Science",
        "Clinical_Medicine",
        "Diagnostics_and_Laboratory_Medicine",
        "Pharmacy",
        "Public_Health",
    ],
    "Humanities and Social Science": ["History", "Literature", "Sociology", "Psychology"],
    "Tech and Engineering": [
        "Agriculture",
        "Architecture_and_Engineering",
        "Computer_Science",
        "Electronics",
        "Energy_and_Power",
        "Materials",
        "Mechanical_Engineering",
    ],
}

#: FACTS 4b 순서의 6개 카테고리.
CATEGORY_ORDER: list[str] = list(DOMAIN_CAT2SUB_CAT.keys())

#: 과목 -> 카테고리 역매핑.
SUB2DOMAIN: dict[str, str] = {
    subject: category for category, subjects in DOMAIN_CAT2SUB_CAT.items() for subject in subjects
}

#: HF config 이름 30개(알파벳순). 정렬 키로도 쓰이므로 순서가 고정되어야 합니다.
SUBJECTS: list[str] = sorted(SUB2DOMAIN.keys())

# assert는 python -O에서 사라지므로 검증은 명시적으로 raise 합니다.
if len(SUBJECTS) != 30:
    raise RuntimeError(
        f"과목 수가 30이 아닙니다({len(SUBJECTS)}개). FACTS 4b의 DOMAIN_CAT2SUB_CAT가 손상되었습니다."
    )

#: 스키마상 존재하는 이미지 컬럼 수(image_1 .. image_7). validation에서 image_6/7은 항상 null이고
#: 실제 최대 참조 인덱스는 5이지만(FACTS 4), 컬럼 자체는 7개이므로 7로 둡니다.
MAX_IMAGE_COLUMNS: int = 7

#: `<image N>` 마커 정규식. "<image 1>"이 표준 표기이지만 공백이 없는 "<image1>"도
#: 놓치지 않도록 \s* 로 느슨하게 잡습니다. 마커를 하나라도 놓치면 이미지가 조용히
#: 빠지는 최악의 버그가 되므로, 여기서는 관용적인 쪽이 안전합니다.
IMAGE_MARKER_PATTERN: str = r"<\s*image\s*(\d+)\s*>"
IMAGE_MARKER_RE: re.Pattern[str] = re.compile(IMAGE_MARKER_PATTERN, re.IGNORECASE)

#: HF의 question_type 값 정규화 표. 계약(INTERFACES.md)상 최종 값은 두 가지뿐입니다.
#: MMMU 레포의 answer_dict_val.json은 open을 'short-answer'라고 부르므로(FACTS 4)
#: 별칭도 받아 줍니다.
_QUESTION_TYPE_ALIASES: dict[str, str] = {
    "multiple-choice": "multiple-choice",
    "multiple_choice": "multiple-choice",
    "multiplechoice": "multiple-choice",
    "mc": "multiple-choice",
    "open": "open",
    "open-ended": "open",
    "open_ended": "open",
    "short-answer": "open",
    "short_answer": "open",
}

#: FACTS 4 / 4a에서 검증된 validation 스플릿 기대값. 자체 점검과 경고 기준으로 씁니다.
EXPECTED_VALIDATION: dict[str, Any] = {
    "n_total": 900,
    "n_per_subject": 30,
    "n_multiple_choice": 847,
    "n_open": 53,
    "image_count_dist": {1: 857, 2: 24, 3: 5, 4: 8, 5: 6},
    "max_image_index": 5,
    "n_rows_markers_in_options": 16,
    "n_rows_markers_only_in_options": 13,
    "orphan_image_rows": [
        "validation_Agriculture_26",
        "validation_Materials_15",
        "validation_Pharmacy_4",
        "validation_Pharmacy_22",
    ],
    "category_n": {
        "Art and Design": 120,
        "Business": 150,
        "Science": 150,
        "Health and Medicine": 150,
        "Humanities and Social Science": 120,
        "Tech and Engineering": 210,
    },
    # 마커가 같은 이미지를 반복 참조하는 대표 사례(FACTS 4a).
    "marker_sequence_math_19": [1, 2, 1, 1, 2],
}

#: MMMU/MMMU의 고정 리비전. "main"은 가변 포인터이고 데이터 파일이 2026-02-12,
#: 2026-04-21, 2026-07-10에 실제로 바뀌었으므로(FACTS 6) 문자열 "MMMU/MMMU"만으로는
#: 재현 가능한 식별자가 되지 못합니다. 기본 리비전을 여기 박아 둡니다.
DEFAULT_DATASET_REVISION: str = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"

#: 기본 HF 데이터셋 repo id.
DEFAULT_DATASET_REPO: str = "MMMU/MMMU"

#: 로컬 디렉터리에서 과목별 parquet을 찾을 때 시도하는 glob 패턴.
#: 첫 번째 패턴이 `hf download MMMU/MMMU --repo-type dataset --include "*/validation-*.parquet"`
#: 로 내려받은 표준 레이아웃입니다(FACTS 4: validation만 내려받으면 약 3GB 절약).
_PARQUET_PATTERNS: tuple[str, ...] = (
    "{subject}/{split}-*.parquet",
    "{subject}/{split}*.parquet",
    "{subject}/*{split}*.parquet",
    "data/{subject}/{split}-*.parquet",
    "data/{subject}/{split}*.parquet",
    "{split}/{subject}-*.parquet",
    "{split}/{subject}*.parquet",
    "{subject}_{split}*.parquet",
    "{split}_{subject}*.parquet",
)

_warned_once: set[str] = set()


def _warn(message: str) -> None:
    """경고를 stderr로 크게 출력합니다. 조용히 삼키지 않는 것이 이 프로젝트의 원칙입니다."""
    print(f"[mmmu_data] 경고: {message}", file=sys.stderr, flush=True)


def _warn_once(key: str, message: str) -> None:
    """같은 종류의 경고가 900행 동안 반복되는 것을 막습니다."""
    if key in _warned_once:
        return
    _warned_once.add(key)
    _warn(message)


# --------------------------------------------------------------------------------------
# 표본 자료구조
# --------------------------------------------------------------------------------------


@dataclass
class MMMUSample:
    """MMMU 한 문항. INTERFACES.md의 필드 정의를 그대로 따릅니다.

    주의: `question`은 **가공하지 않은 원문**이며 `<image N>` 마커가 그대로 남아 있습니다.
    마커를 프롬프트 안에서 이미지 블록으로 바꿔 끼우는 일은 mmmu_prompt.build_messages가
    담당합니다. 여기서 마커를 지우면 이미지와 텍스트의 배치 정보가 사라집니다.
    """

    id: str
    subject: str
    category: str
    question: str
    options: list[str]
    options_raw: str
    answer: str
    question_type: str
    images: list
    image_indices: list[int]
    subfield: str
    topic_difficulty: str
    # 아래 두 필드는 INTERFACES.md 계약에 없는 추가 정보입니다. 기본값이 있으므로
    # 계약대로 만든 호출자는 전혀 영향을 받지 않습니다.
    #  - img_type: 과제 요구대로 ast.literal_eval로 파싱해 둔 이미지 유형 목록(FACTS 4).
    #  - orphan_image_indices: 존재하지만 참조되지 않아 **의도적으로 버린** 이미지의 인덱스.
    #    고아 이미지 규칙이 실제로 동작했는지 자체 점검에서 확인하기 위한 증거입니다.
    img_type: list[str] = field(default_factory=list)
    orphan_image_indices: list[int] = field(default_factory=list)

    @property
    def n_images(self) -> int:
        return len(self.images)

    def __repr__(self) -> str:  # PIL 객체가 통째로 찍히면 로그를 읽을 수 없습니다.
        return (
            f"MMMUSample(id={self.id!r}, subject={self.subject!r}, "
            f"question_type={self.question_type!r}, n_options={len(self.options)}, "
            f"image_indices={self.image_indices}, answer={self.answer!r})"
        )


# --------------------------------------------------------------------------------------
# 마커 처리 — FACTS 4a
# --------------------------------------------------------------------------------------


def marker_sequence(question: str, options_raw: str) -> list[int]:
    """`question` 다음 `options`를 훑어 `<image N>`의 N을 **등장 순서대로** 돌려줍니다.

    중복을 제거하지 않습니다. validation_Math_19에서 [1, 2, 1, 1, 2]가 나오는 것을
    눈으로 확인하기 위한 진단용 함수입니다(FACTS 4a). 이미지 선택에는 쓰지 않습니다.
    """
    text = f"{question or ''}\n{options_raw or ''}"
    return [int(m.group(1)) for m in IMAGE_MARKER_RE.finditer(text)]


def referenced_image_indices(question: str, options_raw: str) -> list[int]:
    """`question`과 `options` 문자열 **양쪽**에서 `<image N>`을 찾아 N을 정렬·중복 제거해 돌려줍니다.

    options를 빼먹으면 900행 중 13행(마커가 options에만 있는 행)의 이미지가 통째로
    사라집니다(FACTS 4a). options_raw는 파싱 전 원문 문자열을 그대로 넣으면 됩니다.
    따로 파싱할 필요 없이 repr 문자열 안의 마커도 정규식에 그대로 잡힙니다.
    """
    return sorted(set(marker_sequence(question, options_raw)))


def subject_from_id(sample_id: str) -> str:
    """`validation_Math_1` -> `Math`. 스플릿 접두사와 끝의 `_<번호>`를 떼어 냅니다(FACTS 4b)."""
    if not isinstance(sample_id, str) or not sample_id:
        raise ValueError(f"id가 비어 있거나 문자열이 아닙니다: {sample_id!r}")
    head, sep, tail = sample_id.rpartition("_")
    if not sep or not tail.isdigit():
        raise ValueError(
            f"MMMU id 형식이 아닙니다: {sample_id!r} (기대 형식: '<split>_<Subject>_<번호>')"
        )
    # 스플릿 이름(validation/dev/test)에는 '_'가 없으므로 첫 '_'에서 한 번만 자릅니다.
    _split_name, sep2, subject = head.partition("_")
    if not sep2 or not subject:
        raise ValueError(
            f"MMMU id에서 과목을 떼어 낼 수 없습니다: {sample_id!r} "
            "(기대 형식: '<split>_<Subject>_<번호>')"
        )
    if subject not in SUB2DOMAIN:
        raise ValueError(
            f"알 수 없는 과목 {subject!r} (id={sample_id!r}). FACTS 4b의 30과목에 없습니다. "
            "데이터셋 리비전이 바뀌었는지 확인하십시오."
        )
    return subject


def parse_repr_list(raw: Any, field_name: str, sample_id: str = "?") -> list[str]:
    """파이썬 repr 문자열(`"['a', 'b']"`)을 리스트로 바꿉니다.

    `options`와 `img_type`은 JSON이 아니므로 `json.loads`는 작은따옴표에서 예외를 냅니다
    (FACTS 4). 반드시 `ast.literal_eval`을 씁니다. 개방형 문항의 options는 `'[]'`입니다.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):  # 이미 파싱된 상태로 들어온 경우
        return [x if isinstance(x, str) else str(x) for x in raw]
    text = str(raw).strip()
    if text == "":
        return []
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise ValueError(
            f"[{sample_id}] {field_name} 필드를 ast.literal_eval로 파싱할 수 없습니다: {text!r}"
        ) from exc
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        # 원소가 문자열이 아닐 경우에만 str()로 맞춥니다(프롬프트에 그대로 들어갈 값입니다).
        return [x if isinstance(x, str) else str(x) for x in value]
    raise ValueError(
        f"[{sample_id}] {field_name} 필드가 리스트가 아닙니다: {type(value).__name__} / {text!r}"
    )


def normalize_question_type(raw: Any, sample_id: str = "?") -> str:
    """question_type을 'multiple-choice' 또는 'open' 으로 정규화합니다."""
    text = str(raw or "").strip().lower()
    if text not in _QUESTION_TYPE_ALIASES:
        raise ValueError(
            f"[{sample_id}] 알 수 없는 question_type {raw!r}. "
            "'multiple-choice' 또는 'open'이어야 합니다(FACTS 4)."
        )
    normalized = _QUESTION_TYPE_ALIASES[text]
    if text != normalized:
        _warn_once(
            f"qtype:{text}",
            f"question_type {text!r}를 {normalized!r}로 정규화했습니다(예: {sample_id}).",
        )
    return normalized


# --------------------------------------------------------------------------------------
# 의존성 지연 임포트 — 이 모듈을 import하는 것만으로 datasets/PIL가 필요해지지 않게 합니다.
# --------------------------------------------------------------------------------------


def _import_datasets():
    try:
        import datasets as hfds  # noqa: PLC0415 (의도적인 지연 임포트)
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "datasets 패키지가 필요합니다. STACK A 기준: pip install datasets==4.0.0 "
            "(FACTS 5). 주의: datasets 4.0.0부터 trust_remote_code 인자가 제거되었으므로 "
            "절대 넘기지 마십시오."
        ) from exc
    return hfds


def _import_pil():
    try:
        from PIL import Image as PILImage  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "pillow 패키지가 필요합니다. STACK A 기준: pip install pillow==11.3.0 (FACTS 5)."
        ) from exc
    return PILImage


# --------------------------------------------------------------------------------------
# 이미지 디코딩
# --------------------------------------------------------------------------------------


def _image_payload_present(value: Any) -> bool:
    """이미지 컬럼 값이 실제 이미지를 담고 있는지(= null이 아닌지) 판정합니다."""
    if value is None:
        return False
    if isinstance(value, dict):
        return bool(value.get("bytes")) or bool(value.get("path"))
    if isinstance(value, (bytes, bytearray)):
        return len(value) > 0
    # 이미 디코딩된 PIL 객체
    return hasattr(value, "size") and hasattr(value, "convert")


def _decode_image(value: Any, sample_id: str, column: str):
    """이미지 컬럼 값(struct<bytes,path> 또는 PIL 객체)을 RGB PIL 이미지로 만듭니다.

    RGB 변환을 여기서 해 두는 이유: Qwen2VLImageProcessor의 do_convert_rgb 기본값이 True라
    어차피 변환되지만, 팔레트/RGBA/CMYK 이미지의 처리 시점이 백엔드(vLLM/transformers)에
    따라 달라지지 않도록 입력 단계에서 고정해 비전 토큰 수를 결정적으로 만듭니다(FACTS 1).
    """
    PILImage = _import_pil()
    if not _image_payload_present(value):
        raise ValueError(
            f"[{sample_id}] {column}이 null인데 `<image N>` 마커가 이 이미지를 참조합니다. "
            "FACTS 4a에서 '참조된 이미지가 null인 경우는 없음'이 900행 전체에 대해 검증되었으므로, "
            "데이터가 손상되었거나 리비전이 다릅니다."
        )
    if hasattr(value, "convert") and hasattr(value, "size"):
        image = value
    elif isinstance(value, dict):
        data = value.get("bytes")
        path = value.get("path")
        if data:
            image = PILImage.open(io.BytesIO(data))
        else:
            image = PILImage.open(path)
    elif isinstance(value, (bytes, bytearray)):
        image = PILImage.open(io.BytesIO(bytes(value)))
    else:
        raise TypeError(
            f"[{sample_id}] {column}의 형식을 해석할 수 없습니다: {type(value).__name__}"
        )
    image.load()  # BytesIO가 회수되기 전에 픽셀을 메모리로 올립니다.
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image


def _decode_off(ds, hfds):
    """이미지 컬럼을 decode=False로 바꿉니다.

    이렇게 하면 행을 읽을 때 PIL 디코딩이 일어나지 않으므로, **참조된 이미지만** 우리가
    직접 디코딩할 수 있습니다. 고아 이미지(FACTS 4a의 4행)를 디코딩하는 낭비가 사라지고
    null 판정도 바이트 수준에서 정확해집니다.
    """
    for i in range(1, MAX_IMAGE_COLUMNS + 1):
        column = f"image_{i}"
        if column not in ds.column_names:
            continue
        try:
            ds = ds.cast_column(column, hfds.Image(decode=False))
        except Exception as exc:  # noqa: BLE001 - 캐스팅 실패는 치명적이지 않습니다.
            _warn_once(
                f"cast:{column}",
                f"{column}을 decode=False로 캐스팅하지 못했습니다({exc}). "
                "디코딩된 PIL 값을 그대로 처리합니다(동작은 같고 메모리만 더 씁니다).",
            )
    return ds


# --------------------------------------------------------------------------------------
# 로컬 경로 해석
# --------------------------------------------------------------------------------------


def _is_save_to_disk_dir(path: Path) -> bool:
    """`Dataset.save_to_disk` / `DatasetDict.save_to_disk`로 저장된 디렉터리인지 판정."""
    return (path / "dataset_dict.json").is_file() or (path / "state.json").is_file()


def _resolve_snapshot_root(root: Path, revision: str | None) -> Path:
    """HF 허브 캐시 디렉터리를 가리킨 경우 실제 스냅샷 디렉터리로 한 단계 내려갑니다.

    학생이 `~/.cache/huggingface/hub/datasets--MMMU--MMMU`를 --data-path로 넘기는 일이
    흔하므로, snapshots/<sha> 까지 자동으로 내려가 줍니다.
    """
    snapshots = root / "snapshots"
    if not snapshots.is_dir():
        return root
    children = sorted(p for p in snapshots.iterdir() if p.is_dir())
    if not children:
        raise FileNotFoundError(f"{snapshots} 안에 스냅샷 디렉터리가 없습니다.")
    if revision:
        for child in children:
            if child.name == revision or child.name.startswith(revision) or revision.startswith(child.name):
                return child
    if len(children) == 1:
        return children[0]
    raise FileNotFoundError(
        f"{snapshots} 안에 스냅샷이 여러 개 있습니다({[c.name for c in children]}). "
        "--dataset-revision으로 어느 것을 쓸지 지정하거나, 스냅샷 디렉터리를 직접 --data-path로 넘기십시오."
    )


def _find_local_subject_files(root: Path, subject: str, split: str) -> list[Path]:
    """과목 하나에 해당하는 parquet 파일 목록을 찾습니다(없으면 빈 리스트)."""
    for pattern in _PARQUET_PATTERNS:
        globbed = sorted(root.glob(pattern.format(subject=subject, split=split)))
        files = [p for p in globbed if p.is_file() and p.suffix == ".parquet"]
        if files:
            return files
    return []


def _pick_split(obj, split: str, where: str, hfds):
    """load_from_disk 결과(Dataset 또는 DatasetDict)에서 원하는 스플릿을 꺼냅니다."""
    if isinstance(obj, hfds.DatasetDict):
        if split not in obj:
            raise KeyError(
                f"{where}에 '{split}' 스플릿이 없습니다. 있는 스플릿: {sorted(obj.keys())}"
            )
        return obj[split]
    return obj


def _load_local_subject(hfds, root: Path, subject: str, split: str):
    """로컬 디렉터리에서 과목 하나를 읽습니다. 찾지 못하면 None."""
    subject_dir = root / subject
    if subject_dir.is_dir() and _is_save_to_disk_dir(subject_dir):
        return _pick_split(hfds.load_from_disk(str(subject_dir)), split, str(subject_dir), hfds)
    files = _find_local_subject_files(root, subject, split)
    if not files:
        return None
    # parquet 빌더는 스키마 메타데이터에서 Image 피처를 복원합니다.
    return hfds.load_dataset("parquet", data_files={split: [str(p) for p in files]}, split=split)


def _local_help_message(root: Path, split: str) -> str:
    tried = "\n  ".join(p.format(subject="<Subject>", split=split) for p in _PARQUET_PATTERNS)
    return (
        f"로컬 경로 {root} 에서 MMMU '{split}' 데이터를 찾지 못했습니다.\n"
        f"시도한 glob 패턴:\n  {tried}\n"
        "내려받는 방법(validation만 받으면 약 3GB를 절약합니다 — FACTS 4):\n"
        f"  hf download {DEFAULT_DATASET_REPO} --repo-type dataset "
        f"--revision {DEFAULT_DATASET_REVISION} "
        f'--include "*/{split}-*.parquet" --local-dir {root}\n'
        "또는 --data-path에 HF repo id를 그대로 넘기십시오(예: --data-path MMMU/MMMU)."
    )


# --------------------------------------------------------------------------------------
# 행 -> 표본 변환
# --------------------------------------------------------------------------------------

_REQUIRED_COLUMNS = ("id", "question", "options", "answer", "question_type")


def _row_to_sample(row: dict, subject: str, split: str) -> MMMUSample:
    sample_id = row["id"]
    options_raw = row.get("options")
    options_raw_str = "[]" if options_raw is None else str(options_raw)
    options = parse_repr_list(options_raw_str, "options", sample_id)
    img_type = parse_repr_list(row.get("img_type"), "img_type", sample_id)
    question = row.get("question")
    if question is None:
        raise ValueError(f"[{sample_id}] question이 null입니다.")
    question = str(question)
    question_type = normalize_question_type(row.get("question_type"), sample_id)

    if question_type == "multiple-choice" and len(options) < 2:
        raise ValueError(
            f"[{sample_id}] multiple-choice인데 선택지가 {len(options)}개입니다: {options_raw_str!r}"
        )
    if question_type == "open" and options:
        _warn_once(
            "open_with_options",
            f"[{sample_id}] open 문항에 선택지가 들어 있습니다. 선택지는 프롬프트에 넣지 않습니다"
            "(공식 construct_prompt도 question_type으로만 분기합니다).",
        )

    # 마커는 question과 options **양쪽**에서 찾습니다(FACTS 4a).
    indices = referenced_image_indices(question, options_raw_str)

    images: list = []
    for n in indices:
        column = f"image_{n}"
        if column not in row:
            raise ValueError(
                f"[{sample_id}] `<image {n}>` 마커가 있는데 {column} 컬럼이 없습니다. "
                f"스키마상 이미지 컬럼은 image_1..image_{MAX_IMAGE_COLUMNS}입니다(FACTS 4)."
            )
        # 마커의 정수 N -> 컬럼 image_N. 등장 순서(left-to-right)로 소비하지 않습니다.
        images.append(_decode_image(row[column], sample_id, column))

    # 참조되지 않은 이미지는 '있어도' 넘기지 않습니다(FACTS 4a의 고아 이미지 4행).
    orphans = [
        n
        for n in range(1, MAX_IMAGE_COLUMNS + 1)
        if n not in indices and _image_payload_present(row.get(f"image_{n}"))
    ]

    answer = row.get("answer")
    # 개방형 정답 3개는 parquet 안에서 문자열화된 리스트입니다(FACTS 4c).
    # 여기서 풀어 버리면 안 됩니다. 채점 규칙(eval_open)이 mmmu_parser의 책임이므로
    # 정답은 원문 문자열 그대로 보존합니다.
    return MMMUSample(
        id=sample_id,
        subject=subject,
        category=SUB2DOMAIN[subject],
        question=question,
        options=options,
        options_raw=options_raw_str,
        answer="" if answer is None else str(answer),
        question_type=question_type,
        images=images,
        image_indices=indices,
        subfield=str(row.get("subfield") or ""),
        topic_difficulty=str(row.get("topic_difficulty") or ""),
        img_type=img_type,
        orphan_image_indices=orphans,
    )


def _dataset_to_samples(ds, subject: str | None, split: str, allowed: Sequence[str], hfds) -> list[MMMUSample]:
    missing = [c for c in _REQUIRED_COLUMNS if c not in ds.column_names]
    if missing:
        raise ValueError(
            f"필수 컬럼이 없습니다: {missing}. 실제 컬럼: {ds.column_names} "
            "(FACTS 4의 16컬럼 스키마와 다릅니다)."
        )
    ds = _decode_off(ds, hfds)
    allowed_set = set(allowed)
    out: list[MMMUSample] = []
    for row in ds:
        sample_id = row["id"]
        subject_in_id = subject_from_id(sample_id)
        if subject is None:
            # 과목 구분 없이 하나로 저장된 데이터셋: id에서 과목을 읽어 필터링합니다.
            if subject_in_id not in allowed_set:
                continue
            resolved = subject_in_id
        else:
            if subject_in_id != subject:
                raise ValueError(
                    f"config '{subject}'에서 읽은 행의 id가 {sample_id!r}로 과목이 다릅니다"
                    f"(id 기준 {subject_in_id}). 파일이 섞였습니다."
                )
            resolved = subject
        if not sample_id.startswith(f"{split}_"):
            _warn_once(
                "split_prefix",
                f"id {sample_id!r}의 접두사가 '{split}_'가 아닙니다. "
                "다른 스플릿 파일을 읽고 있는지 확인하십시오.",
            )
        out.append(_row_to_sample(row, resolved, split))
    return out


def _normalize_subjects(subjects: Any) -> list[str]:
    """subjects 인자를 정규화합니다(None -> 전체 30과목). 쉼표 문자열도 받습니다."""
    if subjects is None:
        return list(SUBJECTS)
    if isinstance(subjects, str):
        requested = [s.strip() for s in subjects.split(",") if s.strip()]
    else:
        requested = [str(s).strip() for s in subjects if str(s).strip()]
    if not requested:
        raise ValueError("subjects가 비어 있습니다. 전체를 쓰려면 None을 넘기십시오.")
    unknown = [s for s in requested if s not in SUB2DOMAIN]
    if unknown:
        raise ValueError(
            f"알 수 없는 과목: {unknown}\n사용 가능한 30과목: {', '.join(SUBJECTS)}"
        )
    # 중복 제거 후 SUBJECTS 순서로 고정 — 호출자가 순서를 흔들어도 결과는 같아야 합니다.
    return [s for s in SUBJECTS if s in set(requested)]


def _sort_key(sample: MMMUSample) -> tuple[int, int]:
    """(과목 알파벳순 인덱스, id 뒤의 정수). 표본 순서를 완전히 결정적으로 만듭니다(FACTS 4c)."""
    tail = sample.id.rsplit("_", 1)[-1]
    if not tail.isdigit():
        raise ValueError(f"id {sample.id!r}의 끝이 정수가 아니어서 정렬할 수 없습니다.")
    return (SUBJECTS.index(sample.subject), int(tail))


def _sanity_check(samples: list[MMMUSample], split: str, subjects: Sequence[str]) -> None:
    if not samples:
        raise RuntimeError(
            "표본이 0개입니다. --data-path / --split / --subjects 를 확인하십시오."
        )
    ids = [s.id for s in samples]
    duplicates = [sid for sid, c in Counter(ids).items() if c > 1]
    if duplicates:
        raise RuntimeError(
            f"중복 id가 {len(duplicates)}개 있습니다(예: {duplicates[:5]}). "
            "같은 parquet을 두 번 읽었을 가능성이 큽니다."
        )
    per_subject = Counter(s.subject for s in samples)
    if split == "validation":
        expected_each = EXPECTED_VALIDATION["n_per_subject"]
        odd = {s: per_subject.get(s, 0) for s in subjects if per_subject.get(s, 0) != expected_each}
        if odd:
            _warn(
                f"validation은 과목당 {expected_each}개여야 하는데 다른 과목이 있습니다: {odd} "
                "(FACTS 4). 데이터셋 리비전이 다를 수 있습니다."
            )
        expected_total = expected_each * len(subjects)
        if len(samples) != expected_total:
            _warn(f"총 표본 수 {len(samples)}개 != 기대값 {expected_total}개.")
    # 정답 문자가 선택지 범위를 벗어난 객관식은 채점에서 무조건 오답이 되므로 미리 알립니다.
    import string as _string

    bad_gold = [
        s.id
        for s in samples
        if s.question_type == "multiple-choice"
        and s.answer.strip() not in set(_string.ascii_uppercase[: len(s.options)])
    ]
    if bad_gold:
        _warn(
            f"정답 문자가 선택지 범위를 벗어난 객관식이 {len(bad_gold)}개 있습니다"
            f"(예: {bad_gold[:5]}). 채점에서 전부 오답 처리됩니다."
        )


# --------------------------------------------------------------------------------------
# 공개 로더
# --------------------------------------------------------------------------------------


def load_mmmu(
    data_path: str | os.PathLike,
    split: str = "validation",
    revision: str | None = None,
    subjects: Iterable[str] | str | None = None,
) -> list[MMMUSample]:
    """MMMU를 읽어 결정적 순서의 `MMMUSample` 리스트로 돌려줍니다.

    Args:
        data_path: **존재하는 로컬 디렉터리**면 로컬에서(load_from_disk 또는 parquet) 읽고,
            그렇지 않으면 HF repo id로 취급합니다(예: "MMMU/MMMU").
            교수님 요구사항이 "MMMU 데이터 경로를 입력으로 받는 스크립트"이므로 두 경우를
            모두 지원합니다(FACTS 0).
        split: 기본 "validation"(900개).
        revision: HF repo id를 쓸 때 고정할 커밋 sha. "main"은 가변 포인터이고 MMMU의
            데이터 파일은 67.4가 공개된 **이후** 실제로 세 번 바뀌었으므로(FACTS 6)
            재현 가능한 실행에서는 반드시 지정해야 합니다.
        subjects: 과목 필터(리스트 또는 쉼표 문자열). None이면 30과목 전체.

    Returns:
        (과목 알파벳순, id 번호순)으로 정렬된 표본 리스트.

    메모리: 참조된 이미지를 모두 PIL로 올려 둡니다(900문항 대략 1.5~3GB). 노트북에서
    시험해 볼 때는 --subjects 나 --limit 으로 줄이십시오.
    """
    # 값싼 인자 검증을 무거운 datasets 임포트보다 먼저 끝냅니다.
    subject_list = _normalize_subjects(subjects)
    root = Path(str(data_path)).expanduser()
    samples: list[MMMUSample] = []

    if root.is_file():
        # 파일 하나를 넘기면 과목 30개를 모을 수 없습니다. 조용히 HF repo id로 해석해
        # 엉뚱한 오류를 내지 않도록 여기서 분명하게 실패합니다.
        raise ValueError(
            f"--data-path 에 파일이 아니라 디렉터리를 넘기십시오: {root}\n"
            "MMMU는 과목별 config 30개로 나뉘어 있어(FACTS 4) 과목 디렉터리들을 담은 "
            "상위 디렉터리가 필요합니다. 예: /workspace/data/MMMU "
            f"(그 안에 {SUBJECTS[0]}/{split}-00000-of-00001.parquet 형태)"
        )

    hfds = _import_datasets()

    if root.is_dir():
        root = _resolve_snapshot_root(root, revision)
        if revision:
            _warn(
                f"로컬 경로({root})를 읽으므로 revision={revision}은 검증되지 않습니다. "
                "리비전 확인은 `hf cache verify ... --revision <sha>`로 하십시오(FACTS 5)."
            )
        if _is_save_to_disk_dir(root):
            # 과목 구분 없이 한 덩어리로 저장된 경우: id에서 과목을 복원합니다.
            ds = _pick_split(hfds.load_from_disk(str(root)), split, str(root), hfds)
            samples.extend(_dataset_to_samples(ds, None, split, subject_list, hfds))
        else:
            loaded: dict[str, Any] = {}
            for subject in subject_list:
                ds = _load_local_subject(hfds, root, subject, split)
                if ds is not None:
                    loaded[subject] = ds
            if not loaded:
                raise FileNotFoundError(_local_help_message(root, split))
            not_found = [s for s in subject_list if s not in loaded]
            if not_found:
                # 일부 과목만 읽히면 점수가 조용히 틀어집니다. 명시적으로 실패합니다.
                raise FileNotFoundError(
                    f"{len(not_found)}개 과목의 '{split}' 파일을 찾지 못했습니다: {not_found}\n"
                    "일부만 평가하면 전체 정확도가 조용히 왜곡되므로 중단합니다. "
                    "의도한 것이라면 --subjects 로 명시하십시오.\n" + _local_help_message(root, split)
                )
            for subject in subject_list:  # 순서 고정
                samples.extend(_dataset_to_samples(loaded[subject], subject, split, subject_list, hfds))
    else:
        repo_id = str(data_path)
        for subject in subject_list:
            # MMMU에는 "all" config가 없으므로 과목별로 30번 로드합니다(FACTS 4).
            # MMMU/MMMU는 스크립트 없는 parquet 레포이므로 trust_remote_code를 넘기면
            # datasets>=4.0.0에서 TypeError가 납니다(FACTS 4).
            ds = hfds.load_dataset(repo_id, subject, split=split, revision=revision)
            samples.extend(_dataset_to_samples(ds, subject, split, subject_list, hfds))

    samples.sort(key=_sort_key)
    _sanity_check(samples, split, subject_list)
    return samples


# --------------------------------------------------------------------------------------
# 자체 점검 (python src/mmmu_data.py --data-path ...)
# --------------------------------------------------------------------------------------


def _display_width(text: str) -> int:
    """한글/전각 문자를 2칸으로 세어 표 정렬을 맞춥니다(터미널 가독성 목적)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _fmt_check(label: str, measured: Any, expected: Any, mark: str) -> str:
    return f"  {_pad(label, 40)} 측정={measured}  기대={expected}  [{mark}]"


def _self_check(samples: list[MMMUSample], split: str, subjects: Sequence[str]) -> int:
    """FACTS 4 / 4a의 기대값과 실측값을 나란히 출력합니다. 반환값은 불일치 개수."""
    full_validation = split == "validation" and len(subjects) == len(SUBJECTS)
    exp = EXPECTED_VALIDATION
    lines: list[str] = []
    mismatches = 0

    def check(label: str, measured: Any, expected: Any, scaled: bool = True) -> None:
        """scaled=True인 항목은 기대값이 900행 전체 기준이므로, 부분 로드에서는
        불일치로 세지 않고 '참고'로만 표시합니다. 부분 로드에서 빨간 불이 뜨면
        학생이 진짜 문제를 구분할 수 없게 됩니다."""
        nonlocal mismatches
        counted = full_validation or not scaled
        if measured == expected:
            mark = "OK"
        elif counted:
            mismatches += 1
            mark = "불일치 <<<"
        else:
            mark = "참고(부분 로드)"
        lines.append(_fmt_check(label, measured, expected, mark))

    n_total = len(samples)
    dist = dict(sorted(Counter(s.n_images for s in samples).items()))
    n_mc = sum(1 for s in samples if s.question_type == "multiple-choice")
    n_open = sum(1 for s in samples if s.question_type == "open")
    in_options = [
        s for s in samples if referenced_image_indices("", s.options_raw)
    ]
    only_in_options = [
        s
        for s in in_options
        if not referenced_image_indices(s.question, "")
    ]
    orphan_rows = sorted(s.id for s in samples if s.orphan_image_indices)
    max_index = max((max(s.image_indices) for s in samples if s.image_indices), default=0)
    option_counts = dict(
        sorted(Counter(len(s.options) for s in samples if s.question_type == "multiple-choice").items())
    )
    n_not_four = sum(n for k, n in option_counts.items() if k != 4)

    print(f"\n=== mmmu_data 자체 점검 (split={split}, 과목 {len(subjects)}개) ===")
    if not full_validation:
        print(
            "  (주의: validation 전체가 아니므로 아래 '기대' 값은 FACTS 4/4a의 900행 기준값이며"
            " 불일치가 정상입니다.)"
        )
    check("총 행 수", n_total, exp["n_total"])
    check("이미지 개수 분포 {n장: 행수}", dist, exp["image_count_dist"])
    check("객관식(multiple-choice) 행 수", n_mc, exp["n_multiple_choice"])
    check("개방형(open) 행 수", n_open, exp["n_open"])
    check("options에 마커가 있는 행 수", len(in_options), exp["n_rows_markers_in_options"])
    check(
        "options에만 마커가 있는 행 수", len(only_in_options), exp["n_rows_markers_only_in_options"]
    )
    check("참조된 최대 이미지 인덱스", max_index, exp["max_image_index"])
    check("고아 이미지 보유 행 수", len(orphan_rows), len(exp["orphan_image_rows"]))
    check("고아 이미지 보유 행 id", orphan_rows, sorted(exp["orphan_image_rows"]))

    by_category = Counter(s.category for s in samples)
    check(
        "카테고리별 행 수",
        {c: by_category.get(c, 0) for c in CATEGORY_ORDER},
        exp["category_n"],
    )

    math_19 = next((s for s in samples if s.id == "validation_Math_19"), None)
    if math_19 is not None:
        check(
            "validation_Math_19 마커 등장 순서",
            marker_sequence(math_19.question, math_19.options_raw),
            exp["marker_sequence_math_19"],
            scaled=False,
        )
        check("validation_Math_19 실제 전달 이미지 수", len(math_19.images), 2, scaled=False)

    for line in lines:
        print(line)

    print("\n  [참고] 선택지 개수 분포(객관식):", option_counts)
    print(
        f"  [참고] 선택지가 4개가 아닌 객관식 행: {n_not_four}개 "
        "— A~D 하드코딩 금지 근거(FACTS 4: 847행 중 241행)"
    )
    print(f"  [참고] 전체 전달 이미지 수: {sum(s.n_images for s in samples)}장")
    if only_in_options:
        preview = ", ".join(s.id for s in only_in_options[:5])
        print(f"  [참고] options에만 마커가 있는 행 예시: {preview}")
    if orphan_rows:
        detail = ", ".join(
            f"{s.id}{s.orphan_image_indices}" for s in samples if s.orphan_image_indices
        )
        print(f"  [참고] 버린 고아 이미지: {detail}")
    print(f"  [참고] 첫 표본: {samples[0].id} / 마지막 표본: {samples[-1].id}")

    if mismatches:
        print(
            f"\n  >>> 불일치 {mismatches}건. FACTS 4/4a 기준과 다릅니다. "
            "데이터 리비전(--dataset-revision)이나 로더 동작을 먼저 확인하십시오."
        )
    elif full_validation:
        print("\n  >>> 모든 항목이 FACTS 4/4a 기대값과 일치합니다.")
    else:
        print(
            "\n  >>> 부분 로드 기준으로 이상 없습니다. 제출용 점검은 과목 전체(900행)로 "
            "한 번 더 실행하십시오."
        )
    return mismatches


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MMMU 로더 자체 점검 — FACTS 4/4a의 기대값과 실측값을 비교합니다."
    )
    parser.add_argument(
        "--data-path",
        required=True,
        help="로컬 MMMU 디렉터리 또는 HF repo id(예: MMMU/MMMU)",
    )
    parser.add_argument("--split", default="validation")
    parser.add_argument(
        "--revision",
        default=None,
        help=f"HF 데이터셋 리비전. 재현성을 위해 {DEFAULT_DATASET_REVISION} 권장(FACTS 6).",
    )
    parser.add_argument("--subjects", default=None, help="쉼표로 구분한 과목 필터(선택)")
    args = parser.parse_args(argv)

    subject_list = _normalize_subjects(args.subjects)
    samples = load_mmmu(
        args.data_path, split=args.split, revision=args.revision, subjects=subject_list
    )
    mismatches = _self_check(samples, args.split, subject_list)
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(_main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MMMU 베이스라인 실행 결과를 제출용 Markdown 보고서로 변환하는 스크립트입니다.

이 스크립트는 `src/eval_mmmu.py` 가 만들어 놓은 실행 디렉터리(run dir) 하나를 읽어서
과제 명세(슬라이드 15)가 요구하는 항목을 빠짐없이 담은 Markdown 문서를 만듭니다.

  * 전체 성능 / 카테고리별 성능 / 과목별 성능 / 문제 유형별 성능
  * 총 소요 시간과 카테고리·과목별 소요 시간
  * 실험 환경(HW 인프라, 드라이버, 모든 도구 패키지 버전)
  * 공개 보고 성능(MMMU val 67.4)과의 비교 및 차이의 원인 분석

또한 팀원 4명의 결과를 한 표로 모으는 `--compare` 와, 두 실행의 예측을 직접 비교하여
점수 차이가 샘플링 노이즈인지 실제 버그인지 판정하는 `--diff` 를 제공합니다.

사용법:
    python src/report.py --run-dir outputs/RUN --out assignment/assignment1_results.md
    python src/report.py --run-dir outputs/RUN_ME --compare outputs/RUN_A outputs/RUN_B
    python src/report.py --diff outputs/RUN_A outputs/RUN_B

설계 원칙
---------
1. **표준 라이브러리만 사용합니다.** 이 스크립트는 GPU 가 없는 팀원 개인 노트북에서도
   돌아가야 하므로, torch 를 import 할 가능성이 있는 `src/capture_env.py`,
   `src/mmmu_data.py` 를 import 하지 않습니다. 그 대신 FACTS.md 4b 의 카테고리 표를
   이 파일 안에 그대로 복제해 두었습니다(두 곳이 달라지면 FACTS.md 4b 가 기준입니다).
2. **조용한 실패를 만들지 않습니다.** 파일이 없거나 키가 비면 "N/A" 로 표시하고
   경고를 stderr 로 내보내며, 보고서 본문의 "무결성 점검" 절에 그대로 남깁니다.
   예를 들어 멀티 이미지 문항 43개(FACTS 4b/4a 근거)가 누락되면 점검 표에서 바로 드러납니다.
3. **정확도는 correct/n 으로 다시 계산합니다.** metrics.json 의 `accuracy` 값이 비율(0.674)
   인지 퍼센트(67.4)인지 INTERFACES.md 에 명시되어 있지 않기 때문입니다. 저장된 값과
   재계산 값이 어긋나면 경고로 보고합니다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# ---------------------------------------------------------------------------
# 상수 — 모든 수치는 FACTS.md 에서 온 검증된 값입니다. 기억에 의존해 바꾸지 마십시오.
# ---------------------------------------------------------------------------

SCHEMA_NOTE = "report.py / MMMU baseline report generator v1"

#: 공개 보고 점수 (FACTS 0, FACTS 10 / metrics.json published_reference)
PUBLISHED_MMMU_VAL = 67.4
PUBLISHED_SOURCE = "Qwen3-VL technical report arXiv:2511.21631"

#: FACTS 4b — DOMAIN_CAT2SUB_CAT (mmmu/utils/data_utils.py). 순서까지 FACTS 4b 와 동일합니다.
CATEGORY_ORDER: list[str] = [
    "Art and Design",
    "Business",
    "Science",
    "Health and Medicine",
    "Humanities and Social Science",
    "Tech and Engineering",
]

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

#: FACTS 4b — 카테고리별 validation 표본 수. 120/150/150/150/120/210 이므로
#: 6개 카테고리 정확도의 단순 평균(macro)은 전체 정확도(micro)와 같아지지 않습니다.
EXPECTED_CATEGORY_N: dict[str, int] = {
    "Art and Design": 120,
    "Business": 150,
    "Science": 150,
    "Health and Medicine": 150,
    "Humanities and Social Science": 120,
    "Tech and Engineering": 210,
}

CATEGORY_KR: dict[str, str] = {
    "Art and Design": "예술·디자인",
    "Business": "경영·경제",
    "Science": "과학",
    "Health and Medicine": "보건·의학",
    "Humanities and Social Science": "인문·사회과학",
    "Tech and Engineering": "기술·공학",
}

#: 30개 과목의 한글 설명. 과목 키 자체는 HF config 이름이므로 절대 번역하지 않습니다.
SUBJECT_KR: dict[str, str] = {
    "Accounting": "회계",
    "Agriculture": "농학",
    "Architecture_and_Engineering": "건축·공학",
    "Art": "미술",
    "Art_Theory": "미술이론",
    "Basic_Medical_Science": "기초의학",
    "Biology": "생물학",
    "Chemistry": "화학",
    "Clinical_Medicine": "임상의학",
    "Computer_Science": "컴퓨터과학",
    "Design": "디자인",
    "Diagnostics_and_Laboratory_Medicine": "진단검사의학",
    "Economics": "경제학",
    "Electronics": "전자공학",
    "Energy_and_Power": "에너지·동력",
    "Finance": "재무",
    "Geography": "지리학",
    "History": "역사학",
    "Literature": "문학",
    "Manage": "경영관리",
    "Marketing": "마케팅",
    "Materials": "재료공학",
    "Math": "수학",
    "Mechanical_Engineering": "기계공학",
    "Music": "음악",
    "Pharmacy": "약학",
    "Physics": "물리학",
    "Psychology": "심리학",
    "Public_Health": "보건학",
    "Sociology": "사회학",
}

#: 과목 -> 카테고리 역인덱스
SUB2DOMAIN: dict[str, str] = {
    subject: category for category, subjects in DOMAIN_CAT2SUB_CAT.items() for subject in subjects
}

#: FACTS 4b 기준 알파벳 순 30개 과목
ALL_SUBJECTS: list[str] = sorted(SUB2DOMAIN)

#: FACTS 4 — validation 분할의 구성
EXPECTED_TOTAL_N = 900
EXPECTED_MC_N = 847
EXPECTED_OPEN_N = 53
EXPECTED_SUBJECT_N = 30  # 과목당 30문항이면서 과목 수도 30개입니다.
#: FACTS 4 이미지 개수 분포: 1장 857 / 2장 24 / 3장 5 / 4장 8 / 5장 6 -> 2장 이상이 43개
EXPECTED_MULTI_IMAGE_N = 24 + 5 + 8 + 6
EXPECTED_MAX_IMAGES = 5

#: FACTS 7 — n=900, p=0.674 에서의 통계량
ONE_SAMPLE_PP = 0.111
SE_PP_AT_N900 = 1.56
DIFF_CI95_PP = 4.33

#: INTERFACES.md 가 env.json packages 에 요구하는 패키지 목록(표시 순서 고정)
KEY_PACKAGES: list[str] = [
    "torch",
    "torchvision",
    "transformers",
    "tokenizers",
    "huggingface-hub",
    "accelerate",
    "safetensors",
    "vllm",
    "datasets",
    "pillow",
    "numpy",
    "qwen-vl-utils",
    "flash-attn",
]

KST = timezone(timedelta(hours=9))


class ReportError(Exception):
    """보고서를 만들 수 없는 치명적 오류. main() 에서 한국어 메시지로 출력합니다."""


# ---------------------------------------------------------------------------
# 낮은 수준 유틸리티
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽습니다. 깨진 JSON 은 조용히 넘기지 않고 예외로 올립니다."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ReportError(f"{path} 가 올바른 JSON 이 아닙니다: {exc}") from exc
    except OSError as exc:
        raise ReportError(f"{path} 를 읽을 수 없습니다: {exc}") from exc


def _read_jsonl(path: Path, warnings: list[str]) -> list[dict]:
    """predictions.jsonl 을 읽습니다.

    한 줄이 깨져 있어도 전체를 포기하지 않고 그 줄만 세어 경고로 남깁니다.
    (보고 도구는 손상된 입력에서도 최대한 정보를 보여 주는 편이 유용합니다.)
    """
    rows: list[dict] = []
    bad = 0
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                if bad <= 3:
                    warnings.append(f"{path} {lineno}번째 줄이 JSON 으로 파싱되지 않아 건너뛰었습니다.")
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                bad += 1
    if bad:
        warnings.append(f"{path}: 파싱 실패 {bad}줄 (무결성 점검 표 참조)")
    return rows


def _cell(value: Any) -> str:
    """Markdown 표 셀로 안전하게 변환합니다. `|` 와 줄바꿈이 표를 깨뜨립니다."""
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if not text:
        return "(빈 값)"
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>").replace("\r", "")


def md_table(headers: Sequence[Any], rows: Iterable[Sequence[Any]], align: Sequence[str] | None = None) -> list[str]:
    """GitHub Flavored Markdown 표를 줄 목록으로 만듭니다."""
    headers = [_cell(h) for h in headers]
    if align is None:
        align = ["l"] * len(headers)
    sep = []
    for i in range(len(headers)):
        a = align[i] if i < len(align) else "l"
        sep.append({"l": ":---", "r": "---:", "c": ":---:"}.get(a, ":---"))
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    empty = True
    for row in rows:
        empty = False
        cells = [_cell(c) for c in row]
        # 열 수가 모자라거나 넘치면 표가 깨지므로 맞춰 줍니다.
        if len(cells) < len(headers):
            cells += ["N/A"] * (len(headers) - len(cells))
        lines.append("| " + " | ".join(cells[: len(headers)]) + " |")
    if empty:
        lines.append("| " + " | ".join(["(데이터 없음)"] * len(headers)) + " |")
    return lines


def fmt_pct(value: float | None, digits: int = 2) -> str:
    """퍼센트 값을 포맷합니다."""
    if value is None:
        return "N/A"
    return f"{value:.{digits}f} %"


def fmt_pp(value: float | None, digits: int = 2) -> str:
    """퍼센트포인트 차이를 부호와 함께 포맷합니다."""
    if value is None:
        return "N/A"
    return f"{value:+.{digits}f} pp"


def fmt_sec(value: Any, digits: int = 1) -> str:
    """초 단위 시간을 사람이 읽을 수 있게 포맷합니다."""
    if value is None:
        return "N/A"
    try:
        x = float(value)
    except (TypeError, ValueError):
        return _cell(value)
    if x < 0:
        return f"{x:.{digits}f} 초 (음수 — 계측 오류)"
    if x < 60:
        return f"{x:.{digits}f} 초"
    total = int(round(x))
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        human = f"{hours}시간 {minutes}분 {seconds}초"
    else:
        human = f"{minutes}분 {seconds}초"
    return f"{x:.{digits}f} 초 ({human})"


def fmt_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return _cell(value)


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    """중첩 dict/list 를 (키경로, 문자열값) 목록으로 펼칩니다.

    env.json 의 하위 구조(os, python, run_config, notes 등)가 문자열일 수도 dict 일 수도
    있으므로, 어떤 모양이 와도 표로 그릴 수 있게 방어적으로 펼칩니다.
    """
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten(value, path))
    elif isinstance(obj, (list, tuple)):
        if not obj:
            out.append((prefix or "(값)", "(빈 목록)"))
        elif all(not isinstance(x, (dict, list, tuple)) for x in obj):
            out.append((prefix or "(값)", ", ".join(str(x) for x in obj)))
        else:
            for i, value in enumerate(obj):
                out.extend(_flatten(value, f"{prefix}[{i}]"))
    else:
        out.append((prefix or "(값)", "N/A" if obj is None else str(obj)))
    return out


def _as_list_of_lines(obj: Any) -> list[str]:
    """notes 필드처럼 str | list | dict 아무 모양으로 올 수 있는 값을 불릿 목록으로 만듭니다."""
    if obj is None:
        return []
    if isinstance(obj, str):
        return [line.strip() for line in obj.splitlines() if line.strip()]
    if isinstance(obj, (list, tuple)):
        lines: list[str] = []
        for item in obj:
            if isinstance(item, (dict, list, tuple)):
                lines.extend(f"{k}: {v}" for k, v in _flatten(item))
            elif item is not None and str(item).strip():
                lines.append(str(item).strip())
        return lines
    if isinstance(obj, dict):
        return [f"{k}: {v}" for k, v in _flatten(obj)]
    return [str(obj)]


def _is_dirty(value: Any) -> bool | None:
    """git.dirty 값을 bool 로 정규화합니다(문자열 "false" 도 같은 뜻으로 취급).

    값이 없으면 None 을 돌려주어 '판정 불가'와 '청결함'을 구분합니다.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("false", "0", "no", ""):
            return False
        if text in ("true", "1", "yes"):
            return True
        return None
    return bool(value)


def _percentile(sorted_values: Sequence[float], q: float) -> float | None:
    """가장 가까운 순위(nearest-rank) 방식 분위수. 빈 목록이면 None 입니다."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = max(1, min(len(sorted_values), int(math.ceil(q / 100.0 * len(sorted_values)))))
    return float(sorted_values[rank - 1])


# ---------------------------------------------------------------------------
# 실행 디렉터리 로딩
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Run:
    """하나의 실행 디렉터리에서 읽어 들인 모든 산출물."""

    path: Path
    metrics: dict
    timing: dict
    env: dict
    config: dict
    predictions: list[dict]
    warnings: list[str] = dataclasses.field(default_factory=list)
    has_predictions_file: bool = False

    # -- 편의 접근자 ---------------------------------------------------------
    @property
    def label(self) -> str:
        """보고서에서 이 실행을 가리키는 짧은 이름(디렉터리 이름)."""
        return self.path.name or str(self.path)

    @property
    def member(self) -> str:
        """팀원 이름. env.json 또는 config.json 에서 찾고, 없으면 디렉터리 이름을 씁니다."""
        candidates = ("member", "team_member", "member_name", "author", "runner", "name")
        containers: list[Any] = [
            self.env,
            self.env.get("run_config"),
            self.env.get("notes"),
            self.env.get("extra"),
            self.config,
            self.config.get("run_config") if isinstance(self.config.get("run_config"), dict) else None,
        ]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in candidates:
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return self.label


def load_run(run_dir: str | Path, *, need_predictions: bool = False) -> Run:
    """실행 디렉터리에서 metrics/timing/env/config/predictions 를 읽습니다.

    metrics.json 이 없으면 보고서를 만들 의미가 없으므로 즉시 실패합니다(명시적 실패).
    나머지 파일은 없으면 경고만 남기고 "N/A" 로 렌더링합니다.
    """
    path = Path(run_dir).expanduser()
    if not path.exists():
        raise ReportError(f"실행 디렉터리가 존재하지 않습니다: {path}")
    if not path.is_dir():
        raise ReportError(f"실행 디렉터리가 아닙니다(파일입니다): {path}")

    warnings: list[str] = []

    metrics_path = path / "metrics.json"
    try:
        metrics = _read_json(metrics_path)
    except FileNotFoundError:
        raise ReportError(
            f"{metrics_path} 가 없습니다. 먼저 `python src/eval_mmmu.py --data-path ... --out {path}` 를 완료하십시오."
        ) from None
    if not isinstance(metrics, dict):
        raise ReportError(f"{metrics_path} 의 최상위가 JSON 객체가 아닙니다.")

    def _optional(name: str) -> dict:
        try:
            obj = _read_json(path / name)
        except FileNotFoundError:
            warnings.append(f"{path / name} 가 없어 해당 절을 N/A 로 표시합니다.")
            return {}
        if not isinstance(obj, dict):
            warnings.append(f"{path / name} 의 최상위가 JSON 객체가 아니어서 무시합니다.")
            return {}
        return obj

    timing = _optional("timing.json")
    env = _optional("env.json")
    config = _optional("config.json")

    predictions: list[dict] = []
    predictions_path = path / "predictions.jsonl"
    has_predictions = predictions_path.exists()
    if has_predictions:
        predictions = _read_jsonl(predictions_path, warnings)
    elif need_predictions:
        raise ReportError(f"{predictions_path} 가 없어 예측 비교(--diff)를 할 수 없습니다.")
    else:
        warnings.append(f"{predictions_path} 가 없어 예측 단위 점검(멀티 이미지 문항 수 등)을 건너뜁니다.")

    return Run(
        path=path,
        metrics=metrics,
        timing=timing,
        env=env,
        config=config,
        predictions=predictions,
        warnings=warnings,
        has_predictions_file=has_predictions,
    )


def cfg_get(run: Run, *names: str, default: Any = None) -> Any:
    """config.json / env.json(run_config) 어디에 있든 설정 값을 찾아 줍니다.

    eval_mmmu.py 가 argparse 결과를 평평하게 저장할 수도, `args`/`run_config` 아래로
    넣을 수도 있으므로 후보 컨테이너를 순서대로 훑습니다.
    """
    containers: list[Any] = [
        run.config,
        run.config.get("args") if isinstance(run.config.get("args"), dict) else None,
        run.config.get("run_config") if isinstance(run.config.get("run_config"), dict) else None,
        run.env.get("run_config") if isinstance(run.env.get("run_config"), dict) else None,
        run.env.get("model") if isinstance(run.env.get("model"), dict) else None,
        run.env.get("dataset") if isinstance(run.env.get("dataset"), dict) else None,
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for name in names:
            for key in (name, name.replace("-", "_"), name.replace("_", "-")):
                if key in container and container[key] is not None:
                    return container[key]
    return default


def is_partial_run(run: Run) -> tuple[bool, str]:
    """부분 실행(--limit / --subjects)인지 판정합니다.

    부분 실행이면 900/847/53/43 같은 전수 기대치를 적용하면 안 되므로, 점검 표에서
    '해당 없음' 으로 처리하기 위해 먼저 판별합니다.
    """
    reasons = []
    limit = cfg_get(run, "limit")
    if isinstance(limit, (int, float)) and limit and int(limit) > 0:
        reasons.append(f"--limit {int(limit)}")
    subjects = cfg_get(run, "subjects")
    if subjects:
        if isinstance(subjects, str):
            count = len([s for s in subjects.split(",") if s.strip()])
        elif isinstance(subjects, (list, tuple)):
            count = len(subjects)
        else:
            count = 0
        if count and count < EXPECTED_SUBJECT_N:
            reasons.append(f"--subjects {count}개 과목")
    split = cfg_get(run, "split")
    if isinstance(split, str) and split and split != "validation":
        reasons.append(f"--split {split}")
    return (bool(reasons), ", ".join(reasons))


# ---------------------------------------------------------------------------
# 지표 계산
# ---------------------------------------------------------------------------


def stat_block(block: Any) -> tuple[int | None, int | None, float | None, str | None]:
    """{n, correct, accuracy} 블록에서 (n, correct, 정확도[%], 경고) 를 뽑습니다.

    정확도는 언제나 correct/n 으로 다시 계산합니다. metrics.json 의 accuracy 가 비율(0.674)
    인지 퍼센트(67.4)인지 규약에 없기 때문입니다. 저장값과 0.05 pp 이상 어긋나면
    집계 버그 신호이므로 경고 문자열을 함께 돌려줍니다.
    """
    if not isinstance(block, dict):
        return None, None, None, None
    n = block.get("n")
    correct = block.get("correct")
    try:
        n = int(n) if n is not None else None
    except (TypeError, ValueError):
        n = None
    try:
        correct = int(correct) if correct is not None else None
    except (TypeError, ValueError):
        correct = None

    recomputed: float | None = None
    if n is not None and correct is not None and n > 0:
        recomputed = 100.0 * correct / n
    elif n == 0:
        recomputed = None

    stored = block.get("accuracy")
    stored_pct: float | None = None
    if isinstance(stored, (int, float)):
        # 1.0 이하이면 비율로 간주합니다. MMMU 에서 100% 정답은 현실적으로 불가능하므로 안전합니다.
        stored_pct = float(stored) * 100.0 if float(stored) <= 1.0 else float(stored)

    warning = None
    if recomputed is not None and stored_pct is not None and abs(recomputed - stored_pct) > 0.05:
        warning = (
            f"저장된 accuracy({stored}) 와 correct/n 재계산값({recomputed:.4f} %)이 "
            f"{abs(recomputed - stored_pct):.3f} pp 어긋납니다."
        )
    if recomputed is None and stored_pct is not None:
        recomputed = stored_pct
    return n, correct, recomputed, warning


def collect_group(run: Run, key: str) -> dict[str, tuple[int | None, int | None, float | None]]:
    """by_subject / by_category 블록을 {이름: (n, correct, 정확도%)} 로 정규화합니다."""
    raw = run.metrics.get(key)
    out: dict[str, tuple[int | None, int | None, float | None]] = {}
    if not isinstance(raw, dict):
        if raw is not None:
            run.warnings.append(f"metrics.json 의 {key} 가 객체가 아니어서 무시합니다.")
        return out
    for name, block in raw.items():
        n, correct, acc, warn = stat_block(block)
        if warn:
            run.warnings.append(f"metrics.json {key}.{name}: {warn}")
        out[str(name)] = (n, correct, acc)
    return out


def macro_mean(values: Iterable[float | None]) -> float | None:
    """None 을 제외한 단순 평균(macro). 전체 정확도(micro)와 구분해 표시하기 위한 값입니다."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def binomial_se_pp(p_pct: float | None, n: int | None) -> float | None:
    """이항분포 표준오차를 퍼센트포인트로 돌려줍니다. sqrt(p(1-p)/n) * 100."""
    if p_pct is None or not n or n <= 0:
        return None
    p = p_pct / 100.0
    p = min(max(p, 0.0), 1.0)
    return 100.0 * math.sqrt(p * (1.0 - p) / n)


# ---------------------------------------------------------------------------
# 보고서 절 — 모두 Markdown 줄 목록을 돌려줍니다.
# ---------------------------------------------------------------------------


def section_header(run: Run) -> list[str]:
    """문서 제목과 실행 개요."""
    now_utc = datetime.now(timezone.utc)
    model = run.env.get("model") if isinstance(run.env.get("model"), dict) else {}
    dataset = run.env.get("dataset") if isinstance(run.env.get("dataset"), dict) else {}

    overall_n, _, _, _ = stat_block(run.metrics.get("overall"))
    partial, partial_reason = is_partial_run(run)

    rows = [
        ["실행 디렉터리", str(run.path)],
        ["담당 팀원", run.member],
        ["모델", model.get("repo_id") or cfg_get(run, "model", default="N/A")],
        [
            "모델 리비전",
            model.get("revision") or cfg_get(run, "model_revision", default="N/A"),
        ],
        [
            "데이터셋",
            dataset.get("repo_id_or_path") or cfg_get(run, "data_path", default="N/A"),
        ],
        [
            "데이터셋 리비전",
            dataset.get("revision") or cfg_get(run, "dataset_revision", default="N/A"),
        ],
        ["분할(split)", dataset.get("split") or cfg_get(run, "split", default="validation")],
        ["표본 수", overall_n if overall_n is not None else dataset.get("n_samples")],
        ["추론 백엔드", cfg_get(run, "backend", default="N/A")],
        ["프롬프트 템플릿", cfg_get(run, "template", default="N/A")],
        ["시드(seed)", cfg_get(run, "seed", default="N/A")],
        ["보고서 생성 시각", f"{now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC / {now_utc.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')} KST"],
    ]

    lines = [
        "# MMMU validation 베이스라인 평가 결과 (Qwen3-VL-4B-Instruct)",
        "",
        "본 문서는 `src/report.py` 가 실행 디렉터리의 `metrics.json` / `timing.json` / "
        "`env.json` / `predictions.jsonl` 을 읽어 자동 생성한 것입니다. 손으로 수정하지 마시고, "
        "수치를 고칠 일이 생기면 평가를 다시 실행한 뒤 이 스크립트를 다시 돌리십시오.",
        "",
        "## 1. 실행 개요",
        "",
    ]
    lines += md_table(["항목", "값"], rows)
    lines.append("")
    if partial:
        lines += [
            f"> **주의**: 이 실행은 전수 실행이 아닙니다({partial_reason}). "
            "따라서 900문항 기준 기대치(847/53 문항 구성, 멀티 이미지 43문항 등)와 공개 점수 67.4 와의 "
            "비교는 참고용으로만 보셔야 하며, 제출용 수치로 사용해서는 안 됩니다.",
            "",
        ]
    return lines


def section_integrity(run: Run) -> list[str]:
    """무결성 점검 — 조용한 버그를 눈에 보이게 만드는 절.

    멀티 이미지 문항 43개가 통째로 빠지는 것 같은 사고는 정확도 표만 보면 절대 드러나지
    않습니다(FACTS 4a). 그래서 기대치와 관측치를 나란히 놓고 먼저 확인합니다.
    """
    partial, partial_reason = is_partial_run(run)
    overall_n, overall_correct, _, overall_acc_warn = stat_block(run.metrics.get("overall"))
    by_subject = collect_group(run, "by_subject")
    by_category = collect_group(run, "by_category")
    mc_n, _, _, mc_acc_warn = stat_block(run.metrics.get("multiple_choice"))
    open_n, _, _, open_acc_warn = stat_block(run.metrics.get("open_ended"))

    rows: list[list[Any]] = []
    issues = 0

    def check(item: str, expected: Any, observed: Any, ok: bool | None, note: str = "") -> None:
        nonlocal issues
        if ok is None:
            verdict = "해당 없음"
        elif ok:
            verdict = "정상"
        else:
            verdict = "확인 필요"
            issues += 1
        rows.append([item, expected, observed, verdict, note or "-"])

    # 전체 표본 수
    total_note = partial_reason if partial else "FACTS 4: validation = 30문항 x 30과목 = 900"
    if not run.config:
        # config.json 이 없으면 --limit/--subjects 여부를 알 수 없으므로 전수 실행으로 간주합니다.
        total_note += " / config.json 이 없어 부분 실행 여부를 판별할 수 없습니다."
    check(
        "전체 표본 수",
        EXPECTED_TOTAL_N,
        overall_n,
        None if partial else (overall_n == EXPECTED_TOTAL_N),
        total_note,
    )
    # 저장된 accuracy 와 correct/n 재계산값의 일치 — 집계 버그를 잡는 핵심 점검입니다.
    acc_warns = [w for w in (overall_acc_warn, mc_acc_warn, open_acc_warn) if w]
    check(
        "저장된 accuracy = correct / n",
        "일치",
        "일치" if not acc_warns else f"{len(acc_warns)}개 블록 불일치",
        not acc_warns,
        acc_warns[0] if acc_warns else "overall / multiple_choice / open_ended 블록을 각각 재계산해 대조합니다.",
    )
    # 과목 수
    check(
        "과목 수",
        EXPECTED_SUBJECT_N,
        len(by_subject),
        None if partial else (len(by_subject) == EXPECTED_SUBJECT_N),
        "FACTS 4: HF config 가 과목별로 1개씩 30개",
    )
    # 합계 일치
    subj_sum = sum(n for n, _, _ in by_subject.values() if n is not None)
    check(
        "과목별 n 합계 = 전체 n",
        overall_n,
        subj_sum,
        (overall_n is not None and subj_sum == overall_n),
        "어긋나면 집계 단계에서 문항이 누락되었습니다.",
    )
    cat_sum = sum(n for n, _, _ in by_category.values() if n is not None)
    check(
        "카테고리별 n 합계 = 전체 n",
        overall_n,
        cat_sum,
        (overall_n is not None and cat_sum == overall_n),
        "어긋나면 과목→카테고리 매핑에 빠진 과목이 있습니다.",
    )
    # 유형 구성
    if mc_n is not None and open_n is not None:
        check(
            "객관식 + 단답형 = 전체 n",
            overall_n,
            mc_n + open_n,
            (overall_n is not None and mc_n + open_n == overall_n),
            "question_type 분류 누락 점검",
        )
        check(
            "객관식 / 단답형 문항 수",
            f"{EXPECTED_MC_N} / {EXPECTED_OPEN_N}",
            f"{mc_n} / {open_n}",
            None if partial else (mc_n == EXPECTED_MC_N and open_n == EXPECTED_OPEN_N),
            "FACTS 4: 847 multiple-choice + 53 open",
        )
    else:
        check("객관식 / 단답형 문항 수", f"{EXPECTED_MC_N} / {EXPECTED_OPEN_N}", "N/A", False,
              "metrics.json 에 multiple_choice / open_ended 블록이 없습니다.")

    # 카테고리별 기대 표본 수 (FACTS 4b)
    mismatched = []
    for category in CATEGORY_ORDER:
        observed = by_category.get(category, (None, None, None))[0]
        if observed != EXPECTED_CATEGORY_N[category]:
            mismatched.append(f"{category}={'없음' if observed is None else observed}")
    check(
        "카테고리별 표본 수",
        "120/150/150/150/120/210",
        "일치" if not mismatched else ", ".join(mismatched),
        None if partial else (not mismatched),
        "FACTS 4b",
    )

    # predictions.jsonl 기반 점검
    if run.has_predictions_file:
        preds = run.predictions
        check(
            "predictions.jsonl 줄 수 = 전체 n",
            overall_n,
            len(preds),
            (overall_n is not None and len(preds) == overall_n),
            "응답 덤프 누락 점검",
        )
        ids = [p.get("id") for p in preds]
        dup = len(ids) - len(set(ids))
        check("중복 id", 0, dup, dup == 0, "같은 문항이 두 번 채점되면 정확도가 왜곡됩니다.")

        n_images = [p.get("n_images") for p in preds if isinstance(p.get("n_images"), int)]
        multi = sum(1 for v in n_images if v >= 2)
        check(
            "이미지 2장 이상 문항 수",
            EXPECTED_MULTI_IMAGE_N,
            multi,
            None if partial else (multi == EXPECTED_MULTI_IMAGE_N),
            "FACTS 4: 2장 24 + 3장 5 + 4장 8 + 5장 6 = 43. 여기서 어긋나면 멀티 이미지 문항이 통째로 빠졌습니다.",
        )
        check(
            "최대 이미지 장수",
            EXPECTED_MAX_IMAGES,
            max(n_images) if n_images else "N/A",
            None if partial else (bool(n_images) and max(n_images) == EXPECTED_MAX_IMAGES),
            "FACTS 4: validation 최대 5장(image_6/7 은 항상 null)",
        )
        # image_indices 와 n_images 정합성 (FACTS 4a: 마커 N -> image_N 매핑)
        bad_idx = 0
        for p in preds:
            idx = p.get("image_indices")
            cnt = p.get("n_images")
            if isinstance(idx, list) and isinstance(cnt, int) and len(idx) != cnt:
                bad_idx += 1
        check(
            "image_indices 길이 = n_images",
            0,
            bad_idx,
            bad_idx == 0,
            "어긋나면 `<image N>` 마커 매핑(FACTS 4a)이 깨졌습니다.",
        )
        # 출력 토큰 상한에 닿은 문항 — 답이 잘려 파싱이 실패할 수 있습니다.
        max_new = cfg_get(run, "max_new_tokens", default=None)
        try:
            max_new_i = int(max_new) if max_new is not None else None
        except (TypeError, ValueError):
            max_new_i = None
        if max_new_i:
            capped = sum(1 for p in preds if isinstance(p.get("output_tokens"), int) and p["output_tokens"] >= max_new_i)
            check(
                "출력 토큰 상한 도달 문항",
                0,
                capped,
                capped == 0,
                f"--max-new-tokens {max_new_i} 에 닿은 응답은 중간에서 잘려 파싱 실패로 이어질 수 있습니다.",
            )
        # 컨텍스트 초과 (FACTS 3: 9048 에서 900문항 중 0건이 초과)
        max_len = cfg_get(run, "max_model_len", "max_model_length", default=None)
        try:
            max_len_i = int(max_len) if max_len is not None else None
        except (TypeError, ValueError):
            max_len_i = None
        if max_len_i:
            over = sum(1 for p in preds if isinstance(p.get("prompt_tokens"), int) and p["prompt_tokens"] >= max_len_i)
            check(
                "프롬프트가 max_model_len 초과",
                0,
                over,
                over == 0,
                f"FACTS 3: max_model_len={max_len_i} 에서 900문항 중 초과 0건이 정상입니다.",
            )

    # git 상태 (FACTS 12: dirty 인 상태의 결과는 재현 불가)
    git = run.env.get("git") if isinstance(run.env.get("git"), dict) else {}
    dirty = git.get("dirty")
    dirty_flag = _is_dirty(dirty)
    dirty_is_clean = None if dirty_flag is None else (not dirty_flag)
    check(
        "git 작업 트리 청결(dirty=false)",
        "false",
        dirty,
        dirty_is_clean,
        "FACTS 12: dirty=true 인 실행은 커밋과 결과가 대응되지 않아 보고용으로 쓸 수 없습니다.",
    )

    # 미파싱 비율 (FACTS 4c)
    n_unparseable = run.metrics.get("n_unparseable")
    if isinstance(n_unparseable, int) and mc_n:
        ratio = 100.0 * n_unparseable / mc_n
        check(
            "미파싱(무작위 추측) 비율",
            "객관식의 5 % 이하",
            f"{n_unparseable} / {mc_n} = {ratio:.2f} %",
            ratio <= 5.0,
            "FACTS 4c: 공식 파서는 실패 시 random.choice 로 추측하므로 비율이 높으면 점수 신뢰도가 떨어집니다.",
        )

    lines = ["## 2. 무결성 점검", ""]
    if issues:
        lines += [
            f"> **점검 결과: 확인이 필요한 항목 {issues}건.** 아래 표에서 '확인 필요' 행을 먼저 해결한 뒤 "
            "이 수치를 제출하십시오.",
            "",
        ]
    else:
        lines += ["> 점검 결과: 모든 항목 정상입니다.", ""]
    lines += md_table(["점검 항목", "기대", "관측", "판정", "근거/비고"], rows)
    lines.append("")
    # 경고는 중복 없이(등장 순서 유지) 문서에 남깁니다.
    unique_warnings = list(dict.fromkeys(run.warnings))
    if unique_warnings:
        lines += ["<details>", "<summary>생성 중 발생한 경고 (클릭하여 펼치기)</summary>", ""]
        lines += [f"- {w}" for w in unique_warnings]
        lines += ["", "</details>", ""]
    return lines


def section_overall(run: Run) -> list[str]:
    """전체 성능 + 공개 점수와의 차이."""
    n, correct, acc, _ = stat_block(run.metrics.get("overall"))
    published = _published_value(run)
    delta = None if acc is None else acc - published
    se = binomial_se_pp(acc, n)

    rows = [
        ["표본 수 (n)", n],
        ["정답 수 (correct)", correct],
        ["정확도 (accuracy)", fmt_pct(acc)],
        ["집계 방식", run.metrics.get("aggregation") or "micro / sample-weighted"],
        [f"공개 보고 점수 (MMMU val)", fmt_pct(published)],
        ["차이 (본 실행 − 공개)", fmt_pp(delta)],
        ["관측값 기준 표준오차 sqrt(p(1−p)/n)", "N/A" if se is None else f"{se:.2f} pp"],
    ]
    lines = ["## 3. 전체 성능", ""]
    lines += md_table(["항목", "값"], rows)
    lines += [
        "",
        f"집계는 **micro(표본 가중) 평균**입니다. 공식 MMMU 하네스도 표본 가중 방식을 쓰므로 "
        f"카테고리 6개 정확도의 단순 평균(macro)과는 값이 다릅니다(FACTS 4b). 두 값은 다음 절에 "
        f"나란히 제시합니다.",
        "",
    ]
    return lines


def _published_value(run: Run) -> float:
    """공개 보고 점수를 metrics.json 에서 읽고, 없으면 상수를 씁니다(값이 다르면 경고)."""
    block = run.metrics.get("published_reference")
    if isinstance(block, dict):
        value = block.get("mmmu_val")
        if isinstance(value, (int, float)):
            value = float(value) * 100.0 if float(value) <= 1.0 else float(value)
            if abs(value - PUBLISHED_MMMU_VAL) > 0.01:
                run.warnings.append(
                    f"metrics.json 의 published_reference.mmmu_val({value}) 이 FACTS 0 의 "
                    f"{PUBLISHED_MMMU_VAL} 과 다릅니다. FACTS.md 가 기준입니다."
                )
            return value
    return PUBLISHED_MMMU_VAL


def _published_source(run: Run) -> str:
    block = run.metrics.get("published_reference")
    if isinstance(block, dict) and isinstance(block.get("source"), str) and block["source"].strip():
        return block["source"].strip()
    return PUBLISHED_SOURCE


def section_by_category(run: Run) -> list[str]:
    """카테고리별 성능 — FACTS 4b 순서 고정, micro/macro 둘 다 표기."""
    by_category = collect_group(run, "by_category")
    overall_n, overall_correct, overall_acc, _ = stat_block(run.metrics.get("overall"))

    rows: list[list[Any]] = []
    for category in CATEGORY_ORDER:
        n, correct, acc = by_category.get(category, (None, None, None))
        expected = EXPECTED_CATEGORY_N[category]
        flag = "-" if n == expected else f"기대 {expected} 과 불일치"
        rows.append(
            [
                f"{category} ({CATEGORY_KR[category]})",
                len(DOMAIN_CAT2SUB_CAT[category]),
                n,
                expected,
                correct,
                fmt_pct(acc),
                flag,
            ]
        )
    # metrics 에 FACTS 4b 에 없는 카테고리가 들어 있으면 숨기지 않고 드러냅니다.
    for category in sorted(set(by_category) - set(CATEGORY_ORDER)):
        n, correct, acc = by_category[category]
        rows.append([category, "-", n, "-", correct, fmt_pct(acc), "FACTS 4b 에 없는 카테고리"])

    macro = macro_mean([by_category.get(c, (None, None, None))[2] for c in CATEGORY_ORDER])
    lines = ["## 4. 카테고리별 성능", ""]
    lines += md_table(
        ["카테고리", "과목 수", "n", "기대 n", "정답", "정확도", "비고"],
        rows,
        align=["l", "r", "r", "r", "r", "r", "l"],
    )
    lines += [
        "",
        "### 4.1 micro vs macro",
        "",
    ]
    lines += md_table(
        ["집계 방식", "정의", "값"],
        [
            [
                "micro (표본 가중) — **공식 기준**",
                "전체 정답 수 / 전체 문항 수",
                fmt_pct(overall_acc),
            ],
            [
                "macro (비가중)",
                "6개 카테고리 정확도의 단순 평균",
                fmt_pct(macro),
            ],
            [
                "두 값의 차이",
                "macro − micro",
                fmt_pp(None if (macro is None or overall_acc is None) else macro - overall_acc),
            ],
        ],
        align=["l", "l", "r"],
    )
    lines += [
        "",
        "카테고리별 표본 수가 120/150/150/150/120/210 으로 고르지 않기 때문에 두 값은 원리적으로 "
        "일치하지 않습니다(FACTS 4b). 공식 MMMU 하네스와 공개 점수 67.4 는 **micro** 기준이므로, "
        "보고·비교에는 반드시 micro 값을 쓰고 macro 는 카테고리 간 편차를 보는 보조 지표로만 쓰십시오.",
        "",
    ]
    return lines


def section_by_subject(run: Run) -> list[str]:
    """과목별 성능 — 30과목 전체, 정확도 오름차순(취약 과목이 먼저)."""
    by_subject = collect_group(run, "by_subject")

    # 정확도 오름차순. 동점은 과목명 알파벳 순으로 고정해 출력이 결정적이 되게 합니다.
    def sort_key(item: tuple[str, tuple[int | None, int | None, float | None]]):
        name, (_, _, acc) = item
        return (acc if acc is not None else float("inf"), name)

    rows: list[list[Any]] = []
    for rank, (subject, (n, correct, acc)) in enumerate(sorted(by_subject.items(), key=sort_key), start=1):
        category = SUB2DOMAIN.get(subject, "(미확인)")
        rows.append(
            [
                rank,
                subject,
                SUBJECT_KR.get(subject, "-"),
                f"{category} ({CATEGORY_KR.get(category, '-')})" if category in CATEGORY_KR else category,
                n,
                correct,
                fmt_pct(acc),
            ]
        )

    missing = [s for s in ALL_SUBJECTS if s not in by_subject]
    present = [(s, v) for s, v in sorted(by_subject.items(), key=sort_key) if v[2] is not None]

    lines = ["## 5. 과목별 성능 (정확도 오름차순)", ""]
    lines += md_table(
        ["순위", "과목 (HF config)", "과목(한글)", "카테고리", "n", "정답", "정확도"],
        rows,
        align=["r", "l", "l", "l", "r", "r", "r"],
    )
    lines.append("")
    if missing:
        lines += [
            f"> **주의**: 30개 과목 중 {len(missing)}개가 결과에 없습니다: "
            + ", ".join(f"`{m}`" for m in missing)
            + ". 부분 실행이 아니라면 데이터 로딩 단계(FACTS 4: config 30개를 각각 load_dataset)에서 "
            "누락이 발생한 것입니다.",
            "",
        ]
    if present:
        weak = present[:5]
        strong = list(reversed(present[-5:]))
        lines += [
            "### 5.1 성능 분석용 요약",
            "",
            "- **가장 취약한 과목 5개**: "
            + ", ".join(f"{s} ({SUBJECT_KR.get(s, '-')}) {v[2]:.2f} %" for s, v in weak),
            "- **가장 우수한 과목 5개**: "
            + ", ".join(f"{s} ({SUBJECT_KR.get(s, '-')}) {v[2]:.2f} %" for s, v in strong),
            f"- 과목 간 정확도 폭(최고 − 최저): {present[-1][1][2] - present[0][1][2]:.2f} pp",
            "",
            f"과목당 표본은 30문항뿐이므로 한 문항이 3.33 pp 를 움직입니다. 즉 과목 단위 수치는 "
            f"편차가 크며, 전체 n=900 기준 1문항이 {ONE_SAMPLE_PP} pp 인 것과 비교해 "
            f"약 30배 민감합니다(FACTS 7). 과목 순위는 경향을 보는 데까지만 쓰고, "
            f"단정적인 결론은 카테고리 단위(n=120~210)에서 내리십시오.",
            "",
        ]
    return lines


def section_by_type(run: Run) -> list[str]:
    """문제 유형별 성능 + 미파싱(무작위 추측) 진단."""
    mc_n, mc_correct, mc_acc, _ = stat_block(run.metrics.get("multiple_choice"))
    open_n, open_correct, open_acc, _ = stat_block(run.metrics.get("open_ended"))
    overall_n, _, _, _ = stat_block(run.metrics.get("overall"))
    n_unparseable = run.metrics.get("n_unparseable")

    rows = [
        [
            "multiple-choice (객관식)",
            mc_n,
            EXPECTED_MC_N,
            mc_correct,
            fmt_pct(mc_acc),
            "공식 `parse_multi_choice_response` 로 채점",
        ],
        [
            "open (단답형)",
            open_n,
            EXPECTED_OPEN_N,
            open_correct,
            fmt_pct(open_acc),
            "공식 `parse_open_response` 로 채점",
        ],
    ]
    lines = ["## 6. 문제 유형별 성능", ""]
    lines += md_table(
        ["유형", "n", "기대 n", "정답", "정확도", "채점 방식"],
        rows,
        align=["l", "r", "r", "r", "r", "l"],
    )
    lines.append("")

    # 미파싱 진단
    ratio = None
    if isinstance(n_unparseable, int) and mc_n:
        ratio = 100.0 * n_unparseable / mc_n
    guess_rows = [
        ["미파싱(파서 fallback) 응답 수", n_unparseable if n_unparseable is not None else "N/A"],
        ["객관식 대비 비율", "N/A" if ratio is None else f"{ratio:.2f} %"],
    ]
    if isinstance(n_unparseable, int) and overall_n:
        # 선택지 4개 기준 기대 우연 정답 수. FACTS 4b 에 따르면 847개 객관식 중 241개는
        # 선택지가 4개가 아니므로(2~9개) 어디까지나 근사치입니다.
        lucky = 0.25 * n_unparseable
        guess_rows.append(
            [
                "우연히 맞은 것으로 추정되는 문항 수 (선택지 4개 가정)",
                f"약 {lucky:.1f} 문항 ≈ 전체 정확도 {100.0 * lucky / overall_n:.2f} pp",
            ]
        )
        # 선택지 수가 많을수록 우연 정답 기대값은 작아집니다(9개 -> 1/9, 2개 -> 1/2).
        guess_rows.append(
            [
                "추정 범위 (선택지 9개 → 2개)",
                f"{n_unparseable / 9.0:.1f} ~ {0.5 * n_unparseable:.1f} 문항",
            ]
        )
    lines += md_table(["미파싱 진단 항목", "값"], guess_rows)
    lines += [
        "",
        "### 6.1 미파싱(unparseable)이 무엇을 뜻하는가",
        "",
        "공식 MMMU 파서(`mmmu/utils/eval_utils.py`)는 응답에서 선택지 문자를 찾지 못하면 "
        "`random.choice(all_choices)` 로 **무작위 추측**을 반환합니다. 즉 미파싱 문항은 오답으로 "
        "처리되는 것이 아니라, 선택지 수의 역수만큼 확률로 정답 처리됩니다. 본 구현은 이 동작을 "
        "그대로 재현하되 몇 건이 fallback 에 걸렸는지 세어 `n_unparseable` 로 남깁니다(FACTS 4c).",
        "",
        "실제로 fallback 에 걸리는 것이 확인된 응답 형태는 다음과 같습니다(FACTS 4c).",
        "",
        "- `**C**` — Markdown 굵게 표시. 괄호 패스에 걸리지 않고, ` C ` 패스는 양쪽 공백을 요구합니다.",
        "- `C) $8` — 닫는 괄호만 있는 형태.",
        "- `c` — 소문자 단독.",
        "- 빈 문자열(`\"\"`) — 생성이 즉시 종료된 경우.",
        "- `The correct option is $8` — 선택지 본문 매칭 패스는 응답 토큰이 5개를 **넘을 때만** "
        "실행되므로 정확히 5토큰인 이 응답은 본문 매칭 없이 추측으로 넘어갑니다.",
        "",
        "따라서 `n_unparseable` 은 그 자체로 프롬프트 품질 지표입니다. 값이 크면 정확도 수치에 "
        "무작위 성분이 섞였다는 뜻이므로, 파서를 고치는 대신(공식 호환성을 잃습니다) "
        "`--template anchored` 처럼 `Answer: <letter>` 앵커를 강제하는 프롬프트로 "
        "다시 측정하는 것이 올바른 대응입니다(FACTS 11).",
        "",
        "또한 무작위 추측은 전역 `random` 스트림을 소비하므로 **문항 순회 순서가 바뀌면 점수도 바뀝니다**. "
        "본 구현은 순서를 고정하고 채점 루프 직전에 `random.seed(42)` 를 호출합니다(FACTS 4c).",
        "",
    ]
    return lines


def section_timing(run: Run) -> list[str]:
    """소요 시간 — 총시간/모델 로딩/추론/채점 + 카테고리·과목별 표."""
    timing = run.timing
    total = timing.get("total_wall_s")
    load = timing.get("model_load_s")
    infer = timing.get("inference_s")
    score = timing.get("scoring_s")

    def share(value: Any) -> str:
        try:
            if total is not None and float(total) > 0 and value is not None:
                return f"{100.0 * float(value) / float(total):.1f} %"
        except (TypeError, ValueError):
            pass
        return "N/A"

    other = None
    try:
        if total is not None and None not in (load, infer, score):
            other = float(total) - float(load) - float(infer) - float(score)
    except (TypeError, ValueError):
        other = None

    overall_n, _, _, _ = stat_block(run.metrics.get("overall"))
    per_sample_infer = None
    try:
        if infer is not None and overall_n:
            per_sample_infer = float(infer) / overall_n
    except (TypeError, ValueError):
        per_sample_infer = None

    rows = [
        ["총 소요 시간 (total_wall_s)", fmt_sec(total), "100.0 %" if total is not None else "N/A"],
        ["모델 로딩 (model_load_s)", fmt_sec(load), share(load)],
        ["추론 (inference_s)", fmt_sec(infer), share(infer)],
        ["채점 (scoring_s)", fmt_sec(score), share(score)],
        ["그 외(데이터 로딩·집계 등)", fmt_sec(other), share(other)],
        ["문항당 평균 추론 시간", "N/A" if per_sample_infer is None else f"{per_sample_infer:.2f} 초/문항", "-"],
    ]

    lines = ["## 7. 소요 시간", ""]
    if not timing:
        lines += [
            "> **경고**: `timing.json` 을 찾을 수 없습니다. 과제는 총 소요 시간과 카테고리·과목별 "
            "소요 시간을 요구하므로, 이 상태로는 제출 요건을 충족하지 못합니다. 평가를 다시 "
            "실행하여 `timing.json` 을 생성하십시오.",
            "",
        ]
    lines += md_table(["구간", "시간", "총시간 대비"], rows, align=["l", "r", "r"])
    lines += [
        "",
        "모델 로딩 시간을 따로 계측하는 이유는, 엔진 기동(가중치 로딩, vLLM 의 torch.compile / "
        "CUDA 그래프 캡처) 비용이 알파벳 순으로 첫 번째 과목(`Accounting`)에 전가되어 과목별 "
        "시간 표를 왜곡하기 때문입니다(FACTS 7). 또한 첫 실행은 HF 다운로드가 포함된 "
        "cold-cache 실행이므로, 캐시를 채운 뒤의 실행만 보고용 수치로 사용하십시오.",
        "",
    ]

    # 카테고리별
    cat_timing = timing.get("by_category") if isinstance(timing.get("by_category"), dict) else {}
    cat_rows: list[list[Any]] = []
    for category in CATEGORY_ORDER:
        block = cat_timing.get(category) if isinstance(cat_timing.get(category), dict) else {}
        n = block.get("n")
        wall = block.get("wall_s")
        sps = block.get("s_per_sample")
        if sps is None:
            try:
                sps = float(wall) / int(n) if wall is not None and n else None
            except (TypeError, ValueError, ZeroDivisionError):
                sps = None
        cat_rows.append(
            [
                f"{category} ({CATEGORY_KR[category]})",
                n,
                fmt_sec(wall),
                "N/A" if sps is None else f"{float(sps):.2f} 초/문항",
            ]
        )
    lines += ["### 7.1 카테고리별 소요 시간", ""]
    lines += md_table(["카테고리", "n", "소요 시간", "문항당"], cat_rows, align=["l", "r", "r", "r"])
    lines.append("")

    # 과목별 — 느린 과목이 위로 오게 문항당 시간 내림차순
    subj_timing = timing.get("by_subject") if isinstance(timing.get("by_subject"), dict) else {}
    entries: list[tuple[str, Any, Any, float | None]] = []
    for subject, block in subj_timing.items():
        if not isinstance(block, dict):
            continue
        n = block.get("n")
        wall = block.get("wall_s")
        sps = block.get("s_per_sample")
        if sps is None:
            try:
                sps = float(wall) / int(n) if wall is not None and n else None
            except (TypeError, ValueError, ZeroDivisionError):
                sps = None
        try:
            sps_f = float(sps) if sps is not None else None
        except (TypeError, ValueError):
            sps_f = None
        entries.append((str(subject), n, wall, sps_f))

    entries.sort(key=lambda e: (-(e[3] if e[3] is not None else -1.0), e[0]))
    subj_rows = [
        [
            subject,
            SUBJECT_KR.get(subject, "-"),
            n,
            fmt_sec(wall),
            "N/A" if sps is None else f"{sps:.2f} 초/문항",
        ]
        for subject, n, wall, sps in entries
    ]
    lines += ["### 7.2 과목별 소요 시간 (문항당 시간 내림차순)", ""]
    lines += md_table(["과목", "과목(한글)", "n", "소요 시간", "문항당"], subj_rows, align=["l", "l", "r", "r", "r"])
    lines.append("")

    # 문항 단위 지연 분포 (predictions.jsonl 이 있을 때만)
    latencies = sorted(
        float(p["latency_s"])
        for p in run.predictions
        if isinstance(p.get("latency_s"), (int, float))
    )
    if latencies:
        lines += ["### 7.3 문항 단위 지연 시간 분포", ""]
        lines += md_table(
            ["통계량", "값(초)"],
            [
                ["문항 수", len(latencies)],
                ["최소", fmt_float(latencies[0], 2)],
                ["중위수(p50)", fmt_float(_percentile(latencies, 50), 2)],
                ["평균", fmt_float(sum(latencies) / len(latencies), 2)],
                ["p95", fmt_float(_percentile(latencies, 95), 2)],
                ["최대", fmt_float(latencies[-1], 2)],
                ["합계", fmt_float(sum(latencies), 1)],
            ],
            align=["l", "r"],
        )
        lines += [
            "",
            "vLLM 은 여러 요청을 연속 배치로 처리하므로 문항별 `latency_s` 의 합계는 "
            "`inference_s` 보다 크게 나올 수 있습니다(요청 구간이 서로 겹칩니다). "
            "처리량 기준 수치는 위 7절의 `inference_s` 를 쓰십시오.",
            "",
        ]
    return lines


def section_environment(run: Run) -> list[str]:
    """실험 환경 — HW 인프라, 드라이버, 모든 도구 패키지 버전.

    팀의 이번 주 최우선 요구사항입니다. env.json 에 실제로 기록된 값만 렌더링하고,
    비어 있으면 숨기지 않고 "N/A" 로 드러냅니다.
    """
    env = run.env
    lines = ["## 8. 실험 환경", ""]
    if not env:
        lines += [
            "> **경고**: `env.json` 을 찾을 수 없어 실험 환경을 기록할 수 없습니다. "
            "과제 요구사항(HW 인프라 및 도구 패키지 버전)을 충족하지 못하는 상태이므로 "
            "`python -m src.capture_env --out <RUN_DIR>` 를 실행하거나 평가를 다시 수행하십시오.",
            "",
        ]
        return lines

    lines += [
        f"- env.json schema_version: `{env.get('schema_version', 'N/A')}`",
        f"- 수집 시각(UTC): `{env.get('captured_at_utc', 'N/A')}`",
        "",
    ]

    # 8.1 하드웨어
    hw = env.get("hardware") if isinstance(env.get("hardware"), dict) else {}
    vram = hw.get("vram_total_mib")
    vram_text: Any = vram
    try:
        if vram is not None:
            vram_text = f"{int(vram)} MiB ({int(vram) / 1024.0:.1f} GiB)"
    except (TypeError, ValueError):
        vram_text = vram
    lines += ["### 8.1 하드웨어", ""]
    lines += md_table(
        ["항목", "값"],
        [
            ["GPU", hw.get("gpu_name")],
            ["GPU 개수", hw.get("gpu_count")],
            ["GPU 메모리", vram_text],
            ["CPU", hw.get("cpu_model")],
            ["CPU 코어 수", hw.get("cpu_count")],
            ["시스템 메모리", None if hw.get("ram_gib") is None else f"{hw.get('ram_gib')} GiB"],
        ],
    )
    lines.append("")

    # 8.2 드라이버와 CUDA (FACTS 9)
    dc = env.get("driver_cuda") if isinstance(env.get("driver_cuda"), dict) else {}
    lines += ["### 8.2 드라이버와 CUDA 버전", ""]
    lines += md_table(
        ["항목", "값", "의미"],
        [
            [
                "nvidia-smi 헤더 CUDA",
                dc.get("nvidia_smi_cuda"),
                "드라이버가 지원하는 **최대** 런타임 버전입니다. 실제 사용 버전이 아닙니다.",
            ],
            [
                "torch.version.cuda",
                dc.get("torch_version_cuda"),
                "휠이 빌드된 CUDA — **실제로 중요한 값**입니다.",
            ],
            [
                "nvcc --version",
                dc.get("nvcc_version"),
                "로컬 툴킷. 보통 설치되어 있지 않고, 미리 빌드된 휠과는 무관합니다.",
            ],
            ["NVIDIA 드라이버 버전", dc.get("driver_version"), "CUDA 12.x 는 525 이상, 13.x 는 580 이상이 필요합니다."],
        ],
    )
    lines += [
        "",
        "세 CUDA 버전은 서로 다른 것을 가리킵니다(FACTS 9). 예를 들어 `nvidia-smi` 가 13.0 인데 "
        "`torch.version.cuda` 가 12.9 인 상태는 **정상**이며 조치할 필요가 없습니다. "
        "또한 RunPod 머신마다 드라이버가 다르므로, 팀원 4명은 Pod 생성 시 CUDA 버전 필터를 써서 "
        "같은 드라이버를 받아야 합니다. 드라이버가 다르면 커널 경로가 달라져 설명할 수 없는 "
        "정확도 차이가 생깁니다(FACTS 8).",
        "",
    ]

    # 8.3 OS / Python
    lines += ["### 8.3 운영체제와 Python", ""]
    os_rows = _flatten(env.get("os"), "os") + _flatten(env.get("python"), "python")
    lines += md_table(["항목", "값"], os_rows)
    lines.append("")

    # 8.4 패키지 버전
    packages = env.get("packages") if isinstance(env.get("packages"), dict) else {}
    pip_freeze = packages.get("pip_freeze")
    pkg_rows: list[list[Any]] = []
    for name in KEY_PACKAGES:
        value = None
        for key in (name, name.replace("-", "_"), name.replace("_", "-")):
            if key in packages and packages[key] is not None:
                value = packages[key]
                break
        pkg_rows.append([name, value if value is not None else "미설치"])
    extra_names = sorted(
        k for k in packages
        if k != "pip_freeze"
        and k.replace("_", "-") not in {p.replace("_", "-") for p in KEY_PACKAGES}
    )
    for name in extra_names:
        pkg_rows.append([name, packages[name]])

    lines += ["### 8.4 도구 패키지 버전", ""]
    lines += md_table(["패키지", "버전"], pkg_rows)
    lines += [
        "",
        "`flash-attn` 이 `미설치` 인 것은 의도된 상태입니다. PyPI 에 소스 배포본만 있어 설치에 "
        "30~60분의 컴파일이 필요하고, Qwen3-VL 은 `_supports_sdpa = True` 이므로 "
        "`attn_implementation=\"sdpa\"` 로 충분합니다(FACTS 5).",
        "",
    ]
    if isinstance(pip_freeze, (list, tuple)) and pip_freeze:
        lines += [
            "<details>",
            f"<summary>pip freeze 전체 목록 ({len(pip_freeze)}개 패키지) — 클릭하여 펼치기</summary>",
            "",
            "```text",
        ]
        lines += [str(item) for item in pip_freeze]
        lines += ["```", "", "</details>", ""]
    elif isinstance(pip_freeze, str) and pip_freeze.strip():
        lines += [
            "<details>",
            "<summary>pip freeze 전체 목록 — 클릭하여 펼치기</summary>",
            "",
            "```text",
            pip_freeze,
            "```",
            "",
            "</details>",
            "",
        ]
    else:
        lines += [
            "> **주의**: `packages.pip_freeze` 가 비어 있습니다. 전체 의존성 목록이 없으면 "
            "다른 팀원이 환경을 똑같이 재현할 수 없습니다.",
            "",
        ]

    # 8.5 아티팩트 리비전 (FACTS 6)
    model = env.get("model") if isinstance(env.get("model"), dict) else {}
    dataset = env.get("dataset") if isinstance(env.get("dataset"), dict) else {}
    lines += ["### 8.5 모델·데이터셋 아티팩트 리비전", ""]
    lines += md_table(
        ["항목", "값"],
        [
            ["모델 repo_id", model.get("repo_id")],
            ["모델 revision (커밋 SHA)", model.get("revision")],
            ["모델 로컬 경로", model.get("local_path")],
            ["dtype", model.get("dtype")],
            ["attn_implementation", model.get("attn_implementation")],
            ["데이터셋 repo_id 또는 경로", dataset.get("repo_id_or_path")],
            ["데이터셋 revision", dataset.get("revision")],
            ["분할(split)", dataset.get("split")],
            ["표본 수", dataset.get("n_samples")],
        ],
    )
    rev_warn = []
    for label, value in (("모델", model.get("revision")), ("데이터셋", dataset.get("revision"))):
        if value in (None, "", "main", "master"):
            rev_warn.append(label)
    lines.append("")
    if rev_warn:
        lines += [
            f"> **경고**: {', '.join(rev_warn)} 리비전이 비어 있거나 `main` 입니다. `main` 은 움직이는 "
            "브랜치 포인터입니다. MMMU/MMMU 의 데이터 파일은 2026-02-12, 2026-04-21, 2026-07-10 에 "
            "실제로 변경되었고, 이는 67.4 가 공개된 **이후**입니다. 따라서 `MMMU/MMMU` 라는 문자열만으로는 "
            "재현 가능한 식별자가 되지 못합니다(FACTS 6). 커밋 SHA 를 고정해 다시 실행하십시오.",
            "",
        ]
    else:
        lines += [
            "두 리비전이 커밋 SHA 로 고정되어 있어야 결과가 재현 가능합니다. `main` 은 움직이는 "
            "포인터이며, MMMU/MMMU 의 데이터 파일은 67.4 공개 이후에도 세 차례 변경되었습니다(FACTS 6).",
            "",
        ]

    # 8.6 실행 설정
    run_config = env.get("run_config")
    cfg_rows = _flatten(run_config) if run_config else _flatten(run.config)
    lines += ["### 8.6 실행 설정 (inference settings)", ""]
    if cfg_rows:
        lines += md_table(["설정 키", "값"], sorted(cfg_rows))
    else:
        lines += md_table(["설정 키", "값"], [])
    lines.append("")

    # 픽셀 예산 해설 (FACTS 1) — 교수님 슬라이드의 28*28 표기가 Qwen3-VL 에서 뜻하는 바
    min_pixels = cfg_get(run, "min_pixels")
    max_pixels = cfg_get(run, "max_pixels")
    lines += [
        "#### 픽셀 예산이 실제로 뜻하는 것",
        "",
        f"- 전달된 `min_pixels` = `{_cell(min_pixels)}`, `max_pixels` = `{_cell(max_pixels)}`",
        "- Qwen3-VL-4B-Instruct 는 `patch_size=16`, `spatial_merge_size=2` 이므로 smart_resize 격자가 "
        "32 이고, **시각 토큰 1개가 32×32 = 1,024 픽셀**을 담습니다(FACTS 1).",
        "- 따라서 교수님 슬라이드의 `1280*28*28` = 1,003,520 px 는 이미지당 **약 980 토큰 하한**, "
        "`5120*28*28` = 4,014,080 px 는 **약 3,920 토큰 상한**을 뜻합니다. `*28*28` 표기는 "
        "Qwen2-VL / Qwen2.5-VL 의 관례(토큰당 14×2=28 격자, 784 px)이며 Qwen3-VL 에서는 "
        "토큰 수와 일치하지 않습니다.",
        "- 공식 QwenLM/Qwen3-VL README 권장값은 32 격자로 쓴 "
        "`{\"shortest_edge\": 256*32*32, \"longest_edge\": 1280*32*32}`, 즉 이미지당 256~1,280 토큰입니다. "
        "본 실행의 상한은 그보다 약 3배 큽니다 → 속도와 점수 모두 달라질 수 있습니다.",
        "- 재현성을 위해서는 공식이 아니라 **해석된 `processor.image_processor.size` 딕트**를 "
        "기록해야 합니다. `AutoProcessor.from_pretrained()` 에 `max_pixels` 를 넘기는 방식은 "
        "transformers 4.57.1 이하에서 조용히 무시되었습니다(transformers #41955, PR #41997 에서 수정).",
        "",
    ]

    # 8.7 git
    git = env.get("git") if isinstance(env.get("git"), dict) else {}
    lines += ["### 8.7 Git 상태", ""]
    lines += md_table(
        ["항목", "값"],
        [["commit", git.get("commit")], ["branch", git.get("branch")], ["dirty", git.get("dirty")]],
    )
    lines.append("")
    if _is_dirty(git.get("dirty")) is True:
        lines += [
            "> **경고**: `git.dirty = true` 입니다. 커밋되지 않은 변경이 있는 상태로 측정된 결과는 "
            "어떤 코드가 이 숫자를 만들었는지 특정할 수 없어 보고용으로 쓸 수 없습니다(FACTS 12). "
            "변경을 커밋하고 다시 실행하십시오.",
            "",
        ]

    # 8.8 notes — capture_env 는 notes 를 dict 로 채울 수도, 문자열/리스트로 둘 수도 있으므로
    # dict 일 때는 표로, 그 외에는 불릿 목록으로 렌더링합니다.
    raw_notes = env.get("notes")
    if isinstance(raw_notes, dict) and raw_notes:
        note_rows = [
            [key, value]
            for key, value in _flatten(raw_notes)
            if value not in ("", "(빈 목록)", "N/A")
        ]
        if note_rows:
            lines += ["### 8.8 환경 수집 시 기록된 메모", ""]
            lines += md_table(["항목", "내용"], note_rows)
            lines.append("")
    else:
        notes = _as_list_of_lines(raw_notes)
        if notes:
            lines += ["### 8.8 환경 수집 시 기록된 메모", ""]
            lines += [f"- {note}" for note in notes]
            lines.append("")

    lines += [
        "> 팀 비교 시 주의: FACTS 7 에 따르면 재현성은 **동일 하드웨어 + 동일 vLLM 버전**에서만 "
        "성립합니다. 위 표의 GPU, 드라이버, `torch`/`transformers`/`vllm` 버전이 팀원 간에 다르면 "
        "점수 차이를 샘플링 노이즈로 설명할 수 없습니다.",
        "",
    ]
    return lines


def section_published_comparison(run: Run) -> list[str]:
    """공개 성능과의 비교 — 수치, 통계적 판정, 차이가 나는 정당한 이유들."""
    n, correct, acc, _ = stat_block(run.metrics.get("overall"))
    published = _published_value(run)
    source = _published_source(run)
    delta = None if acc is None else acc - published
    se_obs = binomial_se_pp(acc, n)
    ratio = None
    if delta is not None and se_obs:
        ratio = abs(delta) / se_obs

    rows = [
        ["공개 보고 점수 (MMMU validation)", fmt_pct(published)],
        ["출처", source],
        ["본 실행 점수 (micro)", fmt_pct(acc)],
        ["차이 (본 실행 − 공개)", fmt_pp(delta)],
        ["n = 900, p = 0.674 기준 1문항의 가치", f"{ONE_SAMPLE_PP} pp"],
        ["n = 900, p = 0.674 기준 표준오차(SE)", f"{SE_PP_AT_N900} pp"],
        ["독립적인 두 실행의 차이에 대한 95 % 구간", f"±{DIFF_CI95_PP} pp"],
        ["관측값 기준 표준오차 sqrt(p(1−p)/n)", "N/A" if se_obs is None else f"{se_obs:.2f} pp"],
        ["차이 / 관측 SE", "N/A" if ratio is None else f"{ratio:.2f} 배"],
    ]

    lines = ["## 9. 공개 성능과의 비교", ""]
    lines += md_table(["항목", "값"], rows)
    lines.append("")

    if delta is None:
        verdict = "본 실행의 정확도를 읽을 수 없어 통계적 판정을 내릴 수 없습니다."
    elif abs(delta) <= 1.96 * SE_PP_AT_N900:
        verdict = (
            f"차이 {delta:+.2f} pp 는 n=900 의 표준오차 {SE_PP_AT_N900} pp 의 1.96배"
            f"(±{1.96 * SE_PP_AT_N900:.2f} pp) 안에 있습니다. 즉 **표본오차만으로 충분히 설명되는 "
            f"범위**이며, 모델이나 코드에 문제가 있다는 증거로 볼 수 없습니다."
        )
    else:
        verdict = (
            f"차이 {delta:+.2f} pp 는 n=900 의 표준오차 {SE_PP_AT_N900} pp 의 1.96배"
            f"(±{1.96 * SE_PP_AT_N900:.2f} pp)를 넘습니다. 단순 표본오차로는 설명되지 않으므로, "
            f"아래 9.1 의 항목들을 순서대로 점검해야 합니다."
        )
    lines += [f"**판정**: {verdict}", ""]

    template = cfg_get(run, "template", default="N/A")
    backend = cfg_get(run, "backend", default="N/A")
    dataset = run.env.get("dataset") if isinstance(run.env.get("dataset"), dict) else {}
    lines += [
        "### 9.1 로컬 수치가 공개 수치와 정당하게 달라지는 이유",
        "",
        "아래 다섯 가지는 구현이 정확해도 점수가 달라지는, 이미 알려진 원인들입니다.",
        "",
        f"1. **프롬프트 템플릿** — 본 실행은 `--template {_cell(template)}` 를 사용했습니다. "
        "MMMU 가 제공하는 유일한 템플릿은 LLaVA 시절의 범용 프롬프트이고, 템플릿을 바꾸면 MMMU "
        "점수가 몇 점 단위로 움직입니다. 공개 점수가 어떤 템플릿으로 측정되었는지는 공개되어 "
        "있지 않습니다(FACTS 11).",
        f"2. **추론 프레임워크** — 본 실행의 백엔드는 `{_cell(backend)}` 입니다. 교수님도 "
        "\"The results may vary slightly depending on the inference framework\" 라고 명시했습니다"
        "(슬라이드 16). 특히 `presence_penalty=1.5` 는 transformers 의 `GenerationConfig` 에 "
        "존재하지 않는 인자여서 vLLM 경로에서만 적용됩니다(FACTS 2). 또한 lmms-eval 의 객관식 "
        "파서는 공식 파서에 없는 추가 패스를 갖고 있어 **동일한 생성 결과에서도 더 높은 점수**를 "
        "보고합니다(FACTS 10).",
        f"3. **샘플링 확률성** — `temperature=0.7`, `top_p=0.8`, `top_k=20` 은 확률적 디코딩입니다"
        "(FACTS 7). 같은 코드·같은 하드웨어에서도 실행마다 점수가 달라지며, n=900 에서 "
        f"표준오차는 {SE_PP_AT_N900} pp, 독립적인 두 실행의 차이는 95 % 구간이 "
        f"±{DIFF_CI95_PP} pp 입니다. 공개 점수와 1~2 pp 차이는 노이즈로 보아야 합니다.",
        f"4. **데이터셋 리비전 드리프트** — 본 실행의 데이터셋 리비전은 "
        f"`{_cell(dataset.get('revision') or cfg_get(run, 'dataset_revision', default='N/A'))}` 입니다. "
        "MMMU/MMMU 의 데이터 파일은 2026-02-12, 2026-04-21, 2026-07-10 의 \"Upload dataset\" 커밋으로 "
        "변경되었습니다. 즉 67.4 가 공개된 뒤에 데이터가 바뀌었으므로, 공개 점수와 현재 데이터는 "
        "애초에 완전히 같은 문제 집합이 아닐 수 있습니다(FACTS 6).",
        "5. **픽셀(시각 토큰) 예산** — Qwen3-VL 의 격자는 32 이고 토큰 1개가 1,024 px 를 담습니다. "
        "교수님의 `1280*28*28` / `5120*28*28` 은 이미지당 약 980 / 3,920 토큰으로 해석되며, 공식 "
        "README 권장인 256~1,280 토큰보다 최대 3배 큽니다(FACTS 1). 시각 토큰 수는 해상도 인식에 "
        "직접 영향을 주므로 점수와 속도가 함께 변합니다.",
        "",
        "여기에 더해 객관식 파서의 무작위 추측(FACTS 4c)이 남아 있습니다. 파서가 실패하면 공식 "
        "구현은 무작위로 한 선택지를 고르므로, 미파싱 문항 수만큼 점수에 난수 성분이 섞이고 그 값은 "
        "문항 순회 순서에까지 의존합니다. 6절의 `n_unparseable` 을 함께 보고하십시오.",
        "",
        "### 9.2 보고 시 권장 문장",
        "",
        f"> 본 팀의 로컬 측정값은 {fmt_pct(acc)} 로, 공개 보고값 {fmt_pct(published)}"
        f"({source}) 대비 {fmt_pp(delta)} 입니다. n=900 에서 1문항은 {ONE_SAMPLE_PP} pp, "
        f"표준오차는 {SE_PP_AT_N900} pp 이므로 이 정도 차이는 프롬프트 템플릿, 추론 프레임워크, "
        f"샘플링 확률성, 데이터셋 리비전, 시각 토큰 예산의 차이로 설명할 수 있는 범위입니다.",
        "",
    ]
    return lines


# ---------------------------------------------------------------------------
# 팀원 비교 (--compare)
# ---------------------------------------------------------------------------


def _pkg(env: dict, name: str) -> Any:
    """env.json packages 에서 패키지 버전을 하이픈/언더스코어 표기 모두로 찾습니다."""
    packages = env.get("packages") if isinstance(env.get("packages"), dict) else {}
    for key in (name, name.replace("-", "_"), name.replace("_", "-")):
        if key in packages and packages[key] is not None:
            return packages[key]
    return None


def _gpu_text(env: dict) -> str:
    hw = env.get("hardware") if isinstance(env.get("hardware"), dict) else {}
    name = hw.get("gpu_name")
    count = hw.get("gpu_count")
    if name is None:
        return "N/A"
    return f"{name} x{count}" if count else str(name)


def _driver_text(env: dict) -> str:
    dc = env.get("driver_cuda") if isinstance(env.get("driver_cuda"), dict) else {}
    driver = dc.get("driver_version") or "N/A"
    smi = dc.get("nvidia_smi_cuda")
    torch_cuda = dc.get("torch_version_cuda")
    parts = [str(driver)]
    if smi:
        parts.append(f"smi CUDA {smi}")
    if torch_cuda:
        parts.append(f"torch CUDA {torch_cuda}")
    return " / ".join(parts)


def render_compare(runs: Sequence[Run], *, heading_level: int = 2, heading_number: str = "10") -> list[str]:
    """팀원 간 결과 비교 표를 만듭니다."""
    hashes = "#" * heading_level
    lines = [f"{hashes} {heading_number}. 팀원 간 결과 비교", ""]
    if len(runs) < 2:
        lines += ["> 비교할 실행이 2개 미만입니다. `--compare DIR ...` 에 팀원의 실행 디렉터리를 추가하십시오.", ""]
        return lines

    rows: list[list[Any]] = []
    extra_rows: list[list[Any]] = []
    accs: list[float] = []
    published = _published_value(runs[0])

    for run in runs:
        n, correct, acc, _ = stat_block(run.metrics.get("overall"))
        if acc is not None:
            accs.append(acc)
        rows.append(
            [
                run.member,
                _gpu_text(run.env),
                _driver_text(run.env),
                _pkg(run.env, "torch"),
                _pkg(run.env, "transformers"),
                _pkg(run.env, "vllm"),
                cfg_get(run, "seed"),
                fmt_pct(acc),
                fmt_sec(run.timing.get("total_wall_s")),
            ]
        )
        dataset = run.env.get("dataset") if isinstance(run.env.get("dataset"), dict) else {}
        model = run.env.get("model") if isinstance(run.env.get("model"), dict) else {}
        git = run.env.get("git") if isinstance(run.env.get("git"), dict) else {}
        extra_rows.append(
            [
                run.member,
                str(run.path),
                n,
                cfg_get(run, "backend"),
                cfg_get(run, "template"),
                run.metrics.get("n_unparseable"),
                _short(model.get("revision") or cfg_get(run, "model_revision")),
                _short(dataset.get("revision") or cfg_get(run, "dataset_revision")),
                _short(git.get("commit")),
                git.get("dirty"),
            ]
        )

    lines += md_table(
        ["팀원", "GPU", "드라이버 / CUDA", "torch", "transformers", "vllm", "seed", "정확도", "총 소요 시간"],
        rows,
        align=["l", "l", "l", "l", "l", "l", "r", "r", "r"],
    )
    lines.append("")
    lines += [f"{hashes}# {heading_number}.1 설정·아티팩트 비교", ""]
    lines += md_table(
        ["팀원", "실행 디렉터리", "n", "backend", "template", "미파싱", "모델 rev", "데이터셋 rev", "git commit", "dirty"],
        extra_rows,
        align=["l", "l", "r", "l", "l", "r", "l", "l", "l", "l"],
    )
    lines.append("")

    # 환경 일치 여부 — 다르면 노이즈 논리가 성립하지 않습니다(FACTS 7).
    fields = {
        "GPU": [_gpu_text(r.env) for r in runs],
        "드라이버 / CUDA": [_driver_text(r.env) for r in runs],
        "torch": [_pkg(r.env, "torch") for r in runs],
        "transformers": [_pkg(r.env, "transformers") for r in runs],
        "vllm": [_pkg(r.env, "vllm") for r in runs],
        "backend": [cfg_get(r, "backend") for r in runs],
        "template": [cfg_get(r, "template") for r in runs],
        "seed": [cfg_get(r, "seed") for r in runs],
        "모델 revision": [
            (r.env.get("model") or {}).get("revision") if isinstance(r.env.get("model"), dict) else None
            for r in runs
        ],
        "데이터셋 revision": [
            (r.env.get("dataset") or {}).get("revision") if isinstance(r.env.get("dataset"), dict) else None
            for r in runs
        ],
    }
    diff_rows = []
    differing_keys = []
    members = [r.member for r in runs]
    for key, values in fields.items():
        uniq = {str(v) for v in values}
        same = len(uniq) == 1
        if not same:
            differing_keys.append(key)
        # 값 자체에 " / " 가 들어갈 수 있으므로(드라이버 문자열) 팀원 이름을 붙여 줄바꿈으로 나눕니다.
        detail = "<br>".join(f"{m}: {v}" for m, v in zip(members, values))
        diff_rows.append([key, "동일" if same else "상이", detail])
    lines += [f"{hashes}# {heading_number}.2 환경 일치 여부", ""]
    lines += md_table(["비교 항목", "판정", "팀원별 값"], diff_rows)
    lines.append("")

    # 환경이 다르면 '노이즈' 논리 자체가 성립하지 않으므로 경고를 판정보다 먼저 둡니다(FACTS 7).
    critical = [k for k in differing_keys if k not in ("seed",)]
    if differing_keys:
        lines += [
            "> **경고**: 다음 항목이 팀원 간에 서로 다릅니다: "
            + ", ".join(f"`{k}`" for k in differing_keys)
            + ". FACTS 7 에 따르면 재현성은 동일 하드웨어와 동일 vLLM 버전에서만 성립하므로, "
            "이 상태에서는 점수 차이를 '노이즈'로 설명할 수 없습니다. 먼저 환경을 일치시키십시오. "
            "(`seed` 는 의도적으로 다르게 두어도 됩니다 — 오히려 분산을 확인하는 데 도움이 됩니다.)",
            "",
        ]

    spread = (max(accs) - min(accs)) if len(accs) >= 2 else None
    if spread is not None:
        if spread <= 2.0:
            judgement = (
                f"정확도 폭은 {spread:.2f} pp 입니다. FACTS 7 기준 **예상되는 노이즈 범위**이며 "
                f"버그의 증거가 아닙니다."
            )
        elif spread <= DIFF_CI95_PP:
            judgement = (
                f"정확도 폭은 {spread:.2f} pp 입니다. 독립적인 두 실행의 차이에 대한 95 % 구간"
                f"(±{DIFF_CI95_PP} pp) 안에 있으므로 아직 샘플링 노이즈로 설명 가능합니다. "
                f"다만 상한에 가깝다면 예측 비교로 확인해 두는 것이 안전합니다."
            )
        else:
            judgement = (
                f"정확도 폭은 {spread:.2f} pp 로, 95 % 구간(±{DIFF_CI95_PP} pp)을 넘습니다. "
                f"샘플링만으로는 설명되지 않으므로 설정 차이 또는 버그를 의심해야 합니다."
            )
        if critical:
            judgement += (
                f" 단, 위 경고대로 {', '.join('`' + k + '`' for k in critical)} 이(가) 서로 달라 "
                f"이 폭을 순수한 샘플링 분산으로 해석할 수는 없습니다."
            )
        lines += [f"**판정**: {judgement}", ""]

    lines += [
        f"{hashes}# {heading_number}.3 점수 차이를 어떻게 해석해야 하는가",
        "",
        "- 교수님이 권장한 설정(`temperature=0.7`, `top_p=0.8`, `top_k=20`)은 확률적 샘플링이므로 "
        "**팀원 4명의 점수는 반드시 서로 다릅니다**. 비트 단위 재현은 애초에 불가능합니다(FACTS 7).",
        f"- n=900, p=0.674 에서 1문항 = {ONE_SAMPLE_PP} pp, 표준오차 = {SE_PP_AT_N900} pp, "
        f"독립적인 두 실행의 **차이**에 대한 95 % 구간 = ±{DIFF_CI95_PP} pp 입니다. "
        "따라서 **1~2 pp 의 차이는 정상적인 노이즈**이며 원인을 찾으려 시간을 쓸 필요가 없습니다.",
        "- 노이즈인지 버그인지는 **예측을 직접 비교**해서 구분합니다(FACTS 7).",
        "  - 원문 응답 텍스트 차이는 많은데 파싱된 라벨이 뒤집힌 문항은 적다 → **샘플링 노이즈**입니다.",
        "  - 원문 텍스트 차이는 적은데 점수 차이가 크다 → **파서 또는 정답키(데이터 리비전) 버그**입니다.",
        "- 확인 명령:",
        "",
        "```bash",
        "python src/report.py --diff outputs/RUN_A outputs/RUN_B",
        "```",
        "",
        "- vLLM 을 쓰는 경우 재현성을 높이려면 `LLM(seed=...)` 과 `SamplingParams.seed` 를 **둘 다** "
        "지정하고(`SamplingParams.seed` 의 기본값은 None 입니다), "
        "`VLLM_ENABLE_V1_MULTIPROCESSING=0` 을 설정해야 하며, 그래도 동일 하드웨어·동일 vLLM "
        "버전에서만 성립합니다(FACTS 7).",
        "- `transformers.enable_full_determinism()` 은 쓰지 마십시오. `CUDA_LAUNCH_BLOCKING=1` 을 "
        "설정해 모든 CUDA 실행을 직렬화하므로, 과제가 요구하는 소요 시간 표가 무의미해집니다(FACTS 7).",
        "",
    ]
    return lines


def _short(value: Any, length: int = 12) -> str:
    """긴 커밋 SHA 를 표에 넣기 좋게 줄입니다(앞 12자)."""
    if value is None:
        return "N/A"
    text = str(value)
    if len(text) <= length:
        return text
    return text[:length] + "…"


# ---------------------------------------------------------------------------
# 예측 비교 (--diff)
# ---------------------------------------------------------------------------


def render_diff(run_a: Run, run_b: Run) -> list[str]:
    """두 실행의 predictions.jsonl 을 비교해 노이즈와 버그를 구분합니다.

    FACTS 7 의 진단 규칙을 그대로 구현합니다.
      * 원문 텍스트 차이 많음 + 라벨 뒤집힘 적음 -> 샘플링 노이즈
      * 원문 텍스트 차이 적음 + 점수 차이 큼    -> 파서/정답키 버그
    """
    def index(run: Run) -> tuple[dict[str, dict], int]:
        table: dict[str, dict] = {}
        dup = 0
        for row in run.predictions:
            key = row.get("id")
            if key is None:
                continue
            key = str(key)
            if key in table:
                dup += 1
                continue  # 첫 번째 행을 유지합니다(결정적 동작).
            table[key] = row
        return table, dup

    table_a, dup_a = index(run_a)
    table_b, dup_b = index(run_b)

    ids_a = list(table_a)
    common = [i for i in ids_a if i in table_b]  # A 파일 순서를 유지합니다.
    only_a = [i for i in ids_a if i not in table_b]
    only_b = [i for i in table_b if i not in table_a]

    text_diff: list[str] = []
    text_diff_stripped: list[str] = []
    label_flip: list[str] = []
    gold_mismatch: list[str] = []
    same_text_diff_label: list[str] = []
    a_correct_b_wrong: list[str] = []
    a_wrong_b_correct: list[str] = []
    unparseable_either: list[str] = []

    for key in common:
        ra, rb = table_a[key], table_b[key]
        resp_a, resp_b = ra.get("response"), rb.get("response")
        if resp_a != resp_b:
            text_diff.append(key)
            if str(resp_a or "").strip() != str(resp_b or "").strip():
                text_diff_stripped.append(key)
        if ra.get("parsed") != rb.get("parsed"):
            label_flip.append(key)
            if resp_a == resp_b:
                same_text_diff_label.append(key)
        if ra.get("gold") != rb.get("gold"):
            gold_mismatch.append(key)
        ca, cb = bool(ra.get("correct")), bool(rb.get("correct"))
        if ca and not cb:
            a_correct_b_wrong.append(key)
        elif cb and not ca:
            a_wrong_b_correct.append(key)
        if ra.get("unparseable") or rb.get("unparseable"):
            unparseable_either.append(key)

    n_common = len(common)
    acc_a_common = 100.0 * sum(1 for k in common if table_a[k].get("correct")) / n_common if n_common else None
    acc_b_common = 100.0 * sum(1 for k in common if table_b[k].get("correct")) / n_common if n_common else None
    _, _, acc_a_full, _ = stat_block(run_a.metrics.get("overall"))
    _, _, acc_b_full, _ = stat_block(run_b.metrics.get("overall"))
    gap = None if (acc_a_common is None or acc_b_common is None) else acc_b_common - acc_a_common

    def pctof(count: int) -> str:
        if not n_common:
            return "N/A"
        return f"{count} ({100.0 * count / n_common:.1f} %)"

    now_utc = datetime.now(timezone.utc)
    lines = [
        "# 예측 비교 (--diff)",
        "",
        f"- A: `{run_a.path}` (팀원: {run_a.member})",
        f"- B: `{run_b.path}` (팀원: {run_b.member})",
        f"- 생성 시각: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC / {now_utc.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')} KST",
        "",
        "## 1. 비교 대상",
        "",
    ]
    lines += md_table(
        ["항목", "값"],
        [
            ["A 예측 문항 수", len(table_a)],
            ["B 예측 문항 수", len(table_b)],
            ["공통 문항 수", n_common],
            ["A 에만 있는 문항", f"{len(only_a)} ({', '.join(only_a[:5])}{' …' if len(only_a) > 5 else ''})" if only_a else 0],
            ["B 에만 있는 문항", f"{len(only_b)} ({', '.join(only_b[:5])}{' …' if len(only_b) > 5 else ''})" if only_b else 0],
            ["A 중복 id", dup_a],
            ["B 중복 id", dup_b],
        ],
        align=["l", "r"],
    )
    lines.append("")
    if only_a or only_b:
        lines += [
            "> **경고**: 두 실행이 서로 다른 문항 집합을 평가했습니다. `--limit`/`--subjects` 설정이 "
            "달랐거나 데이터 로딩에서 누락이 발생한 것이므로, 점수 비교 전에 이것부터 맞추십시오.",
            "",
        ]

    lines += ["## 2. 차이 집계 (공통 문항 기준)", ""]
    lines += md_table(
        ["항목", "문항 수", "의미"],
        [
            ["원문 응답 텍스트가 다름", pctof(len(text_diff)), "샘플링으로 생성 자체가 달라진 문항"],
            [
                "공백 제거 후에도 다름",
                pctof(len(text_diff_stripped)),
                "앞뒤 공백 차이만인 경우를 제외한 실질적 텍스트 차이",
            ],
            ["파싱된 라벨이 뒤집힘", pctof(len(label_flip)), "채점 결과가 바뀔 수 있는 문항"],
            [
                "원문은 같은데 라벨이 다름",
                pctof(len(same_text_diff_label)),
                "파서 비결정성 또는 무작위 fallback(FACTS 4c) 신호 — 0 이 아니면 반드시 조사",
            ],
            ["정답키(gold)가 다름", pctof(len(gold_mismatch)), "데이터셋 리비전 불일치(FACTS 6) — 최우선 원인"],
            ["A 정답 → B 오답", pctof(len(a_correct_b_wrong)), "-"],
            ["A 오답 → B 정답", pctof(len(a_wrong_b_correct)), "-"],
            [
                "둘 중 하나라도 미파싱",
                pctof(len(unparseable_either)),
                "이 문항들의 라벨 비교는 무작위 추측이 섞여 의미가 약합니다.",
            ],
        ],
        align=["l", "r", "l"],
    )
    lines.append("")

    lines += ["## 3. 점수 비교", ""]
    lines += md_table(
        ["항목", "A", "B", "차이 (B − A)"],
        [
            [
                "전체 정확도 (metrics.json)",
                fmt_pct(acc_a_full),
                fmt_pct(acc_b_full),
                fmt_pp(None if (acc_a_full is None or acc_b_full is None) else acc_b_full - acc_a_full),
            ],
            [
                "공통 문항 정확도 (predictions.jsonl 재계산)",
                fmt_pct(acc_a_common),
                fmt_pct(acc_b_common),
                fmt_pp(gap),
            ],
        ],
        align=["l", "r", "r", "r"],
    )
    lines.append("")

    # 설정 차이
    flat_a = dict(_flatten(run_a.config)) if run_a.config else {}
    flat_b = dict(_flatten(run_b.config)) if run_b.config else {}
    keys = sorted(set(flat_a) | set(flat_b))
    cfg_rows = [[k, flat_a.get(k, "(없음)"), flat_b.get(k, "(없음)")] for k in keys if flat_a.get(k) != flat_b.get(k)]
    lines += ["## 4. config.json 설정 차이", ""]
    if not run_a.config or not run_b.config:
        lines += ["> 한쪽 이상에서 `config.json` 을 찾지 못해 설정 비교를 건너뜁니다.", ""]
    elif cfg_rows:
        lines += md_table(["설정 키", "A", "B"], cfg_rows[:40])
        if len(cfg_rows) > 40:
            lines += ["", f"(차이 {len(cfg_rows)}건 중 40건만 표시했습니다.)"]
        lines += [
            "",
            "> 설정이 다르면 점수 차이는 '노이즈'가 아니라 **다른 실험**입니다. 특히 `template`, "
            "`backend`, `max_pixels`/`min_pixels`, `max_new_tokens`, `seed` 가 다르면 비교 자체가 "
            "성립하지 않습니다.",
            "",
        ]
    else:
        lines += ["두 실행의 설정은 동일합니다(seed 포함). 따라서 차이는 샘플링 또는 구현에서 옵니다.", ""]

    # 라벨 뒤집힘 상세
    lines += ["## 5. 라벨이 뒤집힌 문항 (최대 25건)", ""]
    flip_rows = []
    for key in label_flip[:25]:
        ra, rb = table_a[key], table_b[key]
        flip_rows.append(
            [
                key,
                ra.get("subject"),
                ra.get("gold"),
                ra.get("parsed"),
                rb.get("parsed"),
                "O" if ra.get("correct") else "X",
                "O" if rb.get("correct") else "X",
                "같음" if ra.get("response") == rb.get("response") else "다름",
                "A" if ra.get("unparseable") else ("B" if rb.get("unparseable") else "-"),
            ]
        )
    lines += md_table(
        ["id", "과목", "정답", "A 파싱", "B 파싱", "A 정답?", "B 정답?", "원문", "미파싱"],
        flip_rows,
        align=["l", "l", "l", "l", "l", "c", "c", "c", "c"],
    )
    if len(label_flip) > 25:
        lines += ["", f"(뒤집힌 문항 {len(label_flip)}건 중 25건만 표시했습니다.)"]
    lines.append("")

    if gold_mismatch:
        lines += ["## 5.1 정답키가 다른 문항 (최대 15건)", ""]
        lines += md_table(
            ["id", "A gold", "B gold"],
            [[k, table_a[k].get("gold"), table_b[k].get("gold")] for k in gold_mismatch[:15]],
        )
        lines.append("")

    # 해석
    lines += ["## 6. 해석", ""]
    verdicts: list[str] = []
    if not n_common:
        verdicts.append("공통 문항이 없어 해석할 수 없습니다. 두 실행이 같은 문항 집합을 평가했는지 확인하십시오.")
    else:
        text_ratio = 100.0 * len(text_diff) / n_common
        flip_ratio = 100.0 * len(label_flip) / n_common
        verdicts.append(
            f"공통 {n_common}문항 중 원문 텍스트 차이 {text_ratio:.1f} %, 라벨 뒤집힘 {flip_ratio:.1f} %, "
            f"공통 문항 정확도 차이 {fmt_pp(gap)} 입니다."
        )
        if gold_mismatch:
            verdicts.append(
                f"**정답키가 다른 문항이 {len(gold_mismatch)}건 있습니다. 이것이 최우선 원인입니다.** "
                "두 실행이 서로 다른 데이터셋 리비전을 읽었다는 뜻이므로(FACTS 6), "
                "`--dataset-revision` 을 같은 커밋 SHA 로 고정하고 다시 실행하십시오. "
                "해결 전에는 점수 비교가 무의미합니다."
            )
        if same_text_diff_label:
            verdicts.append(
                f"원문 응답이 **완전히 같은데** 파싱 라벨이 다른 문항이 {len(same_text_diff_label)}건 "
                "있습니다. 생성이 같다면 파싱도 같아야 합니다. 원인은 (1) 공식 파서의 무작위 fallback "
                "(FACTS 4c — 난수 스트림이 문항 순회 순서에 의존), 또는 (2) 파서 구현 차이입니다. "
                "채점 루프 직전에 `random.seed(42)` 를 호출했는지, 문항 순서가 동일한지 확인하십시오."
            )
        if text_ratio >= 30.0 and flip_ratio <= 10.0 and (gap is None or abs(gap) <= DIFF_CI95_PP):
            verdicts.append(
                "원문 텍스트는 많이 다르지만 라벨 뒤집힘은 적고 점수 차이도 95 % 구간 안입니다. "
                "**전형적인 샘플링 노이즈 패턴**입니다(FACTS 7). 버그를 찾을 필요가 없습니다."
            )
        elif text_ratio <= 5.0 and gap is not None and abs(gap) > 2.0:
            verdicts.append(
                "원문 텍스트 차이는 거의 없는데 점수 차이가 큽니다. **파서 또는 정답키(데이터 리비전) "
                "버그의 전형적인 패턴**입니다(FACTS 7). 먼저 위 5절의 뒤집힌 문항들을 눈으로 확인하고, "
                "`parse_multi_choice_response` 와 gold 값을 점검하십시오."
            )
        elif gap is not None and abs(gap) > DIFF_CI95_PP:
            verdicts.append(
                f"점수 차이 {abs(gap):.2f} pp 가 독립 두 실행의 95 % 구간(±{DIFF_CI95_PP} pp)을 "
                "넘습니다. 4절의 설정 차이를 먼저 보고, 설정이 같다면 환경(GPU·드라이버·vllm 버전) "
                "차이를 확인하십시오."
            )
        else:
            verdicts.append(
                f"텍스트 차이 {text_ratio:.1f} %, 라벨 뒤집힘 {flip_ratio:.1f} %, 점수 차이 "
                f"{fmt_pp(gap)} 는 특정 패턴으로 단정하기 어려운 중간 영역입니다. "
                f"점수 차이가 ±{DIFF_CI95_PP} pp 안이라면 노이즈로 보고 넘어가고, "
                "그렇지 않다면 설정과 환경을 비교하십시오."
            )
    lines += [f"- {v}" for v in verdicts]
    lines += [
        "",
        "판정 기준 요약(FACTS 7):",
        "",
        "| 관측 패턴 | 해석 |",
        "| :--- | :--- |",
        "| 텍스트 차이 많음 + 라벨 뒤집힘 적음 | 샘플링 노이즈 (정상) |",
        "| 텍스트 차이 적음 + 점수 차이 큼 | 파서 / 정답키 버그 |",
        "| 정답키 자체가 다름 | 데이터셋 리비전 불일치 |",
        "| 원문 같음 + 라벨 다름 | 파서 비결정성 또는 무작위 fallback |",
        "",
    ]
    return lines


# ---------------------------------------------------------------------------
# 문서 조립
# ---------------------------------------------------------------------------


def prescan(run: Run) -> None:
    """보고서를 그리기 전에 metrics 전체를 한 번 훑어 경고를 모읍니다.

    무결성 점검 절이 문서 앞쪽에서 경고 목록을 렌더링하므로, 그 시점에 모든 경고가
    이미 수집되어 있어야 합니다(뒤쪽 절에서 추가되는 경고는 표준출력에 보이지 않게 됩니다).
    """
    collect_group(run, "by_subject")
    collect_group(run, "by_category")
    for key in ("overall", "multiple_choice", "open_ended"):
        _, _, _, warning = stat_block(run.metrics.get(key))
        if warning:
            run.warnings.append(f"metrics.json {key}: {warning}")
    _published_value(run)


def render_report(run: Run, compares: Sequence[Run] | None = None) -> str:
    """실행 디렉터리 하나(+비교 대상)를 전체 Markdown 보고서로 렌더링합니다."""
    prescan(run)
    lines: list[str] = []
    lines += section_header(run)
    lines += section_integrity(run)
    lines += section_overall(run)
    lines += section_by_category(run)
    lines += section_by_subject(run)
    lines += section_by_type(run)
    lines += section_timing(run)
    lines += section_environment(run)
    lines += section_published_comparison(run)
    if compares:
        lines += render_compare(compares, heading_level=2, heading_number="10")
    lines += [
        "---",
        "",
        f"*본 문서는 `src/report.py` ({SCHEMA_NOTE}) 가 자동 생성했습니다. "
        f"수치의 출처는 `{run.path}` 의 metrics.json / timing.json / env.json / predictions.jsonl 입니다.*",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_compare_only(runs: Sequence[Run]) -> str:
    """--compare 만 주어졌을 때의 단독 비교 문서."""
    now_utc = datetime.now(timezone.utc)
    lines = [
        "# 팀원 간 MMMU 베이스라인 결과 비교",
        "",
        f"- 생성 시각: {now_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC / {now_utc.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')} KST",
        f"- 비교 대상 실행 수: {len(runs)}",
        "",
    ]
    lines += render_compare(runs, heading_level=2, heading_number="1")
    return "\n".join(lines).rstrip() + "\n"


def _write_output(text: str, out: str | None) -> None:
    """--out 이 있으면 파일로, 없으면 표준출력으로 내보냅니다."""
    if out:
        path = Path(out).expanduser()
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"보고서를 저장했습니다: {path}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def _emit_warnings(runs: Iterable[Run]) -> None:
    """수집된 경고를 중복 없이 stderr 로 내보냅니다(표준출력은 문서 전용)."""
    for run in runs:
        for warning in dict.fromkeys(run.warnings):
            print(f"[경고] {run.label}: {warning}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


EPILOG = """예시:
  # 제출용 보고서 생성
  python src/report.py --run-dir outputs/RUN --out assignment/assignment1_results.md

  # 내 결과 + 팀원 결과 비교표까지 한 문서로
  python src/report.py --run-dir outputs/RUN_ME --compare outputs/RUN_A outputs/RUN_B outputs/RUN_C

  # 팀원 비교표만
  python src/report.py --compare outputs/RUN_A outputs/RUN_B

  # 두 실행의 예측을 직접 비교해 노이즈와 버그를 구분
  python src/report.py --diff outputs/RUN_A outputs/RUN_B
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report.py",
        description="MMMU 베이스라인 실행 디렉터리를 제출용 Markdown 보고서로 변환합니다.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-dir",
        metavar="DIR",
        help="보고서를 만들 실행 디렉터리(metrics.json 등이 있는 곳).",
    )
    parser.add_argument(
        "--out",
        metavar="FILE",
        help="결과 Markdown 을 저장할 경로. 생략하면 표준출력으로 보냅니다.",
    )
    parser.add_argument(
        "--compare",
        metavar="DIR",
        nargs="+",
        help="팀원 비교표에 포함할 실행 디렉터리들. --run-dir 과 함께 쓰면 해당 실행이 첫 행이 됩니다.",
    )
    parser.add_argument(
        "--diff",
        metavar=("RUN_A", "RUN_B"),
        nargs=2,
        help="두 실행의 predictions.jsonl 을 비교합니다(원문 텍스트 차이 vs 파싱 라벨 뒤집힘).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.diff and (args.run_dir or args.compare):
        parser.error("--diff 는 단독으로 사용합니다. --run-dir / --compare 와 함께 쓸 수 없습니다.")
    if not args.diff and not args.run_dir and not args.compare:
        parser.error("--run-dir, --compare, --diff 중 하나는 반드시 지정해야 합니다.")

    try:
        if args.diff:
            # 예측 비교에는 predictions.jsonl 이 반드시 필요합니다(없으면 명시적 실패).
            run_a = load_run(args.diff[0], need_predictions=True)
            run_b = load_run(args.diff[1], need_predictions=True)
            text = "\n".join(render_diff(run_a, run_b)).rstrip() + "\n"
            # 경고는 렌더링이 끝난 뒤에 출력합니다(렌더링 중에 추가되는 경고까지 포함하기 위함).
            _emit_warnings([run_a, run_b])
            _write_output(text, args.out)
            return 0

        compare_runs: list[Run] = []
        seen: set[Path] = set()
        main_run: Run | None = None

        if args.run_dir:
            main_run = load_run(args.run_dir)
            compare_runs.append(main_run)
            seen.add(main_run.path.resolve())

        for directory in args.compare or []:
            run = load_run(directory)
            resolved = run.path.resolve()
            if resolved in seen:
                continue  # 같은 디렉터리를 두 번 넣어도 행이 중복되지 않게 합니다.
            seen.add(resolved)
            compare_runs.append(run)

        if main_run is None:
            text = render_compare_only(compare_runs)
        else:
            extra = compare_runs if len(compare_runs) > 1 else None
            text = render_report(main_run, extra)
        _emit_warnings(compare_runs)
        _write_output(text, args.out)
        return 0
    except ReportError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("[중단] 사용자가 중단했습니다.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

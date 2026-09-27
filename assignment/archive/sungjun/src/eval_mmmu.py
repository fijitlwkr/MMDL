#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MMMU validation 베이스라인 평가 스크립트 (Qwen/Qwen3-VL-4B-Instruct).

교수님 슬라이드 15의 요구사항 중 이 파일이 직접 담당하는 항목입니다.
  * "MMMU 데이터 경로를 입력으로 받는 평가 스크립트"  -> --data-path (필수 인자)
  * 과목(subject)별 / 카테고리(category)별 정확도      -> metrics.json
  * 전체 소요 시간 + 과목별/카테고리별 소요 시간       -> timing.json
  * 실험 환경 기록                                     -> env.json / ENVIRONMENT.md
  * 공개 점수 67.4와의 비교                            -> metrics.json.published_reference

설계 원칙 (이 스크립트는 성적이 걸린 코드이므로 아래를 타협하지 않습니다)
  1) 조용한 실패 금지. 프롬프트가 컨텍스트를 넘치거나 이미지 개수 제한을 넘기면
     추론 중간에 vLLM이 요청을 거부하여 해당 문항이 0점으로 조용히 기록되는 사고가
     납니다. 그래서 추론 전에 전체 900문항의 vision/prompt 토큰을 미리 계산하고
     (--dry-run 은 이 단계만 수행), 문제가 있으면 위반 id 목록과 함께 즉시 중단합니다.
  2) 적용하지 않은 설정을 보고서에 적지 않습니다. presence_penalty 는 transformers 에
     존재하지 않는 인자이므로(FACTS 2), hf 백엔드에서는 vLLM 의 가산식을 재현한
     PresencePenaltyLogitsProcessor 를 직접 적용하고 "어떤 메커니즘으로 적용했는지"를
     config.json 에 기록합니다.
  3) 환경 기록(env.json)은 모델 로드 이전에 기록합니다. 또한 model_load_s 를 따로
     측정하여 알파벳순 첫 과목(Accounting)이 엔진 시작 시간을 뒤집어쓰지 않게 합니다.
  4) 중단 복구(resume). --out 에 predictions.jsonl 이 이미 있으면 끝난 id 는 건너뛰고
     이어서 추가합니다. 대여 GPU에서 40분짜리 실행이 접속 끊김으로 날아가면 안 됩니다.

실행 예시
  python src/eval_mmmu.py --data-path /workspace/data/MMMU --backend vllm
  python src/eval_mmmu.py --data-path MMMU/MMMU --dry-run
  python src/eval_mmmu.py --data-path /workspace/data/MMMU --backend hf --limit 8
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import hashlib
import json
import logging
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 모듈 경로 부트스트랩
# src/ 를 sys.path 에 넣어 평범한 모듈로 import 합니다(INTERFACES 규약).
# `python src/eval_mmmu.py` 와 `python -m src.eval_mmmu` 둘 다 동작해야 합니다.
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
_SRC_DIR = _THIS_FILE.parent
REPO_ROOT = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    import mmmu_data
    import mmmu_parser
    import mmmu_prompt
    import capture_env
except ImportError as exc:  # 같은 src/ 안의 동료 모듈이 없으면 바로 알려줍니다.
    sys.stderr.write(
        "[치명적] src/ 내부 모듈을 import 할 수 없습니다: {}\n"
        "        mmmu_data.py / mmmu_prompt.py / mmmu_parser.py / capture_env.py 가\n"
        "        {} 안에 모두 있는지 확인하세요.\n".format(exc, _SRC_DIR)
    )
    raise

LOG = logging.getLogger("eval_mmmu")

# ---------------------------------------------------------------------------
# 상수 (모두 FACTS.md 에서 검증된 값. 기억에 의존한 숫자를 쓰지 않습니다.)
# ---------------------------------------------------------------------------

# FACTS 1: Qwen3-VL-4B-Instruct vision_config 는 patch_size=16, spatial_merge_size=2 이므로
# smart_resize 의 factor 는 16*2 = 32 입니다. Qwen2/2.5-VL 의 28 이 아닙니다.
SMART_RESIZE_FACTOR = 32
# 따라서 visual token 1개가 덮는 픽셀 수는 32*32 = 1024 입니다 (Qwen2.5-VL 은 784).
PIXELS_PER_VISION_TOKEN = SMART_RESIZE_FACTOR * SMART_RESIZE_FACTOR
# Qwen 공식 smart_resize 의 종횡비 상한. 이보다 찌그러진 이미지는 예외를 던집니다.
MAX_ASPECT_RATIO = 200

# FACTS 0 슬라이드 16의 교수님 권장값. "N*28*28" 표기를 그대로 기본값으로 둡니다.
DEFAULT_MIN_PIXELS_SPEC = "1280*28*28"   # = 1,003,520 px -> 980 visual tokens (하한)
DEFAULT_MAX_PIXELS_SPEC = "5120*28*28"   # = 4,014,080 px -> 3,920 visual tokens (상한)

# FACTS 6: main 은 움직이는 포인터이므로 커밋 sha 를 기본값으로 고정합니다.
DEFAULT_MODEL = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DEFAULT_DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"

# FACTS 4: validation 은 이미지 최대 5장(image_6/7 컬럼은 항상 null).
DEFAULT_LIMIT_MM_IMAGES = 5

# FACTS 4: 900 = 847 multiple-choice + 53 open. 숫자가 다르면 데이터가 바뀐 것입니다.
EXPECTED_VALIDATION_N = 900
EXPECTED_VALIDATION_MC = 847
EXPECTED_VALIDATION_OPEN = 53

# FACTS 0 / metrics.json 규약.
PUBLISHED_MMMU_VAL = 67.4
PUBLISHED_SOURCE = "Qwen3-VL technical report arXiv:2511.21631"

# FACTS 4c: 공식 파서는 파싱 실패 시 random.choice 로 찍습니다. 그 난수 스트림을
# 고정하기 위해 채점 루프 직전에 이 시드를 호출합니다. (공식 eval_utils.py 와 동일한 42)
OFFICIAL_PARSER_SEED = 42

CONFIG_SCHEMA_VERSION = 1
PREDICTION_KEYS = (
    "id", "subject", "category", "question_type", "n_images", "image_indices",
    "vision_tokens", "prompt_tokens", "output_tokens", "response", "parsed",
    "gold", "correct", "unparseable", "latency_s",
)


# ---------------------------------------------------------------------------
# 작은 유틸
# ---------------------------------------------------------------------------

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _i(n: Any) -> str:
    """큰 정수를 천 단위로 끊어 읽기 쉽게 만듭니다."""
    try:
        return "{:,}".format(int(n))
    except Exception:
        return str(n)


def _hms(seconds: Optional[float]) -> str:
    if seconds is None:
        return "-"
    seconds = float(seconds)
    h, rem = divmod(int(round(seconds)), 3600)
    m, s = divmod(rem, 60)
    if h:
        return "{}시간 {}분 {}초".format(h, m, s)
    if m:
        return "{}분 {}초".format(m, s)
    return "{:.1f}초".format(seconds)


def _acc(correct: int, n: int) -> float:
    """정확도는 0..1 분수로 저장합니다(공식 MMMU eval 과 동일한 스케일).

    보고서에서 67.4 와 비교할 때는 100을 곱해야 합니다. 이 스케일은
    config.json 의 metrics_accuracy_scale 필드에도 명시해 둡니다.
    """
    if n <= 0:
        return 0.0
    return round(correct / n, 6)


def _stable_seed(text: str) -> int:
    """id 문자열로부터 재현 가능한 정수 시드를 만듭니다.

    생성 단계에서 쓰는 '임시 채점'은 난수 폴백(FACTS 4c)을 건드리므로,
    전역 스트림을 더럽히지 않도록 문항별 고정 시드를 씁니다. 최종 점수는
    반드시 random.seed(42) 이후의 일괄 재채점 결과만 사용합니다.
    """
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def _json_dump(obj: Any, path: Path) -> None:
    """JSON 을 원자적으로(임시파일 + replace) 씁니다. 중간에 죽어도 파일이 깨지지 않습니다."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)


def setup_logging(out_dir: Path, verbose: bool = False) -> None:
    """stdout 과 run.log 에 동시에 기록합니다.

    핸들러별로 레벨을 다르게 둡니다. run.log 는 항상 DEBUG 까지 받으므로 문항 900건의
    vision/prompt 토큰 같은 상세 기록이 모두 남고(과제 요구사항), 화면에는 INFO 만 나와
    읽을 수 있습니다. run.log 는 이어하기를 위해 append 모드입니다.
    """
    LOG.handlers.clear()
    LOG.setLevel(logging.DEBUG)
    LOG.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    stream = logging.StreamHandler(stream=sys.stdout)
    stream.setFormatter(fmt)
    stream.setLevel(logging.DEBUG if verbose else logging.INFO)
    LOG.addHandler(stream)

    fileh = logging.FileHandler(out_dir / "run.log", mode="a", encoding="utf-8")
    fileh.setFormatter(fmt)
    fileh.setLevel(logging.DEBUG)
    LOG.addHandler(fileh)


def _banner(title: str) -> None:
    LOG.info("=" * 78)
    LOG.info(title)
    LOG.info("=" * 78)


# ---------------------------------------------------------------------------
# 픽셀 예산 / smart_resize (FACTS 1, FACTS 3)
# ---------------------------------------------------------------------------

_PIXEL_SPEC_RE = re.compile(r"^\d+(\*\d+)*$")


def parse_pixel_spec(spec: str) -> int:
    """"1280*28*28" 같은 곱셈 표기 또는 생 정수("1003520")를 px 값으로 변환합니다.

    교수님 슬라이드가 곱셈 표기를 쓰므로 그 표기를 그대로 CLI 에 받아들입니다.
    eval() 은 쓰지 않습니다(임의 코드 실행 방지).
    """
    if isinstance(spec, int):
        return int(spec)
    cleaned = str(spec).strip().replace(" ", "").replace("_", "").replace(",", "")
    if not cleaned or not _PIXEL_SPEC_RE.match(cleaned):
        raise ValueError(
            "픽셀 값 표기를 해석할 수 없습니다: {!r} "
            "(허용 형식: 1280*28*28 또는 1003520)".format(spec)
        )
    value = 1
    for part in cleaned.split("*"):
        value *= int(part)
    if value <= 0:
        raise ValueError("픽셀 값은 0보다 커야 합니다: {!r}".format(spec))
    return value


def pixels_to_tokens(pixels: int, factor: int = SMART_RESIZE_FACTOR) -> Tuple[int, bool]:
    """픽셀 예산을 visual token 환산값으로 바꿉니다. (토큰수, 정확히 나누어떨어지는지)"""
    per_token = factor * factor
    return pixels // per_token, (pixels % per_token == 0)


def _round_by_factor(value: float, factor: int) -> int:
    return int(round(value / factor) * factor)


def _ceil_by_factor(value: float, factor: int) -> int:
    return int(math.ceil(value / factor) * factor)


def _floor_by_factor(value: float, factor: int) -> int:
    return int(math.floor(value / factor) * factor)


def smart_resize(
    height: int,
    width: int,
    factor: int = SMART_RESIZE_FACTOR,
    min_pixels: int = 0,
    max_pixels: int = 1 << 62,
) -> Tuple[int, int]:
    """Qwen 공식 smart_resize 재현. (resized_height, resized_width) 를 돌려줍니다.

    FACTS 1 의 규칙 그대로입니다: 각 변을 factor(=32) 의 배수로 맞추고,
    max_pixels 로 줄일 때는 floor, min_pixels 로 올릴 때는 ceil 을 씁니다.
    이 함수가 틀리면 컨텍스트 사전 점검 전체가 무의미해지므로 FACTS 3 의 실측값
    (1557x2057 -> 3136 tok, 1586x1530 -> 2400 tok, 2560x2133 -> 5360 tok)으로
    검증했습니다.
    """
    if height <= 0 or width <= 0:
        raise ValueError("이미지 크기가 비정상입니다: {}x{}".format(width, height))
    if max(height, width) / min(height, width) > MAX_ASPECT_RATIO:
        raise ValueError(
            "종횡비가 {} 를 초과합니다({}x{}). Qwen smart_resize 가 거부하는 입력입니다.".format(
                MAX_ASPECT_RATIO, width, height
            )
        )
    h_bar = max(factor, _round_by_factor(height, factor))
    w_bar = max(factor, _round_by_factor(width, factor))
    if h_bar * w_bar > max_pixels:
        beta = math.sqrt((height * width) / max_pixels)
        h_bar = max(factor, _floor_by_factor(height / beta, factor))
        w_bar = max(factor, _floor_by_factor(width / beta, factor))
    elif h_bar * w_bar < min_pixels:
        beta = math.sqrt(min_pixels / (height * width))
        h_bar = _ceil_by_factor(height * beta, factor)
        w_bar = _ceil_by_factor(width * beta, factor)
    return h_bar, w_bar


def vision_tokens_for_image(
    width: int,
    height: int,
    factor: int,
    min_pixels: int,
    max_pixels: int,
) -> Tuple[int, int, int]:
    """이미지 1장이 차지하는 visual token 수. (tokens, resized_w, resized_h)

    FACTS 1: tokens = (resized_h/32) * (resized_w/32).
    <|vision_start|>/<|vision_end|> 2 토큰은 채팅 템플릿 문자열 쪽에서 이미 세어지므로
    여기서는 더하지 않습니다(FACTS 3 의 '문항별 vision token' 실측값과 같은 정의).
    """
    r_h, r_w = smart_resize(height, width, factor=factor, min_pixels=min_pixels, max_pixels=max_pixels)
    return (r_h // factor) * (r_w // factor), r_w, r_h


# ---------------------------------------------------------------------------
# 프로세서 / 픽셀 예산 해석 (FACTS 1 의 함정 처리)
# ---------------------------------------------------------------------------

@dataclass
class PixelBudget:
    """해석된 픽셀 예산과 '실제로 프로세서에 박힌 값'을 함께 들고 다닙니다."""
    min_pixels_spec: str
    max_pixels_spec: str
    min_pixels: int
    max_pixels: int
    min_tokens: int
    max_tokens: int
    factor: int
    size_requested: Dict[str, int]
    size_resolved: Dict[str, Any]
    size_forced: bool
    precount_min_pixels: int
    precount_max_pixels: int

    def to_json(self) -> Dict[str, Any]:
        return {
            "min_pixels_spec": self.min_pixels_spec,
            "max_pixels_spec": self.max_pixels_spec,
            "min_pixels": self.min_pixels,
            "max_pixels": self.max_pixels,
            "min_vision_tokens_per_image": self.min_tokens,
            "max_vision_tokens_per_image": self.max_tokens,
            "smart_resize_factor": self.factor,
            "pixels_per_vision_token": self.factor * self.factor,
            "processor_size_requested": self.size_requested,
            "processor_size_resolved": self.size_resolved,
            "processor_size_forced": self.size_forced,
            "precount_min_pixels": self.precount_min_pixels,
            "precount_max_pixels": self.precount_max_pixels,
            "note": (
                "Qwen3-VL 은 patch_size 16 * spatial_merge_size 2 = 32 그리드이므로 "
                "visual token 1개가 32x32=1024 px 를 덮습니다. 교수님 슬라이드의 '*28*28' 은 "
                "Qwen2.5-VL 관례이며 Qwen3-VL 에서는 토큰 수를 뜻하지 않습니다."
            ),
        }


def announce_pixel_budget(budget_min: int, budget_max: int, min_spec: str, max_spec: str) -> None:
    """시작 시점에 '교수님 숫자 -> 실제 토큰 환산' 을 한국어로 분명히 출력합니다(FACTS 1)."""
    min_tok, min_exact = pixels_to_tokens(budget_min)
    max_tok, max_exact = pixels_to_tokens(budget_max)
    _banner("픽셀 예산(min_pixels / max_pixels) 해석 결과")
    LOG.info("Qwen3-VL-4B-Instruct: patch_size=16, spatial_merge_size=2 -> smart_resize factor = %d", SMART_RESIZE_FACTOR)
    LOG.info("즉 visual token 1개 = %dx%d = %s px (Qwen2.5-VL 의 28x28=784 가 아님)",
             SMART_RESIZE_FACTOR, SMART_RESIZE_FACTOR, _i(PIXELS_PER_VISION_TOKEN))
    LOG.info("--min-pixels %s = %s px  ->  이미지 1장 최소 %s visual tokens%s",
             min_spec, _i(budget_min), _i(min_tok), "" if min_exact else " (나누어떨어지지 않아 내림)")
    LOG.info("--max-pixels %s = %s px  ->  이미지 1장 최대 %s visual tokens%s",
             max_spec, _i(budget_max), _i(max_tok), "" if max_exact else " (나누어떨어지지 않아 내림)")
    LOG.info("주의: 교수님 표기 1280*28*28 / 5120*28*28 은 '1280 / 5120 토큰' 을 의미하지 않습니다.")
    LOG.info("      Qwen3-VL 에서는 각각 %s / %s 토큰으로 해석됩니다. 보고서에는 이 환산값을 쓰십시오.",
             _i(min_tok), _i(max_tok))


def resolve_processor(
    model_id: str,
    revision: Optional[str],
    min_pixels: int,
    max_pixels: int,
    min_spec: str,
    max_spec: str,
) -> Tuple[Any, Any, PixelBudget]:
    """AutoProcessor 를 픽셀 예산과 함께 로드하고, '실제로 반영되었는지' 검증합니다.

    FACTS 1 의 함정: transformers <= 4.57.1 에서는 AutoProcessor.from_pretrained(max_pixels=...)
    가 조용히 무시되었습니다(issue #41955 / PR #41997). 그래서
      (a) 이식성 있는 size={"shortest_edge":..., "longest_edge":...} 형태로도 같이 넘기고,
      (b) 로드 후 processor.image_processor.size 를 되읽어 출력하고,
      (c) 값이 다르면 경고를 띄우고 강제로 덮어씁니다.
    보고서에는 '수식' 이 아니라 이 되읽은 dict 를 기재해야 합니다.
    trust_remote_code 는 쓰지 않습니다(FACTS 5: 아키텍처가 기본 등록되어 있음).
    """
    from transformers import AutoProcessor  # 지연 import: --help 를 노트북에서도 빠르게 띄우기 위함

    size_requested = {"shortest_edge": int(min_pixels), "longest_edge": int(max_pixels)}
    LOG.info("AutoProcessor 로드: %s (revision=%s)", model_id, revision)
    processor = AutoProcessor.from_pretrained(
        model_id,
        revision=revision,
        # size 와 min/max_pixels 를 같은 값으로 '둘 다' 넘깁니다. 어느 경로가 우선하더라도
        # 결과 예산이 동일하므로 모순이 생기지 않고, 버전별 무시 버그를 함께 회피합니다.
        size=size_requested,
        min_pixels=int(min_pixels),
        max_pixels=int(max_pixels),
    )

    image_processor = getattr(processor, "image_processor", None)
    if image_processor is None:
        raise RuntimeError("processor.image_processor 가 없습니다. Qwen3-VL 프로세서가 아닙니다.")

    resolved = dict(getattr(image_processor, "size", {}) or {})
    forced = False
    if resolved.get("shortest_edge") != int(min_pixels) or resolved.get("longest_edge") != int(max_pixels):
        LOG.warning("-" * 78)
        LOG.warning("[경고] 프로세서에 반영된 픽셀 예산이 요청값과 다릅니다.")
        LOG.warning("       요청: %s", size_requested)
        LOG.warning("       반영: %s", resolved)
        LOG.warning("       FACTS 1 의 알려진 함정입니다(transformers <= 4.57.1 에서 max_pixels 무시).")
        LOG.warning("       image_processor.size 를 강제로 덮어써서 요청값을 실제로 적용합니다.")
        LOG.warning("-" * 78)
        image_processor.size = dict(size_requested)
        for attr, value in (("min_pixels", int(min_pixels)), ("max_pixels", int(max_pixels))):
            if hasattr(image_processor, attr):
                setattr(image_processor, attr, value)
        resolved = dict(getattr(image_processor, "size", {}) or {})
        forced = True

    # smart_resize factor 를 프로세서/설정에서 실제로 읽어 교차검증합니다.
    factor = _resolve_factor(model_id, revision, image_processor)

    min_tok, _ = pixels_to_tokens(min_pixels, factor)
    max_tok, _ = pixels_to_tokens(max_pixels, factor)

    # 사전 토큰 계산은 '보수적으로' 합니다. 요청값과 반영값 중 더 큰 상한, 더 작은 하한을
    # 써서 컨텍스트 초과를 과소평가하지 않습니다.
    precount_max = max(int(max_pixels), int(resolved.get("longest_edge") or 0))
    precount_min = min(int(min_pixels), int(resolved.get("shortest_edge") or min_pixels))

    LOG.info("되읽은 processor.image_processor.size = %s", resolved)
    LOG.info("되읽은 예산의 토큰 환산 = %s .. %s visual tokens / image", _i(min_tok), _i(max_tok))
    if precount_max != int(max_pixels) or precount_min != int(min_pixels):
        LOG.warning("사전 토큰 계산에는 보수적 예산(min=%s, max=%s px)을 사용합니다.",
                    _i(precount_min), _i(precount_max))

    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)

    budget = PixelBudget(
        min_pixels_spec=min_spec,
        max_pixels_spec=max_spec,
        min_pixels=int(min_pixels),
        max_pixels=int(max_pixels),
        min_tokens=int(min_tok),
        max_tokens=int(max_tok),
        factor=factor,
        size_requested=size_requested,
        size_resolved=resolved,
        size_forced=forced,
        precount_min_pixels=precount_min,
        precount_max_pixels=precount_max,
    )
    return processor, tokenizer, budget


def _resolve_factor(model_id: str, revision: Optional[str], image_processor: Any) -> int:
    """patch_size * merge_size 를 실제 체크포인트에서 읽어 factor=32 가정을 검증합니다."""
    candidates = []
    ps = getattr(image_processor, "patch_size", None)
    ms = getattr(image_processor, "merge_size", None)
    if isinstance(ps, int) and isinstance(ms, int):
        candidates.append(("image_processor", ps * ms))
    try:
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(model_id, revision=revision)
        vcfg = getattr(cfg, "vision_config", None)
        vps = getattr(vcfg, "patch_size", None)
        vms = getattr(vcfg, "spatial_merge_size", None)
        if isinstance(vps, int) and isinstance(vms, int):
            candidates.append(("config.vision_config", vps * vms))
    except Exception as exc:  # 설정을 못 읽어도 치명적이지는 않습니다. 로그만 남깁니다.
        LOG.debug("AutoConfig 로 factor 교차검증 실패: %s", exc)

    for source, value in candidates:
        LOG.info("factor 교차검증: %s -> patch_size*merge_size = %d", source, value)

    values = {v for _, v in candidates}
    if not values:
        LOG.warning("patch_size/merge_size 를 읽지 못했습니다. FACTS 1 의 factor=%d 를 사용합니다.",
                    SMART_RESIZE_FACTOR)
        return SMART_RESIZE_FACTOR
    if len(values) > 1:
        LOG.warning("factor 후보가 여러 개입니다(%s). 가장 큰 값을 보수적으로 사용합니다.", sorted(values))
    factor = max(values)
    if factor != SMART_RESIZE_FACTOR:
        LOG.warning("[중요] 실제 factor(%d) 가 FACTS 1 의 32 와 다릅니다. 체크포인트가 바뀌었을 수 있습니다. "
                    "토큰 환산값을 보고서에 그대로 옮기기 전에 확인하십시오.", factor)
    return factor


def _apply_chat_template(processor: Any, messages: List[dict]) -> str:
    """채팅 템플릿을 적용해 '이미지 자리표시자가 들어간' 프롬프트 문자열을 만듭니다.

    Qwen3-VL Instruct 템플릿은 기본 system prompt 가 없고 "<|im_start|>assistant\\n" 으로
    끝납니다(FACTS 11). enable_thinking 같은 인자는 존재하지 않습니다.
    """
    fn = getattr(processor, "apply_chat_template", None)
    if fn is None:
        tok = getattr(processor, "tokenizer", None)
        fn = getattr(tok, "apply_chat_template", None) if tok is not None else None
    if fn is None:
        raise RuntimeError("프로세서에서 apply_chat_template 을 찾을 수 없습니다.")
    return fn(messages, tokenize=False, add_generation_prompt=True)


def _count_image_placeholders(processor: Any, tokenizer: Any, text: str) -> Tuple[int, str]:
    """렌더된 프롬프트에 들어간 이미지 자리표시자 개수를 셉니다. (개수, 사용한 토큰 문자열)"""
    candidates = []
    for obj in (processor, tokenizer, getattr(processor, "image_processor", None)):
        token = getattr(obj, "image_token", None)
        if isinstance(token, str) and token:
            candidates.append(token)
    candidates.extend(["<|image_pad|>", "<|vision_start|>"])
    seen = set()
    for token in candidates:
        if token in seen:
            continue
        seen.add(token)
        count = text.count(token)
        if count:
            return count, token
    return 0, candidates[0] if candidates else "<|image_pad|>"


# ---------------------------------------------------------------------------
# 추론 요청 준비 + 컨텍스트 사전 점검 (FACTS 3, FACTS 4a)
# ---------------------------------------------------------------------------

@dataclass
class PreparedRequest:
    sample: Any
    prompt_text: str          # <image N> 마커가 살아있는 원본 프롬프트
    letters: List[str]
    rendered: str             # 채팅 템플릿 적용 후, 이미지 자리표시자가 들어간 문자열
    mm_images: List[Any]      # 자리표시자 순서와 1:1 로 맞춘 PIL 이미지 (반복 참조 포함)
    n_mm_items: int           # 멀티모달 아이템 수 = 마커 '등장 횟수' (고유 이미지 수가 아님)
    vision_tokens: int
    prompt_tokens: int
    per_image: List[Dict[str, int]] = field(default_factory=list)

    @property
    def sample_id(self) -> str:
        return self.sample.id


def prepare_requests(
    samples: Sequence[Any],
    processor: Any,
    tokenizer: Any,
    template: str,
    budget: PixelBudget,
) -> List[PreparedRequest]:
    """900문항 전체의 프롬프트를 만들고 vision/prompt 토큰을 미리 계산합니다.

    여기서 조용히 넘어가면 안 되는 것들
      * build_messages 가 마커에 대응하는 이미지를 못 찾으면 예외를 던집니다(규약).
        그 예외를 잡아서 id 와 함께 즉시 중단합니다.
      * 렌더된 문자열의 자리표시자 개수와 우리가 모은 이미지 개수가 다르면 중단합니다.
        (이 둘이 어긋나면 vLLM 이 런타임에 거부하거나, 더 나쁘면 엉뚱한 이미지가 붙습니다.)
      * FACTS 4a: validation_Math_19 는 마커 순서가 [1,2,1,1,2] 로 같은 이미지를 4번 참조합니다.
        멀티모달 아이템 수는 '등장 횟수' 5개이며 vision token 도 5번 계산됩니다.
    """
    prepared: List[PreparedRequest] = []
    failures: List[str] = []
    for sample in samples:
        try:
            prompt_text, letters = mmmu_prompt.build_prompt(sample, template)
            messages = mmmu_prompt.build_messages(sample, prompt_text)
        except Exception as exc:
            failures.append("{}: 프롬프트 생성 실패 ({}: {})".format(sample.id, type(exc).__name__, exc))
            continue

        # 규약상 sample.images 는 '참조된 이미지만' 담고 순서는 마커 인덱스 순입니다.
        # FACTS 4a 의 고아 이미지(validation_Pharmacy_22 등)가 섞여 들어오면 토큰 수와
        # 답이 달라지므로, 길이 불일치를 여기서 잡습니다.
        n_unique = len(getattr(sample, "image_indices", []) or [])
        if len(getattr(sample, "images", []) or []) != n_unique:
            failures.append(
                "{}: images {}개 != image_indices {}개. 참조되지 않은 이미지가 섞였을 수 있습니다.".format(
                    sample.id, len(sample.images or []), n_unique))
            continue

        blocks = []
        for message in messages:
            content = message.get("content")
            if isinstance(content, list):
                blocks.extend(content)
        mm_images = [blk.get("image") for blk in blocks if blk.get("type") == "image"]
        if any(img is None for img in mm_images):
            failures.append("{}: content 의 image 블록에 PIL 객체가 없습니다.".format(sample.id))
            continue

        try:
            rendered = _apply_chat_template(processor, messages)
        except Exception as exc:
            failures.append("{}: 채팅 템플릿 적용 실패 ({}: {})".format(sample.id, type(exc).__name__, exc))
            continue

        n_placeholder, token_str = _count_image_placeholders(processor, tokenizer, rendered)
        if n_placeholder != len(mm_images):
            failures.append(
                "{}: 자리표시자({}) {}개 != 전달 이미지 {}개. 마커-이미지 매핑이 깨졌습니다.".format(
                    sample.id, token_str, n_placeholder, len(mm_images))
            )
            continue

        per_image: List[Dict[str, int]] = []
        vision_tokens = 0
        bad_image = None
        for img in mm_images:
            try:
                width, height = img.size  # PIL 은 (width, height) 순서입니다. 디코딩은 일어나지 않습니다.
                tokens, r_w, r_h = vision_tokens_for_image(
                    width, height, budget.factor,
                    budget.precount_min_pixels, budget.precount_max_pixels,
                )
            except Exception as exc:
                bad_image = "{}: 이미지 토큰 계산 실패 ({}: {})".format(sample.id, type(exc).__name__, exc)
                break
            per_image.append({"w": int(width), "h": int(height),
                              "resized_w": int(r_w), "resized_h": int(r_h), "tokens": int(tokens)})
            vision_tokens += int(tokens)
        if bad_image:
            failures.append(bad_image)
            continue

        # 텍스트 토큰: 템플릿이 이미 특수토큰을 포함하므로 add_special_tokens=False.
        # 렌더 문자열에는 이미지 1장당 자리표시자가 1토큰씩 들어있으므로 그만큼 빼고
        # 실제 vision token 수를 더합니다. <|vision_start|>/<|vision_end|> 는 문자열에
        # 이미 포함되어 있으므로 따로 더하지 않습니다(FACTS 3 의 '2 토큰/이미지'에 해당).
        text_ids = tokenizer(rendered, add_special_tokens=False)["input_ids"]
        prompt_tokens = len(text_ids) - len(mm_images) + vision_tokens

        prepared.append(PreparedRequest(
            sample=sample,
            prompt_text=prompt_text,
            letters=list(letters),
            rendered=rendered,
            mm_images=list(mm_images),
            n_mm_items=len(mm_images),
            vision_tokens=int(vision_tokens),
            prompt_tokens=int(prompt_tokens),
            per_image=per_image,
        ))

    if failures:
        _banner("[치명적] 프롬프트 준비 단계에서 {}건 실패".format(len(failures)))
        for line in failures[:50]:
            LOG.error("  - %s", line)
        if len(failures) > 50:
            LOG.error("  ... 외 %d건", len(failures) - 50)
        raise SystemExit(
            "프롬프트를 만들 수 없는 문항이 있습니다. 조용히 0점 처리하지 않고 중단합니다."
        )
    return prepared


def check_context_budget(
    prepared: Sequence[PreparedRequest],
    max_model_len: int,
    max_new_tokens: int,
    limit_mm_images: int,
    allow_output_squeeze: bool,
) -> Dict[str, Any]:
    """추론 전에 컨텍스트/이미지 개수 제한을 전수 검사합니다(FACTS 3).

    vLLM 은 프롬프트가 max_model_len 을 넘으면 해당 요청을 거부합니다. 그 결과는
    '응답 없음' 이고, 점수는 조용히 0점이 됩니다. 900문항 중 단 1건만 그래도
    보고서의 숫자가 틀립니다. 그러므로 여기서 먼저 크게 실패합니다.
    """
    hard: List[Tuple[str, int]] = []       # 프롬프트 자체가 컨텍스트를 넘침
    squeeze: List[Tuple[str, int]] = []    # 프롬프트 + max_new_tokens 가 넘침
    mm_over: List[Tuple[str, int]] = []    # 멀티모달 아이템 수가 limit_mm_per_prompt 초과

    for req in prepared:
        if req.prompt_tokens >= max_model_len:
            hard.append((req.sample_id, req.prompt_tokens))
        elif req.prompt_tokens + max_new_tokens > max_model_len:
            squeeze.append((req.sample_id, req.prompt_tokens))
        if req.n_mm_items > limit_mm_images:
            mm_over.append((req.sample_id, req.n_mm_items))

    worst_prompt = max(prepared, key=lambda r: r.prompt_tokens) if prepared else None
    worst_vision = max(prepared, key=lambda r: r.vision_tokens) if prepared else None
    worst_items = max(prepared, key=lambda r: r.n_mm_items) if prepared else None

    _banner("컨텍스트 사전 점검 (추론 전 전수 검사)")
    LOG.info("문항 수: %s / max_model_len=%s / max_new_tokens=%s / limit_mm_per_prompt.image=%d",
             _i(len(prepared)), _i(max_model_len), _i(max_new_tokens), limit_mm_images)
    if worst_prompt is not None:
        LOG.info("최대 prompt_tokens : %s (%s)", _i(worst_prompt.prompt_tokens), worst_prompt.sample_id)
        LOG.info("최대 vision_tokens : %s (%s)", _i(worst_vision.vision_tokens), worst_vision.sample_id)
        LOG.info("최대 이미지 아이템 : %d개 (%s, 마커 등장 횟수 기준)",
                 worst_items.n_mm_items, worst_items.sample_id)
        LOG.info("여유분(headroom)    : %s 토큰 = max_model_len - (최대 prompt + max_new_tokens)",
                 _i(max_model_len - worst_prompt.prompt_tokens - max_new_tokens))
        LOG.info("참고: FACTS 3 의 실측 최대 vision token 5,536(validation_Music_21)은 '고유 참조 이미지' "
                 "기준입니다. 여기 값은 FACTS 4a 의 반복 참조(예: validation_Math_19 의 [1,2,1,1,2])를 "
                 "모두 세므로 더 클 수 있고, 그것이 실제 요청 비용입니다.")

    summary = {
        "n_checked": len(prepared),
        "max_prompt_tokens": int(worst_prompt.prompt_tokens) if worst_prompt else 0,
        "max_prompt_tokens_id": worst_prompt.sample_id if worst_prompt else None,
        "max_vision_tokens": int(worst_vision.vision_tokens) if worst_vision else 0,
        "max_vision_tokens_id": worst_vision.sample_id if worst_vision else None,
        "max_mm_items": int(worst_items.n_mm_items) if worst_items else 0,
        "max_mm_items_id": worst_items.sample_id if worst_items else None,
        "n_prompt_overflow": len(hard),
        "n_output_squeeze": len(squeeze),
        "n_mm_limit_exceeded": len(mm_over),
        "allow_output_squeeze": bool(allow_output_squeeze),
    }

    def _dump(title: str, rows: List[Tuple[str, int]], unit: str) -> None:
        LOG.error("%s (%d건)", title, len(rows))
        for sid, value in rows[:60]:
            LOG.error("    %-34s %s %s", sid, _i(value), unit)
        if len(rows) > 60:
            LOG.error("    ... 외 %d건", len(rows) - 60)

    fatal = False
    if hard:
        _dump("[치명적] 프롬프트가 max_model_len 을 초과하는 문항", hard, "prompt tokens")
        LOG.error("해결책: --max-model-len 을 늘리거나 --max-pixels 를 줄이십시오. "
                  "(예: --max-pixels 1280*32*32 = 1,280 tokens/image)")
        fatal = True
    if mm_over:
        _dump("[치명적] 멀티모달 아이템 수가 limit_mm_per_prompt 를 초과하는 문항", mm_over, "items")
        LOG.error("해결책: --limit-mm-images 를 관측 최대값(%d) 이상으로 올리십시오. "
                  "기본 5 는 FACTS 4 의 'validation 최대 이미지 5장' 에서 온 값이며, "
                  "FACTS 4a 의 반복 참조는 아이템 수를 더 늘릴 수 있습니다.", summary["max_mm_items"])
        fatal = True
    if squeeze:
        if allow_output_squeeze:
            LOG.warning("[경고] prompt + max_new_tokens 가 max_model_len 을 넘는 문항 %d건이 있습니다. "
                        "--allow-output-squeeze 가 켜져 있어 계속 진행하지만, 해당 문항은 "
                        "선언한 max_new_tokens=%s 를 다 쓰지 못합니다. 보고서에 명시하십시오.",
                        len(squeeze), _i(max_new_tokens))
            for sid, value in squeeze[:20]:
                LOG.warning("    %-34s %s prompt tokens", sid, _i(value))
        else:
            _dump("[치명적] prompt + max_new_tokens 가 max_model_len 을 초과하는 문항", squeeze, "prompt tokens")
            LOG.error("해결책: --max-model-len 을 늘리거나 --max-new-tokens 를 줄이거나, "
                      "이 제약을 인정하고 --allow-output-squeeze 를 주십시오.")
            fatal = True

    if fatal:
        raise SystemExit(
            "컨텍스트 사전 점검 실패. 추론 중 조용히 0점 처리되는 것을 막기 위해 중단합니다."
        )
    LOG.info("사전 점검 통과: %s문항 모두 max_model_len 안에 들어갑니다.", _i(len(prepared)))
    return summary


# ---------------------------------------------------------------------------
# presence_penalty 재현 (FACTS 2)
# ---------------------------------------------------------------------------

_PRESENCE_CLS = None


def presence_penalty_processor_class():
    """vLLM 의 presence_penalty 를 재현하는 LogitsProcessor 클래스를 만들어 돌려줍니다.

    FACTS 2 가 말하는 사실관계
      * transformers 의 GenerationConfig 에는 presence_penalty 가 아예 없습니다.
        repetition_penalty 는 '곱셈' 이고 prompt+출력 전체에 적용되므로 대체물이 아닙니다.
      * vLLM 의 presence_penalty 는 '가산' 입니다:
            logits -= penalty * (이미 생성된 토큰인지 여부)
        - 마스크는 '생성된 연속열(continuation)' 에만 적용되고 prompt 는 제외됩니다.
        - 등장 '횟수' 는 무시합니다(있다/없다만 봅니다). 횟수를 보는 것은 frequency_penalty 입니다.
    그래서 prompt 길이를 받아 그 이후 구간만 마스크로 만듭니다. 이 클래스를 쓰면
    hf 백엔드에서도 교수님의 presence_penalty=1.5 를 실제로 적용할 수 있습니다.
    (클래스 생성을 지연시키는 이유: transformers 가 없는 환경에서도 --help 가 떠야 합니다.)
    """
    global _PRESENCE_CLS
    if _PRESENCE_CLS is not None:
        return _PRESENCE_CLS

    try:
        from transformers import LogitsProcessor as _Base
    except Exception:  # 매우 오래된/변형된 설치에서도 동작하도록 순수 callable 로 대체
        _Base = object

    import torch

    class PresencePenaltyLogitsProcessor(_Base):  # type: ignore[misc,valid-type]
        """vLLM 과 동일한 가산형 presence penalty. prompt 구간은 제외합니다."""

        def __init__(self, prompt_len: int, penalty: float) -> None:
            if prompt_len < 0:
                raise ValueError("prompt_len 은 0 이상이어야 합니다.")
            self.prompt_len = int(prompt_len)
            self.penalty = float(penalty)

        def __call__(self, input_ids, scores):
            if self.penalty == 0.0:
                return scores
            generated = input_ids[:, self.prompt_len:]
            if generated.shape[-1] == 0:
                return scores  # 첫 토큰에는 적용할 '이미 생성된 토큰' 이 없습니다.
            vocab = scores.shape[-1]
            max_id = int(generated.max())
            if max_id >= vocab:
                # 조용히 엉뚱한 토큰에 벌점을 주는 것보다 명시적으로 실패하는 편이 낫습니다.
                raise RuntimeError(
                    "생성 토큰 id {} 가 logits 차원 {} 을 벗어났습니다.".format(max_id, vocab)
                )
            mask = torch.zeros_like(scores)
            # scatter_ 는 중복 인덱스를 '덮어쓰기' 하므로 등장 횟수가 무시됩니다.
            # 이것이 vLLM presence_penalty 와 정확히 같은 동작입니다.
            mask.scatter_(1, generated, 1.0)
            return scores - self.penalty * mask

    _PRESENCE_CLS = PresencePenaltyLogitsProcessor
    return _PRESENCE_CLS


# ---------------------------------------------------------------------------
# 백엔드 (vllm / hf 를 하나의 인터페이스 뒤에 둡니다)
# ---------------------------------------------------------------------------

@dataclass
class GenOutput:
    text: str
    output_tokens: int
    latency_s: Optional[float]
    finish_reason: Optional[str] = None


class Backend:
    """추론 백엔드 공통 인터페이스."""

    name = "base"
    latency_basis = "unknown"

    def load(self) -> float:
        """모델을 적재하고 소요 시간(초)을 돌려줍니다."""
        raise NotImplementedError

    def generate(self, requests: Sequence[PreparedRequest]) -> List[GenOutput]:
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {"backend": self.name}

    def shutdown(self) -> None:
        return None


class VLLMBackend(Backend):
    """vLLM 백엔드. FACTS 13 기준 RTX 4090 1장에서 900문항 약 15~45분."""

    name = "vllm"
    latency_basis = "vllm_request_metrics"

    def __init__(self, args: argparse.Namespace, budget: PixelBudget) -> None:
        self.args = args
        self.budget = budget
        self.llm = None
        self.sampling_params = None
        self._latency_basis_resolved: Optional[str] = None

        # FACTS 3/5 에 맞춘 엔진 인자. 이름이 max_model_len 인 점이 중요합니다
        # ('max_model_length' 는 vLLM 에 존재하지 않는 이름이며, 교수님 슬라이드의 산문 표현입니다).
        self.engine_kwargs: Dict[str, Any] = {
            "model": args.model,
            "revision": args.model_revision,
            # FACTS 6: tokenizer_revision 은 기본값이 None 이어서 따로 고정하지 않으면
            # 모델만 고정되고 토크나이저는 main 을 따라갑니다. 반드시 같이 핀합니다.
            "tokenizer_revision": args.model_revision,
            "dtype": "bfloat16",                      # FACTS 6: 가중치가 BF16
            "max_model_len": args.max_model_len,
            # FACTS 3/4: validation 최대 이미지 5장. video:0 을 주어야 비디오 인코더용
            # 메모리 예약이 사라집니다.
            "limit_mm_per_prompt": {"image": int(args.limit_mm_images), "video": 0},
            # FACTS 1: vLLM 에서도 min_pixels/max_pixels 가 size 의 alias 로 동작합니다.
            # 둘을 같은 값으로 함께 넘겨 어느 경로가 우선해도 예산이 같게 만듭니다.
            "mm_processor_kwargs": {
                "min_pixels": budget.min_pixels,
                "max_pixels": budget.max_pixels,
                "size": {"shortest_edge": budget.min_pixels, "longest_edge": budget.max_pixels},
            },
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "max_num_seqs": args.max_num_seqs,
            # FACTS 7: LLM(seed) 와 SamplingParams(seed) 를 모두 설정해야 합니다.
            "seed": args.seed,
            # trust_remote_code 는 넘기지 않습니다(FACTS 5: 아키텍처가 registry 에 기본 등록).
        }
        if args.enforce_eager:
            self.engine_kwargs["enforce_eager"] = True

    def load(self) -> float:
        # FACTS 7: 오프라인 추론의 재현성을 위해 vllm import '전에' 설정해야 하는 환경변수입니다.
        os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
        t0 = time.perf_counter()
        from vllm import LLM, SamplingParams
        LOG.info("vLLM 엔진 인자: %s", json.dumps(self.engine_kwargs, ensure_ascii=False, sort_keys=True))
        self.llm = LLM(**self.engine_kwargs)
        self.sampling_params = SamplingParams(
            n=1,
            temperature=self.args.temperature,
            top_p=self.args.top_p,
            top_k=self.args.top_k,
            repetition_penalty=self.args.repetition_penalty,
            # FACTS 2: presence_penalty 는 vLLM 에만 있는 네이티브 인자입니다.
            presence_penalty=self.args.presence_penalty,
            frequency_penalty=0.0,
            max_tokens=self.args.max_new_tokens,
            seed=self.args.seed,
        )
        elapsed = time.perf_counter() - t0
        LOG.info("SamplingParams: %s", self.sampling_params)
        return elapsed

    def generate(self, requests: Sequence[PreparedRequest]) -> List[GenOutput]:
        if self.llm is None:
            raise RuntimeError("load() 를 먼저 호출해야 합니다.")
        prompts = []
        for req in requests:
            item: Dict[str, Any] = {"prompt": req.rendered}
            if req.mm_images:
                # 자리표시자 순서와 완전히 같은 순서로 넘깁니다(반복 참조 이미지는 반복해서 넣음).
                item["multi_modal_data"] = {"image": list(req.mm_images)}
            prompts.append(item)

        outputs = self.llm.generate(prompts, self.sampling_params, use_tqdm=not self.args.no_progress)
        if len(outputs) != len(requests):
            raise RuntimeError(
                "vLLM 이 요청 {}건에 대해 결과 {}건을 돌려주었습니다. 순서 대응이 깨졌습니다.".format(
                    len(requests), len(outputs))
            )
        # vLLM 의 LLM.generate 는 입력 순서를 유지합니다(공식 문서 보장).
        # 주의: out.prompt 를 입력 문자열과 비교해서 순서를 검사하면 안 됩니다.
        # 이미지가 있는 요청은 <|image_pad|> 자리표시자가 비전 토큰 수만큼 펼쳐져서
        # 돌아오므로 항상 다르게 보입니다(2026-09-14 실제 실행에서 오탐으로 중단됨).
        # 건수 일치 검사(위)만으로 충분합니다.

        results: List[GenOutput] = []
        for out in outputs:
            completion = out.outputs[0]
            latency = None
            metrics = getattr(out, "metrics", None)
            if metrics is not None:
                arrival = getattr(metrics, "arrival_time", None)
                finished = getattr(metrics, "finished_time", None)
                if arrival is not None and finished is not None:
                    latency = max(0.0, float(finished) - float(arrival))
            if latency is None and self._latency_basis_resolved is None:
                # vLLM V1 에서는 RequestOutput.metrics 가 None 일 수 있습니다. 그 경우
                # 과목 배치 시간을 문항 수로 나눈 '분할 추정치' 를 쓰고, 그 사실을 config.json 에 남깁니다.
                self._latency_basis_resolved = "amortized_per_subject_batch"
                LOG.info("vLLM 이 요청별 metrics 를 제공하지 않습니다. latency_s 는 과목 배치 시간의 "
                         "문항당 분할값으로 기록합니다(config.json 의 latency_basis 참조).")
            elif latency is not None and self._latency_basis_resolved is None:
                self._latency_basis_resolved = "vllm_request_metrics"
            results.append(GenOutput(
                text=completion.text or "",
                output_tokens=len(getattr(completion, "token_ids", []) or []),
                latency_s=latency,
                finish_reason=getattr(completion, "finish_reason", None),
            ))
        return results

    def describe(self) -> Dict[str, Any]:
        return {
            "backend": "vllm",
            "engine_kwargs": self.engine_kwargs,
            "latency_basis": self._latency_basis_resolved or self.latency_basis,
            "vllm_env": {
                key: os.environ.get(key)
                for key in ("VLLM_ENABLE_V1_MULTIPROCESSING", "VLLM_BATCH_INVARIANT",
                            "VLLM_ATTENTION_BACKEND", "VLLM_USE_V1")
            },
        }


class HFBackend(Backend):
    """transformers 백엔드. batch=1 이라 FACTS 13 기준 RTX 4090 에서 2~6시간 걸립니다.

    vLLM 이 설치되지 않은 환경의 대조군/검증용 경로입니다.
    """

    name = "hf"
    latency_basis = "per_sample_wall_clock"

    def __init__(self, args: argparse.Namespace, processor: Any, budget: PixelBudget) -> None:
        self.args = args
        self.processor = processor   # resolve_processor 에서 예산이 강제 반영된 그 객체를 재사용합니다.
        self.budget = budget
        self.model = None
        self.model_class_name = None
        self.dtype_kwarg = None
        self.presence_mode = args.hf_presence_penalty

    def load(self) -> float:
        t0 = time.perf_counter()
        import torch
        import transformers

        model_cls = None
        for name in ("Qwen3VLForConditionalGeneration", "AutoModelForImageTextToText",
                     "AutoModelForVision2Seq"):
            candidate = getattr(transformers, name, None)
            if candidate is not None:
                model_cls, self.model_class_name = candidate, name
                break
        if model_cls is None:
            raise RuntimeError(
                "transformers 에서 Qwen3VL 용 모델 클래스를 찾지 못했습니다. "
                "FACTS 5 에 따라 transformers >= 4.57.0 이 필요합니다(현재 {}).".format(
                    transformers.__version__)
            )

        try:
            major = int(str(transformers.__version__).split(".")[0])
        except Exception:
            major = 4
        # FACTS 5 STACK B: transformers v5 는 dtype=, v4 는 torch_dtype= 입니다.
        self.dtype_kwarg = "dtype" if major >= 5 else "torch_dtype"
        kwargs: Dict[str, Any] = {
            self.dtype_kwarg: torch.bfloat16,
            # FACTS 5: flash-attn 은 PyPI sdist 전용이라 30~60분 컴파일입니다. 절대 쓰지 않습니다.
            # Qwen3VL 은 _supports_sdpa = True 이므로 sdpa 가 그대로 대체됩니다.
            "attn_implementation": "sdpa",
        }
        if torch.cuda.is_available():
            kwargs["device_map"] = "cuda:0"

        LOG.info("transformers 모델 로드: %s (%s, revision=%s, %s)",
                 self.args.model, self.model_class_name, self.args.model_revision, kwargs)
        try:
            self.model = model_cls.from_pretrained(
                self.args.model, revision=self.args.model_revision, **kwargs)
        except TypeError as exc:
            # dtype 인자 이름이 버전에 따라 다른 경우에만 한 번 바꿔서 재시도합니다.
            other = "torch_dtype" if self.dtype_kwarg == "dtype" else "dtype"
            LOG.warning("%s 인자가 거부되었습니다(%s). %s 로 재시도합니다.", self.dtype_kwarg, exc, other)
            kwargs[other] = kwargs.pop(self.dtype_kwarg)
            self.dtype_kwarg = other
            self.model = model_cls.from_pretrained(
                self.args.model, revision=self.args.model_revision, **kwargs)
        self.model.eval()

        # FACTS 7: enable_full_determinism() 은 CUDA_LAUNCH_BLOCKING=1 을 켜서 모든 커널을
        # 직렬화합니다. 그러면 과제가 요구하는 소요 시간 표가 의미를 잃으므로 쓰지 않고,
        # set_seed 만 호출합니다.
        transformers.set_seed(self.args.seed)
        return time.perf_counter() - t0

    def generate(self, requests: Sequence[PreparedRequest]) -> List[GenOutput]:
        if self.model is None:
            raise RuntimeError("load() 를 먼저 호출해야 합니다.")
        import torch
        from transformers import LogitsProcessorList

        results: List[GenOutput] = []
        do_sample = self.args.temperature is not None and self.args.temperature > 0.0
        for req in requests:
            t0 = time.perf_counter()
            inputs = self.processor(
                text=[req.rendered],
                images=list(req.mm_images) if req.mm_images else None,
                return_tensors="pt",
            )
            inputs = inputs.to(self.model.device)
            prompt_len = int(inputs["input_ids"].shape[1])

            logits_processor = None
            if self.presence_mode == "custom" and self.args.presence_penalty:
                cls = presence_penalty_processor_class()
                logits_processor = LogitsProcessorList([cls(prompt_len, self.args.presence_penalty)])

            gen_kwargs: Dict[str, Any] = {
                "max_new_tokens": self.args.max_new_tokens,
                "do_sample": do_sample,
                "repetition_penalty": self.args.repetition_penalty,
            }
            if do_sample:
                gen_kwargs.update({
                    "temperature": self.args.temperature,
                    "top_p": self.args.top_p,
                    "top_k": self.args.top_k,
                })
            if logits_processor is not None:
                gen_kwargs["logits_processor"] = logits_processor

            with torch.inference_mode():
                out_ids = self.model.generate(**inputs, **gen_kwargs)
            gen_ids = out_ids[0][prompt_len:]
            text = self.processor.batch_decode(
                [gen_ids], skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
            n_out = int(gen_ids.shape[0])
            finish = "length" if n_out >= self.args.max_new_tokens else "stop"
            results.append(GenOutput(text=text, output_tokens=n_out,
                                     latency_s=time.perf_counter() - t0, finish_reason=finish))
        return results

    def describe(self) -> Dict[str, Any]:
        return {
            "backend": "hf",
            "model_class": self.model_class_name,
            "dtype_kwarg": self.dtype_kwarg,
            "attn_implementation": "sdpa",
            "batch_size": 1,
            "latency_basis": self.latency_basis,
        }


def presence_penalty_record(args: argparse.Namespace) -> Dict[str, Any]:
    """config.json 에 들어갈 presence_penalty 적용 기록(FACTS 2).

    보고서가 '적용하지 않은 설정' 을 적는 사고를 막기 위한 핵심 필드입니다.
    """
    requested = float(args.presence_penalty)
    if args.backend == "vllm":
        return {
            "requested": requested,
            "applied": True,
            "mechanism": "vllm.SamplingParams.presence_penalty (네이티브, 가산형)",
            "note": "vLLM 공식 구현. logits -= penalty * (생성된 토큰 여부), prompt 제외, 횟수 무시.",
        }
    if requested == 0.0:
        return {
            "requested": requested,
            "applied": False,
            "mechanism": "없음 (요청값이 0)",
            "note": "presence_penalty=0 이므로 적용할 것이 없습니다.",
        }
    if args.hf_presence_penalty == "custom":
        return {
            "requested": requested,
            "applied": True,
            "mechanism": "PresencePenaltyLogitsProcessor (본 저장소 src/eval_mmmu.py 자체 구현)",
            "note": ("transformers 에는 presence_penalty 가 존재하지 않습니다(FACTS 2). "
                     "vLLM 의 가산식(logits -= penalty * presence_mask, 생성 구간만, 횟수 무시)을 "
                     "동일하게 재현한 커스텀 LogitsProcessor 로 적용했습니다. "
                     "repetition_penalty(곱셈, prompt 포함)와는 다른 연산입니다."),
        }
    return {
        "requested": requested,
        "applied": False,
        "mechanism": "없음 (--hf-presence-penalty off)",
        "note": ("transformers 에는 presence_penalty 가 없고(FACTS 2) 커스텀 프로세서도 끈 상태입니다. "
                 "보고서에 'presence_penalty=1.5 적용' 이라고 쓰면 거짓이 됩니다."),
    }


# ---------------------------------------------------------------------------
# predictions.jsonl 입출력 / 이어하기 (FACTS: 대여 GPU 에서 접속이 끊겨도 살아남아야 함)
# ---------------------------------------------------------------------------

def build_record(req: PreparedRequest, out: GenOutput, latency_s: Optional[float],
                 score: Dict[str, Any]) -> Dict[str, Any]:
    """predictions.jsonl 한 줄. 키 순서와 이름은 INTERFACES 규약 그대로입니다."""
    sample = req.sample
    return {
        "id": sample.id,
        "subject": sample.subject,
        "category": sample.category,
        "question_type": sample.question_type,
        # n_images 는 '고유 참조 이미지 수'(= image_indices 길이)입니다.
        # 마커 반복 등장으로 실제 전달된 아이템 수가 더 많을 수 있는데(FACTS 4a),
        # 그 차이는 vision_tokens 에 반영되어 있고 config.json 에 집계해 둡니다.
        # images 리스트가 아니라 image_indices 를 세는 이유: 과목이 끝나면 메모리 회수를 위해
        # PIL 이미지를 닫고 비우므로(release_images), 길이가 보존되는 쪽을 사용합니다.
        # 두 값이 일치하는지는 prepare_requests 에서 이미 검증했습니다.
        "n_images": len(getattr(sample, "image_indices", []) or []),
        "image_indices": list(getattr(sample, "image_indices", []) or []),
        "vision_tokens": int(req.vision_tokens),
        "prompt_tokens": int(req.prompt_tokens),
        "output_tokens": int(out.output_tokens),
        "response": out.text,
        "parsed": score.get("parsed"),
        "gold": sample.answer,
        "correct": bool(score.get("correct")),
        "unparseable": bool(score.get("unparseable")),
        "latency_s": None if latency_s is None else round(float(latency_s), 4),
    }


def provisional_score(sample: Any, response: str) -> Dict[str, Any]:
    """생성 직후의 임시 채점.

    FACTS 4c 의 난수 폴백이 전역 random 스트림을 소비하므로, 최종 점수의 재현성을
    지키기 위해 여기서는 전역 상태를 저장/복원하고 문항별 고정 시드를 씁니다.
    파일에 기록되는 이 값은 '임시' 이며, 실행 마지막의 일괄 재채점
    (random.seed(42) 직후)이 predictions.jsonl 을 덮어써 최종값으로 만듭니다.
    """
    state = random.getstate()
    try:
        random.seed(_stable_seed(str(sample.id)))
        return mmmu_parser.score_sample(sample, response)
    finally:
        random.setstate(state)


def load_existing_predictions(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """기존 predictions.jsonl 을 읽습니다. 깨진 줄/중복 id 는 정리하고 파일을 다시 씁니다."""
    if not path.exists():
        return [], 0
    records: List[Dict[str, Any]] = []
    broken = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                broken += 1
                continue
            if not isinstance(rec, dict) or "id" not in rec or not isinstance(rec.get("response"), str):
                broken += 1
                continue
            records.append(rec)

    by_id: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for rec in records:
        if rec["id"] in by_id:
            duplicates += 1
        by_id[rec["id"]] = rec   # 중복이면 마지막 것을 채택
    cleaned = list(by_id.values())

    if broken or duplicates:
        LOG.warning("기존 predictions.jsonl 정리: 깨진 줄 %d개, 중복 id %d개를 제거하고 다시 씁니다.",
                    broken, duplicates)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for rec in cleaned:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    return cleaned, broken


def rewrite_predictions(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    """최종 채점 결과로 predictions.jsonl 을 원자적으로 다시 씁니다."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            ordered = {key: rec.get(key) for key in PREDICTION_KEYS}
            fh.write(json.dumps(ordered, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 채점 / 집계
# ---------------------------------------------------------------------------

def _is_open_ended(question_type: Any) -> bool:
    """FACTS 4: HF 스키마는 'open', MMMU 저장소 쪽 표기는 'short-answer' 입니다."""
    return str(question_type or "").strip().lower().replace("_", "-") in (
        "open", "open-ended", "short-answer", "short answer")


def score_all(records: Sequence[Dict[str, Any]], sample_by_id: Dict[str, Any]) -> Dict[str, int]:
    """전체를 고정 순서로 재채점합니다. 여기가 점수의 유일한 출처입니다.

    FACTS 4c: 공식 파서는 파싱 실패 시 random.choice 로 찍기 때문에 점수가 전역 난수
    스트림, 즉 '문항 순회 순서' 에 의존합니다. 그래서
      (1) 순서를 load_mmmu 의 결정적 정렬로 고정하고,
      (2) 이 루프 바로 직전에 random.seed(42) 를 호출합니다(공식 eval_utils.py 와 동일).
    이어하기로 생성 순서가 달라졌더라도 최종 점수는 항상 같아집니다.
    """
    random.seed(OFFICIAL_PARSER_SEED)   # <<< 파싱 루프 직전 (FACTS 4c)
    stats = {"n": 0, "unparseable": 0}
    for rec in records:
        sample = sample_by_id[rec["id"]]
        result = mmmu_parser.score_sample(sample, rec.get("response") or "")
        rec["parsed"] = result.get("parsed")
        rec["correct"] = bool(result.get("correct"))
        rec["unparseable"] = bool(result.get("unparseable"))
        rec["gold"] = sample.answer
        stats["n"] += 1
        if rec["unparseable"]:
            stats["unparseable"] += 1
    return stats


def _bucket() -> Dict[str, int]:
    return {"n": 0, "correct": 0}


def build_metrics(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    overall = _bucket()
    by_subject: Dict[str, Dict[str, int]] = {}
    by_category: Dict[str, Dict[str, int]] = {}
    mc = _bucket()
    open_ended = _bucket()
    n_unparseable = 0

    for rec in records:
        correct = 1 if rec.get("correct") else 0
        overall["n"] += 1
        overall["correct"] += correct
        subject = rec.get("subject") or mmmu_data.subject_from_id(rec["id"])
        category = rec.get("category") or mmmu_data.SUB2DOMAIN.get(subject, "UNKNOWN")
        by_subject.setdefault(subject, _bucket())
        by_subject[subject]["n"] += 1
        by_subject[subject]["correct"] += correct
        by_category.setdefault(category, _bucket())
        by_category[category]["n"] += 1
        by_category[category]["correct"] += correct
        target = open_ended if _is_open_ended(rec.get("question_type")) else mc
        target["n"] += 1
        target["correct"] += correct
        if rec.get("unparseable"):
            n_unparseable += 1

    def _finish(bucket: Dict[str, int]) -> Dict[str, Any]:
        return {"n": bucket["n"], "correct": bucket["correct"],
                "accuracy": _acc(bucket["correct"], bucket["n"])}

    # 출력 순서를 고정합니다: 과목은 SUBJECTS 순, 카테고리는 CATEGORY_ORDER 순.
    subject_order = [s for s in mmmu_data.SUBJECTS if s in by_subject]
    subject_order += [s for s in sorted(by_subject) if s not in subject_order]
    category_order = [c for c in mmmu_data.CATEGORY_ORDER if c in by_category]
    category_order += [c for c in sorted(by_category) if c not in category_order]

    return {
        "overall": _finish(overall),
        "by_subject": {s: _finish(by_subject[s]) for s in subject_order},
        "by_category": {c: _finish(by_category[c]) for c in category_order},
        "multiple_choice": _finish(mc),
        "open_ended": _finish(open_ended),
        "n_unparseable": n_unparseable,
        # FACTS 4b: 카테고리 표본수가 120/150/150/150/120/210 으로 다르므로 6개 카테고리
        # 정확도의 단순 평균은 Overall 과 다릅니다. 공식 하니스와 같은 micro 평균을 씁니다.
        "aggregation": "micro / sample-weighted",
        "published_reference": {"mmmu_val": PUBLISHED_MMMU_VAL, "source": PUBLISHED_SOURCE},
    }


def build_timing(
    new_times: Dict[str, Dict[str, float]],
    carried: Dict[str, Dict[str, float]],
    total_wall_s: float,
    model_load_s: float,
    scoring_s: float,
) -> Tuple[Dict[str, Any], List[str]]:
    """timing.json 을 만듭니다. 카테고리 시간은 과목 시간에서 합산합니다(과제 요구사항)."""
    subjects = set(new_times) | set(carried)
    merged: Dict[str, Dict[str, float]] = {}
    for subject in subjects:
        n = float(new_times.get(subject, {}).get("n", 0)) + float(carried.get(subject, {}).get("n", 0))
        wall = float(new_times.get(subject, {}).get("wall_s", 0.0)) + float(carried.get(subject, {}).get("wall_s", 0.0))
        merged[subject] = {"n": int(n), "wall_s": round(wall, 3),
                           "s_per_sample": round(wall / n, 3) if n else 0.0}

    order = [s for s in mmmu_data.SUBJECTS if s in merged]
    order += [s for s in sorted(merged) if s not in order]
    by_subject = {s: merged[s] for s in order}

    by_category_acc: Dict[str, Dict[str, float]] = {}
    for subject, row in by_subject.items():
        category = mmmu_data.SUB2DOMAIN.get(subject, "UNKNOWN")
        acc = by_category_acc.setdefault(category, {"n": 0, "wall_s": 0.0})
        acc["n"] += row["n"]
        acc["wall_s"] += row["wall_s"]
    cat_order = [c for c in mmmu_data.CATEGORY_ORDER if c in by_category_acc]
    cat_order += [c for c in sorted(by_category_acc) if c not in cat_order]
    by_category = {
        c: {"n": int(by_category_acc[c]["n"]),
            "wall_s": round(by_category_acc[c]["wall_s"], 3),
            "s_per_sample": round(by_category_acc[c]["wall_s"] / by_category_acc[c]["n"], 3)
            if by_category_acc[c]["n"] else 0.0}
        for c in cat_order
    }

    inference_s = round(sum(row["wall_s"] for row in by_subject.values()), 3)
    missing = [s for s, row in by_subject.items() if row["n"] == 0 or row["wall_s"] == 0.0]
    timing = {
        "total_wall_s": round(total_wall_s, 3),
        "model_load_s": round(model_load_s, 3),
        "inference_s": inference_s,
        "scoring_s": round(scoring_s, 3),
        "by_subject": by_subject,
        "by_category": by_category,
    }
    return timing, missing


# ---------------------------------------------------------------------------
# 데이터 검증 (FACTS 4 / 6 의 값과 대조해 데이터 드리프트를 잡습니다)
# ---------------------------------------------------------------------------

def validate_sample_set(samples: Sequence[Any], args: argparse.Namespace, full_run: bool) -> Dict[str, Any]:
    n = len(samples)
    if n == 0:
        raise SystemExit("불러온 문항이 0개입니다. --data-path / --split / --subjects 를 확인하십시오.")

    subjects = sorted({s.subject for s in samples})
    unknown = [s for s in subjects if s not in mmmu_data.SUBJECTS]
    if unknown:
        raise SystemExit("알 수 없는 과목이 있습니다: {} (FACTS 4b 의 30개 과목과 맞지 않습니다)".format(unknown))

    n_open = sum(1 for s in samples if _is_open_ended(s.question_type))
    n_mc = n - n_open
    max_index = max((max(s.image_indices) if s.image_indices else 0) for s in samples)
    n_no_image = sum(1 for s in samples if not (s.images or []))

    _banner("데이터셋 확인")
    LOG.info("문항 수 %s / 과목 %d개 / multiple-choice %s / open %s",
             _i(n), len(subjects), _i(n_mc), _i(n_open))
    LOG.info("참조 이미지 최대 인덱스 %d / 이미지가 없는 문항 %d개", max_index, n_no_image)

    if full_run and args.split == "validation":
        # FACTS 4 / 6: 이 숫자가 틀리면 데이터셋 리비전이 바뀐 것입니다(2026-02-12, 04-21, 07-10 변경 이력).
        if n != EXPECTED_VALIDATION_N:
            LOG.warning("[경고] validation 문항 수가 %s 가 아니라 %s 입니다. "
                        "--dataset-revision 을 확인하십시오(FACTS 6: 데이터가 바뀐 이력이 있습니다).",
                        _i(EXPECTED_VALIDATION_N), _i(n))
        if (n_mc, n_open) != (EXPECTED_VALIDATION_MC, EXPECTED_VALIDATION_OPEN):
            LOG.warning("[경고] MC/open 구성이 FACTS 4 의 %d/%d 와 다릅니다(현재 %d/%d).",
                        EXPECTED_VALIDATION_MC, EXPECTED_VALIDATION_OPEN, n_mc, n_open)
        if len(subjects) != len(mmmu_data.SUBJECTS):
            LOG.warning("[경고] 과목이 %d개만 로드되었습니다(기대 %d개).",
                        len(subjects), len(mmmu_data.SUBJECTS))
        if max_index > DEFAULT_LIMIT_MM_IMAGES:
            LOG.warning("[경고] 참조 이미지 인덱스 최대값이 %d 입니다(FACTS 4 기대 최대 5). "
                        "--limit-mm-images 를 올려야 할 수 있습니다.", max_index)

    mc_without_options = [s.id for s in samples
                          if not _is_open_ended(s.question_type) and not (s.options or [])]
    if mc_without_options:
        LOG.warning("[경고] 선택지가 비어 있는 multiple-choice 문항 %d개: %s",
                    len(mc_without_options), mc_without_options[:10])

    return {"n": n, "n_subjects": len(subjects), "n_multiple_choice": n_mc, "n_open": n_open,
            "max_image_index": int(max_index), "n_without_image": n_no_image,
            "subjects": subjects}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eval_mmmu.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Qwen3-VL-4B-Instruct 의 MMMU validation 베이스라인 평가 (과목/카테고리별 정확도 + 소요 시간 기록).",
        epilog="예) python src/eval_mmmu.py --data-path /workspace/data/MMMU --backend vllm",
    )
    parser.add_argument("--data-path", required=True,
                        help="[필수] MMMU 데이터 경로(로컬 디렉터리) 또는 HF repo id(MMMU/MMMU).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="모델 repo id 또는 로컬 경로.")
    parser.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION,
                        help="모델 커밋 sha. main 은 움직이는 포인터이므로 기본값으로 고정합니다(FACTS 6).")
    parser.add_argument("--dataset-revision", default=DEFAULT_DATASET_REVISION,
                        help="MMMU 데이터셋 커밋 sha(FACTS 6). 로컬 경로를 쓰면 기록용으로만 남습니다.")
    parser.add_argument("--backend", choices=("vllm", "hf"), default="vllm",
                        help="vllm: 약 15~45분 / hf: 약 2~6시간 (FACTS 13).")
    parser.add_argument("--split", default="validation", help="평가 split (기본 validation).")
    parser.add_argument("--subjects", default=None,
                        help="쉼표로 구분한 과목 필터(예: Math,Physics). 지정하면 보고용 실행이 아닙니다.")
    parser.add_argument("--limit", type=int, default=None,
                        help="앞에서 N문항만 (스모크 테스트용). 지정하면 보고용 실행이 아닙니다.")
    parser.add_argument("--template", choices=("official", "llava", "anchored"), default="anchored",
                        help="프롬프트 템플릿. 기본 anchored = 공식 문구 + 'Answer:' 파싱 앵커(FACTS 11).")
    parser.add_argument("--out", default=None,
                        help="출력 디렉터리. 생략하면 인자들로부터 결정적으로 생성됩니다(타임스탬프 아님).")
    parser.add_argument("--max-model-len", type=int, default=9048,
                        help="vLLM 의 max_model_len (교수님 권장 9048). 'max_model_length' 는 vLLM 인자가 아닙니다.")
    parser.add_argument("--max-new-tokens", type=int, default=2048, help="생성 최대 토큰 수.")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--presence-penalty", type=float, default=1.5,
                        help="vllm 백엔드는 네이티브 적용. hf 백엔드는 커스텀 LogitsProcessor 로 재현(FACTS 2).")
    parser.add_argument("--min-pixels", default=DEFAULT_MIN_PIXELS_SPEC,
                        help="이미지 최소 픽셀. 'N*28*28' 표기 또는 정수. 기본 1280*28*28 -> 980 토큰.")
    parser.add_argument("--max-pixels", default=DEFAULT_MAX_PIXELS_SPEC,
                        help="이미지 최대 픽셀. 'N*28*28' 표기 또는 정수. 기본 5120*28*28 -> 3920 토큰.")
    parser.add_argument("--seed", type=int, default=3407,
                        help="LLM() 과 SamplingParams() 양쪽에 적용(FACTS 7). Qwen 권장값 3407.")
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90,
                        help="vLLM gpu_memory_utilization. 프로파일링에서 OOM 이면 0.85 로 내리십시오(FACTS 8).")
    parser.add_argument("--max-num-seqs", type=int, default=32, help="vLLM 동시 시퀀스 수.")
    parser.add_argument("--limit-mm-per-prompt-image", "--limit-mm-images", dest="limit_mm_images",
                        type=int, default=DEFAULT_LIMIT_MM_IMAGES,
                        help="limit_mm_per_prompt 의 image 값(기본 5 = FACTS 4 의 validation 최대 이미지 수).")
    parser.add_argument("--hf-presence-penalty", choices=("custom", "off"), default="custom",
                        help="hf 백엔드에서 presence_penalty 처리 방법. off 를 주면 미적용으로 기록됩니다.")
    parser.add_argument("--dry-run", action="store_true",
                        help="프롬프트 생성과 토큰 사전 계산만 수행하고 모델은 적재하지 않습니다.")
    parser.add_argument("--allow-output-squeeze", action="store_true",
                        help="prompt + max_new_tokens 가 max_model_len 을 넘는 문항을 허용(기본은 중단).")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="git 작업트리가 dirty 여도 진행(기본은 보고용 실행에서 중단, FACTS 12).")
    parser.add_argument("--enforce-eager", action="store_true",
                        help="vLLM 의 CUDA 그래프 캡처를 끕니다(메모리 부족 시 탈출구).")
    parser.add_argument("--no-progress", action="store_true", help="vLLM 진행바를 끕니다.")
    parser.add_argument("--verbose", action="store_true", help="DEBUG 로그까지 출력합니다.")
    return parser


def resolve_out_dir(args: argparse.Namespace) -> Path:
    """--out 기본값은 '인자로부터 결정적으로' 만듭니다(타임스탬프 금지 = 이어하기가 가능해야 함)."""
    if args.out:
        return Path(args.out).expanduser().resolve()
    key = {
        "model": args.model,
        "model_revision": args.model_revision,
        "dataset_revision": args.dataset_revision,
        "data_path": str(args.data_path),
        "split": args.split,
        "subjects": args.subjects or "",
        "limit": args.limit,
        "template": args.template,
        "backend": args.backend,
        "max_model_len": args.max_model_len,
        "max_new_tokens": args.max_new_tokens,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "repetition_penalty": args.repetition_penalty,
        "presence_penalty": args.presence_penalty,
        "min_pixels": args.min_pixels,
        "max_pixels": args.max_pixels,
        "seed": args.seed,
    }
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:8]
    slug = str(args.model).rstrip("/").split("/")[-1].replace(".", "-")
    name = "{}_{}_{}_{}_seed{}_{}".format(args.split, slug, args.backend, args.template, args.seed, digest)
    return (REPO_ROOT / "outputs" / name).resolve()


# ---------------------------------------------------------------------------
# 환경 기록 / 설정 기록
# ---------------------------------------------------------------------------

def write_environment(
    out_dir: Path,
    args: argparse.Namespace,
    budget: PixelBudget,
    data_stats: Dict[str, Any],
    attn_impl: str,
    run_config: Dict[str, Any],
) -> Dict[str, Any]:
    """env.json / ENVIRONMENT.md 를 '모델 로드 이전에' 기록합니다(FACTS 12, 과제 요구사항).

    실행이 중간에 실패해도 환경 기록은 남아야 합니다. 4명이 각자 빌린 GPU 결과를
    비교하려면 이 파일이 결과 파일보다 먼저 존재해야 합니다.
    """
    model_path = Path(str(args.model)).expanduser()
    extra = {
        "model": {
            "repo_id": args.model,
            "revision": args.model_revision,
            "local_path": str(model_path.resolve()) if model_path.exists() else None,
            "dtype": "bfloat16",
            "attn_implementation": attn_impl,
        },
        "dataset": {
            "repo_id_or_path": str(args.data_path),
            "revision": args.dataset_revision,
            "split": args.split,
            "n_samples": int(data_stats["n"]),
        },
        "run_config": run_config,
    }
    env = capture_env.write_env(out_dir, extra=extra)
    LOG.info("환경 기록 완료: %s, %s", out_dir / "env.json", out_dir / "ENVIRONMENT.md")
    hardware = (env or {}).get("hardware") or {}
    driver = (env or {}).get("driver_cuda") or {}
    LOG.info("GPU=%s x%s / VRAM=%s MiB / nvidia-smi CUDA=%s / torch.version.cuda=%s",
             hardware.get("gpu_name"), hardware.get("gpu_count"), hardware.get("vram_total_mib"),
             driver.get("nvidia_smi_cuda"), driver.get("torch_version_cuda"))
    return env or {}


def make_run_config(
    args: argparse.Namespace,
    out_dir: Path,
    budget: PixelBudget,
    presence: Dict[str, Any],
    subjects: Optional[List[str]],
) -> Dict[str, Any]:
    """env.json 의 run_config 와 config.json 에 공통으로 들어가는 해석된 설정."""
    return {
        "out_dir": str(out_dir),
        "data_path": str(args.data_path),
        "split": args.split,
        "subjects_filter": subjects,
        "limit": args.limit,
        "template": args.template,
        "backend": args.backend,
        "sampling": {
            "temperature": args.temperature,
            "top_p": args.top_p,
            "top_k": args.top_k,
            "repetition_penalty": args.repetition_penalty,
            "presence_penalty": args.presence_penalty,
            "max_new_tokens": args.max_new_tokens,
            "seed": args.seed,
            "note": ("temperature>0 이므로 표본 추출이 확률적입니다. FACTS 7: n=900, p=0.674 에서 "
                     "서로 독립인 두 실행의 차이에 대한 95% 구간은 ±4.33pp 이므로 팀원 간 1~2pp "
                     "차이는 잡음입니다."),
        },
        "presence_penalty_mechanism": presence,
        "pixel_budget": budget.to_json(),
        "context": {
            "max_model_len": args.max_model_len,
            "max_new_tokens": args.max_new_tokens,
            "limit_mm_per_prompt": {"image": args.limit_mm_images, "video": 0},
            "allow_output_squeeze": bool(args.allow_output_squeeze),
        },
        "engine": {
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "max_num_seqs": args.max_num_seqs,
            "enforce_eager": bool(args.enforce_eager),
            "attn_implementation": "sdpa" if args.backend == "hf" else "vllm 내부 선택",
        },
        "determinism": {
            "seed": args.seed,
            "parser_seed": OFFICIAL_PARSER_SEED,
            "sample_order": "load_mmmu 의 (SUBJECTS 인덱스, id 의 문항 번호) 정렬",
            "vllm_enable_v1_multiprocessing": os.environ.get("VLLM_ENABLE_V1_MULTIPROCESSING"),
            "full_determinism": False,
            "note": ("FACTS 7: enable_full_determinism() 은 CUDA_LAUNCH_BLOCKING=1 을 켜서 소요 시간 "
                     "측정을 무의미하게 만들므로 사용하지 않았습니다."),
        },
        "metrics_accuracy_scale": "fraction_0_1 (백분율로 쓰려면 100을 곱하십시오)",
        "aggregation": "micro / sample-weighted",
        "timing_note": ("total_wall_s 는 이번 프로세스 wall clock + 이어받은 추론 시간입니다. "
                        "model_load_s 는 별도로 측정하여 알파벳순 첫 과목에 엔진 시작 비용이 "
                        "섞이지 않게 했습니다."),
    }


def load_carried_timing(timing_path: Path, skipped_by_subject: Dict[str, int]) -> Dict[str, Dict[str, float]]:
    """이어하기 시, 이전 timing.json 에서 '건너뛴 문항 몫' 의 시간을 비례 환산해 가져옵니다."""
    if not skipped_by_subject or not timing_path.exists():
        return {}
    try:
        previous = json.loads(timing_path.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.warning("이전 timing.json 을 읽지 못했습니다(%s). 건너뛴 문항의 시간은 0으로 남습니다.", exc)
        return {}
    previous_subjects = previous.get("by_subject") or {}
    carried: Dict[str, Dict[str, float]] = {}
    for subject, n_skipped in skipped_by_subject.items():
        row = previous_subjects.get(subject)
        if not isinstance(row, dict):
            continue
        prev_n = float(row.get("n") or 0)
        prev_wall = float(row.get("wall_s") or 0.0)
        if prev_n <= 0 or prev_wall <= 0:
            continue
        n_carry = min(prev_n, float(n_skipped))
        carried[subject] = {"n": n_carry, "wall_s": prev_wall * (n_carry / prev_n)}
    if carried:
        LOG.info("이전 실행에서 시간 이어받기: %d과목, 합계 %s",
                 len(carried), _hms(sum(v["wall_s"] for v in carried.values())))
    return carried


def release_images(requests: Sequence[PreparedRequest]) -> None:
    """처리가 끝난 과목의 PIL 이미지를 닫아 메모리를 되돌립니다.

    900문항을 끝까지 들고 있으면 디코딩된 픽셀 버퍼가 누적되어 수 GB가 됩니다.
    채점 단계는 이미지를 쓰지 않으므로(선택지와 정답만 사용) 안전합니다.
    """
    for req in requests:
        for img in req.mm_images:
            try:
                img.close()
            except Exception:
                pass
        req.mm_images = []
        try:
            req.sample.images = []
        except Exception:
            pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    t_process_start = time.perf_counter()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        min_pixels = parse_pixel_spec(args.min_pixels)
        max_pixels = parse_pixel_spec(args.max_pixels)
    except ValueError as exc:
        parser.error(str(exc))
        return 2
    if min_pixels > max_pixels:
        parser.error("--min-pixels 가 --max-pixels 보다 큽니다.")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 은 1 이상이어야 합니다.")
    if args.limit_mm_images <= 0:
        parser.error("--limit-mm-images 는 1 이상이어야 합니다.")

    subjects = None
    if args.subjects:
        subjects = [s.strip() for s in str(args.subjects).split(",") if s.strip()]
        unknown = [s for s in subjects if s not in mmmu_data.SUBJECTS]
        if unknown:
            parser.error("--subjects 에 없는 과목이 있습니다: {}".format(unknown))

    out_dir = resolve_out_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(out_dir, args.verbose)

    _banner("MMMU {} 베이스라인 평가 — {}".format(args.split, args.model))
    LOG.info("시작(UTC): %s", _now_utc_iso())
    LOG.info("명령행: %s", " ".join([sys.executable] + list(sys.argv)))
    LOG.info("출력 디렉터리: %s", out_dir)
    LOG.info("백엔드: %s (%s)", args.backend,
             "약 15~45분 예상" if args.backend == "vllm" else "batch=1, 약 2~6시간 예상 (FACTS 13)")

    announce_pixel_budget(min_pixels, max_pixels, str(args.min_pixels), str(args.max_pixels))

    # --- 1) 데이터 ---------------------------------------------------------
    _banner("MMMU 데이터 로드")
    LOG.info("--data-path = %s (split=%s, revision=%s)", args.data_path, args.split, args.dataset_revision)
    LOG.info("FACTS 4: MMMU 는 'all' config 이 없어 30개 과목 config 을 각각 로드해 이어붙입니다.")
    t_data = time.perf_counter()
    samples = mmmu_data.load_mmmu(
        args.data_path, split=args.split, revision=args.dataset_revision, subjects=subjects)
    if args.limit is not None:
        samples = list(samples)[: args.limit]
    LOG.info("로드 완료: %s문항, %s", _i(len(samples)), _hms(time.perf_counter() - t_data))

    full_run = args.limit is None and not subjects
    data_stats = validate_sample_set(samples, args, full_run)
    reportable = bool(full_run and args.split == "validation"
                      and data_stats["n"] == EXPECTED_VALIDATION_N)
    if not reportable:
        LOG.warning("[주의] 이 실행은 보고용 전체 실행이 아닙니다(--limit/--subjects 또는 문항 수 불일치). "
                    "metrics.json 을 보고서의 대표 숫자로 쓰지 마십시오.")

    # --- 2) 프로세서 / 픽셀 예산 ------------------------------------------
    _banner("프로세서 및 픽셀 예산 확정")
    processor, tokenizer, budget = resolve_processor(
        args.model, args.model_revision, min_pixels, max_pixels,
        str(args.min_pixels), str(args.max_pixels))

    presence = presence_penalty_record(args)
    run_config = make_run_config(args, out_dir, budget, presence, subjects)

    # --- 3) 환경 기록 (모델 로드 전) --------------------------------------
    _banner("실험 환경 기록 (모델 로드 전)")
    attn_impl = "sdpa" if args.backend == "hf" else "vllm 내부 백엔드 (transformers attn_implementation 미적용)"
    try:
        env = write_environment(out_dir, args, budget, data_stats, attn_impl, run_config)
    except Exception as exc:
        if args.dry_run:
            LOG.warning("env.json 기록 실패(dry-run 이므로 계속 진행): %s", exc)
            env = {}
        else:
            LOG.error("env.json 을 기록하지 못했습니다: %s", exc)
            LOG.error("환경 기록은 이 과제의 필수 산출물이므로 중단합니다.")
            return 2

    # FACTS 12: 보고용 실행은 작업트리가 깨끗해야 재현이 가능합니다.
    git_info = (env or {}).get("git") or {}
    if reportable and git_info.get("dirty") and not args.allow_dirty:
        LOG.error("git 작업트리가 dirty 입니다(commit=%s, branch=%s).",
                  git_info.get("commit"), git_info.get("branch"))
        LOG.error("보고용 실행은 커밋 후에 수행하십시오. 그래도 진행하려면 --allow-dirty 를 주십시오.")
        return 2

    # --- 4) 프롬프트 생성 + 토큰 사전 계산 --------------------------------
    _banner("프롬프트 생성 및 토큰 사전 계산 (템플릿: {})".format(args.template))
    t_prep = time.perf_counter()
    prepared = prepare_requests(samples, processor, tokenizer, args.template, budget)
    LOG.info("프롬프트 %s건 생성, %s", _i(len(prepared)), _hms(time.perf_counter() - t_prep))
    for req in prepared:
        # 문항별 vision/prompt 토큰은 run.log 에 전부 남깁니다(stdout 에는 출력하지 않음).
        LOG.debug("토큰 사전계산 %-34s items=%d vision=%6d prompt=%6d %s",
                  req.sample_id, req.n_mm_items, req.vision_tokens, req.prompt_tokens, req.per_image)
    precount = check_context_budget(
        prepared, args.max_model_len, args.max_new_tokens, args.limit_mm_images,
        args.allow_output_squeeze)
    n_repeat_markers = sum(1 for r in prepared if r.n_mm_items > len(r.sample.image_indices or []))
    if n_repeat_markers:
        LOG.info("같은 이미지를 여러 번 참조하는 문항 %d건(FACTS 4a). 마커 등장 순서대로 이미지를 "
                 "반복 전달하므로 vision token 도 반복 계산됩니다.", n_repeat_markers)
    precount["n_samples_with_repeated_markers"] = n_repeat_markers
    precount["total_vision_tokens"] = sum(r.vision_tokens for r in prepared)
    precount["total_prompt_tokens"] = sum(r.prompt_tokens for r in prepared)

    config_path = out_dir / "config.json"
    config: Dict[str, Any] = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "created_at_utc": _now_utc_iso(),
        "reportable": reportable,
        "dry_run": bool(args.dry_run),
        "cli": vars(args),
        "resolved": run_config,
        "model": {"repo_id": args.model, "revision": args.model_revision,
                  "dtype": "bfloat16", "attn_implementation": attn_impl},
        "dataset": {"repo_id_or_path": str(args.data_path), "revision": args.dataset_revision,
                    "split": args.split, **data_stats},
        "token_precount": precount,
        "resume": {},
        "backend_detail": {},
        "run_summary": {},
    }
    _json_dump(config, config_path)
    LOG.info("설정 기록: %s", config_path)

    if args.dry_run:
        _banner("--dry-run 완료 (모델은 적재하지 않았습니다)")
        LOG.info("문항 %s건의 프롬프트와 토큰 수를 검증했습니다.", _i(len(prepared)))
        LOG.info("vision token 합계 %s / prompt token 합계 %s",
                 _i(precount["total_vision_tokens"]), _i(precount["total_prompt_tokens"]))
        LOG.info("최대 prompt %s 토큰(%s), 여유 %s 토큰",
                 _i(precount["max_prompt_tokens"]), precount["max_prompt_tokens_id"],
                 _i(args.max_model_len - precount["max_prompt_tokens"] - args.max_new_tokens))
        LOG.info("문항별 상세 토큰 수는 %s 에 기록되어 있습니다.", out_dir / "run.log")
        return 0

    # --- 5) 이어하기 준비 --------------------------------------------------
    pred_path = out_dir / "predictions.jsonl"
    existing, _broken = load_existing_predictions(pred_path)
    sample_ids = {s.id for s in samples}
    extras = sorted({rec["id"] for rec in existing} - sample_ids)
    if extras:
        LOG.error("predictions.jsonl 에 이번 실행 대상이 아닌 id 가 %d개 있습니다(예: %s).",
                  len(extras), extras[:5])
        LOG.error("다른 설정의 결과와 섞이면 점수가 오염됩니다. --out 을 다른 디렉터리로 지정하십시오.")
        return 2
    done_ids = {rec["id"] for rec in existing}
    if done_ids:
        _banner("이어하기: 기존 결과 {}건을 재사용합니다".format(_i(len(done_ids))))

    groups: Dict[str, List[PreparedRequest]] = {}
    for req in prepared:
        groups.setdefault(req.sample.subject, []).append(req)
    subject_order = [s for s in mmmu_data.SUBJECTS if s in groups]
    subject_order += [s for s in sorted(groups) if s not in subject_order]

    todo_total = sum(1 for req in prepared if req.sample_id not in done_ids)
    skipped_by_subject = {s: sum(1 for r in groups[s] if r.sample_id in done_ids) for s in subject_order}
    carried = load_carried_timing(out_dir / "timing.json", {k: v for k, v in skipped_by_subject.items() if v})
    config["resume"] = {
        "existing_predictions": len(existing),
        "skipped": len(existing),
        "to_generate": todo_total,
        "carried_timing_subjects": sorted(carried),
    }

    # --- 6) 모델 적재 (시간을 따로 측정) ----------------------------------
    model_load_s = 0.0
    backend: Optional[Backend] = None
    if todo_total == 0:
        _banner("생성할 문항이 없습니다. 모델을 적재하지 않고 재채점만 수행합니다.")
    else:
        if args.backend == "vllm":
            backend = VLLMBackend(args, budget)
        else:
            backend = HFBackend(args, processor, budget)
            _banner("presence_penalty 처리 방식 (FACTS 2)")
            if presence["applied"]:
                LOG.warning("transformers 에는 presence_penalty 인자가 없습니다. 본 스크립트의 "
                            "PresencePenaltyLogitsProcessor 로 vLLM 과 동일한 가산식을 재현해 "
                            "presence_penalty=%.3f 를 적용합니다.", args.presence_penalty)
                LOG.warning("이 사실은 config.json 의 resolved.presence_penalty_mechanism 에 기록됩니다.")
            else:
                LOG.warning("[중요] presence_penalty=%.3f 가 적용되지 않습니다(--hf-presence-penalty off). "
                            "보고서에 '적용했다' 고 쓰면 거짓이 됩니다.", args.presence_penalty)
        _banner("모델 적재 ({})".format(args.backend))
        model_load_s = backend.load()
        LOG.info("model_load_s = %.2f초 (%s). 과목별 시간에는 포함되지 않습니다.",
                 model_load_s, _hms(model_load_s))

    # --- 7) 과목별 추론 ----------------------------------------------------
    new_times: Dict[str, Dict[str, float]] = {}
    n_generated = 0
    n_empty = 0
    n_truncated = 0
    if todo_total:
        _banner("추론 시작 — 과목별로 시간을 따로 측정합니다 (총 {}문항)".format(_i(todo_total)))
        with pred_path.open("a", encoding="utf-8") as fh:
            for subject in subject_order:
                reqs = groups[subject]
                todo = [r for r in reqs if r.sample_id not in done_ids]
                if not todo:
                    LOG.info("[%-36s] %d문항 전부 이어받음 -> 건너뜀", subject, len(reqs))
                    release_images(reqs)
                    continue
                LOG.info("[%-36s] 추론 %d문항 시작 (이어받음 %d문항)",
                         subject, len(todo), len(reqs) - len(todo))
                t_sub = time.perf_counter()
                outputs = backend.generate(todo)   # type: ignore[union-attr]
                wall = time.perf_counter() - t_sub

                for req, out in zip(todo, outputs):
                    latency = out.latency_s if out.latency_s is not None else wall / max(1, len(todo))
                    score = provisional_score(req.sample, out.text)
                    record = build_record(req, out, latency, score)
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    n_generated += 1
                    if not out.text.strip():
                        n_empty += 1
                    if out.finish_reason == "length":
                        n_truncated += 1
                fh.flush()
                os.fsync(fh.fileno())   # 접속이 끊겨도 이미 끝난 과목은 디스크에 남아야 합니다.

                new_times[subject] = {"n": float(len(todo)), "wall_s": float(wall)}
                LOG.info("[%-36s] 완료: %s (문항당 %.2f초)",
                         subject, _hms(wall), wall / max(1, len(todo)))
                release_images(reqs)
                gc.collect()
        if backend is not None:
            backend.shutdown()
        LOG.info("추론 완료: %s문항 생성, 빈 응답 %d건, max_new_tokens 까지 생성(잘림 의심) %d건",
                 _i(n_generated), n_empty, n_truncated)
        if n_empty:
            LOG.warning("[경고] 빈 응답 %d건은 파서의 난수 폴백으로 들어갑니다(FACTS 4c). "
                        "metrics.json 의 n_unparseable 과 함께 보고서에 언급하십시오.", n_empty)

    # --- 8) 최종 채점 (난수 시드 고정) ------------------------------------
    _banner("채점 — random.seed({}) 직후 고정 순서로 전체 재채점".format(OFFICIAL_PARSER_SEED))
    LOG.info("FACTS 4c: 공식 파서는 파싱 실패 시 random.choice 로 찍으므로 점수가 순회 순서에 "
             "의존합니다. 이어하기 여부와 무관하게 같은 점수가 나오도록 전체를 다시 채점합니다.")
    t_score = time.perf_counter()
    records, _ = load_existing_predictions(pred_path)
    rec_by_id = {rec["id"]: rec for rec in records}
    missing = [s.id for s in samples if s.id not in rec_by_id]
    if missing:
        LOG.error("응답이 없는 문항이 %d건 있습니다(예: %s).", len(missing), missing[:10])
        LOG.error("조용히 0점 처리하지 않습니다. 같은 --out 으로 다시 실행하면 이어서 생성합니다.")
        return 2
    ordered = [rec_by_id[s.id] for s in samples]
    sample_by_id = {s.id: s for s in samples}
    score_stats = score_all(ordered, sample_by_id)
    rewrite_predictions(pred_path, ordered)
    scoring_s = time.perf_counter() - t_score
    LOG.info("채점 완료: %s문항, 파싱 실패(난수 폴백) %s건, %s",
             _i(score_stats["n"]), _i(score_stats["unparseable"]), _hms(scoring_s))

    metrics = build_metrics(ordered)
    _json_dump(metrics, out_dir / "metrics.json")

    carried_inference = sum(row["wall_s"] for row in carried.values())
    total_wall = (time.perf_counter() - t_process_start) + carried_inference
    timing, missing_timing = build_timing(new_times, carried, total_wall, model_load_s, scoring_s)
    if missing_timing:
        LOG.warning("[경고] 다음 과목은 이번 실행에서 추론하지 않았고 이전 시간 기록도 없어 "
                    "소요 시간이 0으로 남습니다: %s", missing_timing)
    _json_dump(timing, out_dir / "timing.json")

    config["backend_detail"] = backend.describe() if backend is not None else {"backend": "none (재채점만)"}
    config["run_summary"] = {
        "finished_at_utc": _now_utc_iso(),
        "n_samples": len(ordered),
        "n_generated_this_run": n_generated,
        "n_reused_from_previous_run": len(done_ids),
        "n_empty_response": n_empty,
        "n_finish_reason_length": n_truncated,
        "n_unparseable": metrics["n_unparseable"],
        "overall_accuracy_fraction": metrics["overall"]["accuracy"],
        "overall_accuracy_percent": round(metrics["overall"]["accuracy"] * 100.0, 2),
        "published_reference_percent": PUBLISHED_MMMU_VAL,
        "delta_vs_published_pp": round(metrics["overall"]["accuracy"] * 100.0 - PUBLISHED_MMMU_VAL, 2),
        "total_wall_s": timing["total_wall_s"],
        "model_load_s": timing["model_load_s"],
        "inference_s": timing["inference_s"],
        "scoring_s": timing["scoring_s"],
    }
    _json_dump(config, config_path)

    print_summary(metrics, timing, config, out_dir, reportable)
    return 0


def print_summary(
    metrics: Dict[str, Any],
    timing: Dict[str, Any],
    config: Dict[str, Any],
    out_dir: Path,
    reportable: bool,
) -> None:
    overall = metrics["overall"]
    accuracy_pct = overall["accuracy"] * 100.0
    _banner("결과 요약")
    LOG.info("전체        : %4d/%4d = %6.2f%%  (micro / sample-weighted)",
             overall["correct"], overall["n"], accuracy_pct)
    mc = metrics["multiple_choice"]
    oe = metrics["open_ended"]
    LOG.info("객관식만    : %4d/%4d = %6.2f%%", mc["correct"], mc["n"], mc["accuracy"] * 100.0)
    LOG.info("단답형만    : %4d/%4d = %6.2f%%", oe["correct"], oe["n"], oe["accuracy"] * 100.0)
    LOG.info("파싱 실패   : %d건 (공식 파서의 난수 폴백으로 처리, FACTS 4c)", metrics["n_unparseable"])
    LOG.info("공개 점수   : %.1f%% (%s)", PUBLISHED_MMMU_VAL, PUBLISHED_SOURCE)
    LOG.info("차이        : %+.2f pp", accuracy_pct - PUBLISHED_MMMU_VAL)
    LOG.info("주의: 공개된 67.4 는 객관식 847 + 단답형 53 을 모두 포함한 900문항 기준입니다(FACTS 4). "
             "분모가 847 인 '객관식만' 숫자를 67.4 와 나란히 쓰면 비교가 성립하지 않습니다.")
    LOG.info("FACTS 7: n=900, p=0.674 에서 독립 두 실행 차이의 95%% 구간은 ±4.33pp 입니다. "
             "팀원 간 1~2pp 차이는 잡음이며 버그가 아닙니다.")

    LOG.info("-" * 78)
    LOG.info("%-32s %5s %9s %9s", "카테고리", "n", "정확도", "소요(초)")
    for category, row in metrics["by_category"].items():
        t_row = timing["by_category"].get(category, {})
        LOG.info("%-32s %5d %8.2f%% %9.1f", category, row["n"], row["accuracy"] * 100.0,
                 t_row.get("wall_s", 0.0))
    LOG.info("-" * 78)
    LOG.info("%-32s %5s %9s %9s", "과목", "n", "정확도", "소요(초)")
    for subject, row in metrics["by_subject"].items():
        t_row = timing["by_subject"].get(subject, {})
        LOG.info("%-32s %5d %8.2f%% %9.1f", subject, row["n"], row["accuracy"] * 100.0,
                 t_row.get("wall_s", 0.0))
    LOG.info("-" * 78)
    LOG.info("총 소요      : %s (%.1f초)", _hms(timing["total_wall_s"]), timing["total_wall_s"])
    LOG.info("모델 적재    : %s", _hms(timing["model_load_s"]))
    LOG.info("추론         : %s", _hms(timing["inference_s"]))
    LOG.info("채점         : %s", _hms(timing["scoring_s"]))
    presence = config["resolved"]["presence_penalty_mechanism"]
    LOG.info("presence_penalty: 요청 %.3f / 적용 %s / 방식 %s",
             presence["requested"], "예" if presence["applied"] else "아니오", presence["mechanism"])
    LOG.info("산출물: %s", ", ".join(["env.json", "ENVIRONMENT.md", "config.json",
                                      "predictions.jsonl", "metrics.json", "timing.json", "run.log"]))
    LOG.info("경로  : %s", out_dir)
    if not reportable:
        LOG.warning("[주의] 이 실행은 보고용 전체 실행이 아닙니다. 보고서에는 900문항 전체 실행 결과를 쓰십시오.")
    LOG.info("보고서 생성: python src/report.py --run-dir %s", out_dir)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\n[중단] 사용자가 실행을 취소했습니다. 같은 --out 으로 다시 실행하면 이어서 진행합니다.\n")
        sys.exit(130)

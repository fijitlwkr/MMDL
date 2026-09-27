# -*- coding: utf-8 -*-
"""실험 환경 캡처 모듈 — env.json 과 ENVIRONMENT.md 를 생성합니다.

교수님이 요구하신 보고서 항목 "실험 환경 및 설정 (HW infra 및 tool package version 포함)"을
학생이 아무것도 외우거나 손으로 적지 않아도 기계적으로 남기기 위한 모듈입니다.
팀원 4명이 각자 RunPod 파드에서 같은 스택으로 돌렸는지 확인하는 `--check` 모드도 함께 제공합니다.

설계 원칙
1) 모든 탐지(probe)는 개별적으로 감쌉니다. nvcc 처럼 보통 설치되어 있지 않은 도구 하나 때문에
   캡처 전체가 죽으면 안 됩니다. 실패한 값은 null 이 되고, 실패 이유는
   notes.probe_errors 에 "항목 경로 -> 이유" 형태로 반드시 기록됩니다(조용히 넘기지 않습니다).
2) 리비전은 "main" 같은 가변 포인터가 아니라 해석된 40자 커밋 SHA 로 기록합니다(FACTS 6).
   MMMU/MMMU 데이터 파일은 67.4 가 발표된 이후에도 세 번 변경되었으므로, 리비전 없는
   "MMMU/MMMU" 문자열은 재현 가능한 식별자가 아닙니다.
3) 이 파일은 공개 GitHub 저장소에 커밋됩니다. 따라서 API 키·토큰 같은 비밀값과
   파드의 공인 IP·개방 포트는 수집하지 않습니다(화이트리스트 + 비밀값 정규식 이중 차단).
4) CUDA 버전은 세 가지를 각각 따로 기록하고, 서로 달라도 정상이라는 설명을 notes 에 넣습니다.
   FACTS 9: 학생들이 여기서 몇 시간을 낭비합니다.

단독 실행 예
    python -m src.capture_env --out outputs/env            # env.json + ENVIRONMENT.md 생성
    python -m src.capture_env                              # ENVIRONMENT.md 내용을 화면에 출력
    python -m src.capture_env --check outputs/run_a/env.json   # 팀원 환경과 비교
"""

from __future__ import annotations

import argparse
import importlib.metadata as _md
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# ----------------------------------------------------------------------------
# 상수
# ----------------------------------------------------------------------------

#: env.json 스키마 버전. 키 구성을 바꾸면 올립니다(--check 가 호환성 경고에 사용합니다).
SCHEMA_VERSION = "1.0.0"

#: 이 파일이 src/ 안에 있으므로 저장소 루트는 한 단계 위입니다. git 탐지의 기준 경로입니다.
REPO_ROOT = Path(__file__).resolve().parents[1]

# FACTS 0 / FACTS 6 에서 확정된 기본 아티팩트. eval 스크립트가 extra 로 덮어쓸 수 있습니다.
DEFAULT_MODEL_REPO = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_MODEL_REVISION = "ebb281ec70b05090aa6165b016eac8ec08e71b17"
DEFAULT_DATASET_REPO = "MMMU/MMMU"
DEFAULT_DATASET_REVISION = "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68"
DEFAULT_SPLIT = "validation"

#: INTERFACES 의 packages 스키마에 명시된 13개 핵심 패키지. 순서와 철자(하이픈)를 그대로 씁니다.
KEY_PACKAGES: tuple[str, ...] = (
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
)

#: 결과 재현에 직접 영향을 주는 환경 변수만 화이트리스트로 수집합니다.
#  os.environ 전체를 덮어 쓰면 토큰이 섞여 들어가므로 절대 전체를 담지 않습니다.
ENV_VAR_WHITELIST: tuple[str, ...] = (
    "HF_HOME",
    "HF_HUB_CACHE",
    "HF_DATASETS_CACHE",
    "HF_HUB_OFFLINE",
    "HF_XET_HIGH_PERFORMANCE",
    "HF_HUB_ENABLE_HF_TRANSFER",
    "TRANSFORMERS_CACHE",
    "CUDA_HOME",
    "CUDA_VERSION",
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "NVIDIA_DRIVER_CAPABILITIES",
    "LD_LIBRARY_PATH",
    "PYTORCH_CUDA_ALLOC_CONF",
    "CUDA_LAUNCH_BLOCKING",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "TOKENIZERS_PARALLELISM",
    "PYTHONHASHSEED",
    "VLLM_USE_V1",
    "VLLM_ENABLE_V1_MULTIPROCESSING",
    "VLLM_BATCH_INVARIANT",
    "VLLM_WORKER_MULTIPROC_METHOD",
    "VLLM_ATTENTION_BACKEND",
    "VLLM_LOGGING_LEVEL",
    "TZ",
)

#: 화이트리스트에 실수로 비밀값이 추가되더라도 값이 새지 않도록 하는 2차 방어선입니다.
_SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.I)

#: 40자 16진수 = HuggingFace 커밋 SHA.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: https://user:token@github.com/... 형태로 들어간 자격 증명을 지우기 위한 패턴입니다.
_URL_CRED_RE = re.compile(r"//[^/\s@]*@")


# ----------------------------------------------------------------------------
# 공통 유틸리티
# ----------------------------------------------------------------------------

def _reason(exc: BaseException) -> str:
    """예외를 사람이 읽을 수 있는 한 줄짜리 한국어 실패 이유로 바꿉니다."""
    if isinstance(exc, FileNotFoundError):
        base = "실행 파일 또는 경로를 찾을 수 없습니다"
    elif isinstance(exc, subprocess.TimeoutExpired):
        base = "명령이 제한 시간 안에 끝나지 않았습니다"
    elif isinstance(exc, PermissionError):
        base = "접근 권한이 없습니다"
    elif isinstance(exc, (ImportError, ModuleNotFoundError)):
        base = "파이썬 모듈을 임포트할 수 없습니다"
    elif isinstance(exc, (OSError, IOError)):
        base = "운영체제 호출이 실패했습니다"
    else:
        base = "탐지에 실패했습니다"
    msg = " ".join(str(exc).split())[:300]
    return f"{base} ({type(exc).__name__}: {msg})" if msg else base


class _Recorder:
    """탐지 실패 이유와 경고를 모으는 수집기입니다.

    probe() 는 예외를 삼키지 않고 '기록'합니다. 값은 None 이 되지만 왜 None 인지는
    항상 env.json 안에 남습니다. 이것이 '조용한 실패'와의 차이입니다.
    """

    def __init__(self) -> None:
        self.errors: dict[str, str] = {}
        self.warnings: list[str] = []
        self.notes: dict[str, str] = {}

    def probe(self, path: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - 탐지는 무엇이 터져도 캡처를 막지 않습니다.
            self.errors[path] = _reason(exc)
            return default

    def fail(self, path: str, reason: str) -> None:
        self.errors[path] = reason

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def note(self, key: str, text: str) -> None:
        self.notes[key] = text


def _run(cmd: list[str], timeout: float = 30.0, cwd: str | os.PathLike[str] | None = None) -> str:
    """외부 명령을 실행하고 표준출력을 돌려줍니다. 실패하면 예외를 올립니다.

    LC_ALL/LANG 을 C 로 고정하는 이유: 한국어 로케일에서는 lscpu 가 필드 이름을
    "모델명:" 처럼 번역해서 출력하므로 "Model name:" 파싱이 깨집니다.
    """
    exe = shutil.which(cmd[0])
    if exe is None:
        raise FileNotFoundError(f"{cmd[0]} 을(를) PATH 에서 찾을 수 없습니다")
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    proc = subprocess.run(  # noqa: S603 - 인자는 모두 이 모듈 안에서 만든 고정 값입니다.
        [exe, *cmd[1:]],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        detail = " ".join((proc.stderr or proc.stdout or "").split())[:200]
        raise RuntimeError(f"`{' '.join(cmd)}` 가 종료 코드 {proc.returncode} 로 실패했습니다: {detail}")
    return proc.stdout


def _read_text(path: str | os.PathLike[str], limit: int = 1_000_000) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")[:limit]


def _to_int(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _vtuple(version: Any) -> tuple[int, ...] | None:
    """'2.8.0+cu128' -> (2, 8, 0). 버전 비교용 최소 파서입니다(외부 의존성 없이)."""
    if not version:
        return None
    nums = re.findall(r"\d+", str(version))
    if not nums:
        return None
    return tuple(int(n) for n in nums[:3])


def _atomic_write(path: Path, text: str) -> None:
    """임시 파일에 쓰고 교체합니다. 중간에 죽어도 반쪽짜리 env.json 이 남지 않습니다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _flat_get(data: Any, dotted: str) -> tuple[bool, Any]:
    """'packages.transformers' 처럼 점으로 구분된 경로를 찾습니다. -> (존재여부, 값)"""
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _deep_merge(base: dict, overlay: dict) -> dict:
    """overlay 가 우선합니다. 단 overlay 의 None 은 이미 탐지된 값을 지우지 않습니다."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        elif value is None and out.get(key) is not None:
            continue
        else:
            out[key] = value
    return out


def _redact_env_value(name: str, value: str) -> str:
    if _SECRET_NAME_RE.search(name):
        return "<비밀값이므로 기록하지 않음>"
    return value


# torch 임포트는 수 초가 걸리고 드물게 OSError 로 죽기도 하므로 한 번만 시도하고 캐시합니다.
_TORCH_MOD: Any = None
_TORCH_ERR: BaseException | None = None


def _import_torch() -> Any:
    global _TORCH_MOD, _TORCH_ERR
    if _TORCH_MOD is None and _TORCH_ERR is None:
        try:
            import torch  # noqa: PLC0415 - 지연 임포트(의도적)

            _TORCH_MOD = torch
        except BaseException as exc:  # noqa: BLE001
            _TORCH_ERR = exc
    if _TORCH_MOD is None:
        raise RuntimeError(f"torch 를 임포트할 수 없습니다: {_TORCH_ERR}")
    return _TORCH_MOD


# ----------------------------------------------------------------------------
# 개별 탐지기 (hardware)
# ----------------------------------------------------------------------------

def _probe_nvidia_smi_text() -> str:
    """nvidia-smi 의 헤더가 들어 있는 기본 출력. CUDA 런타임/드라이버 버전 파싱에 씁니다."""
    return _run(["nvidia-smi"], timeout=60.0)


def _probe_gpus_via_smi() -> list[dict[str, Any]]:
    out = _run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        timeout=60.0,
    )
    gpus: list[dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        gpus.append(
            {
                "index": parts[0],
                "name": parts[1],
                "vram_mib": _to_int(parts[2]),
                "driver_version": parts[3],
                "compute_cap": parts[4] if len(parts) > 4 else None,
                "source": "nvidia-smi",
            }
        )
    if not gpus:
        raise RuntimeError("nvidia-smi 출력에서 GPU 를 한 개도 찾지 못했습니다")
    return gpus


def _probe_gpus_via_torch() -> list[dict[str, Any]]:
    """nvidia-smi 가 없는 환경(예: 학생 노트북)을 위한 2차 경로입니다."""
    torch = _import_torch()
    if not torch.cuda.is_available():
        raise RuntimeError("torch.cuda.is_available() 이 False 입니다 (CUDA GPU 가 없습니다)")
    gpus: list[dict[str, Any]] = []
    for i in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(i)
        gpus.append(
            {
                "index": str(i),
                "name": props.name,
                "vram_mib": int(props.total_memory // (1024 * 1024)),
                "driver_version": None,
                "compute_cap": f"{props.major}.{props.minor}",
                "source": "torch.cuda",
            }
        )
    if not gpus:
        raise RuntimeError("torch.cuda.device_count() 가 0 입니다")
    return gpus


def _probe_cpu_model() -> str:
    """lscpu -> /proc/cpuinfo -> sysctl(macOS) -> platform 순서로 내려갑니다."""
    try:
        out = _run(["lscpu"], timeout=30.0)
        for key in ("Model name", "BIOS Model name"):
            m = re.search(rf"^{key}:\s*(.+)$", out, re.MULTILINE)
            if m:
                return " ".join(m.group(1).split())
    except BaseException:  # noqa: BLE001 - 다음 경로를 시도합니다.
        pass
    try:
        info = _read_text("/proc/cpuinfo", limit=200_000)
        m = re.search(r"^model name\s*:\s*(.+)$", info, re.MULTILINE)
        if m:
            return " ".join(m.group(1).split())
        m = re.search(r"^Model\s*:\s*(.+)$", info, re.MULTILINE)  # ARM 계열
        if m:
            return " ".join(m.group(1).split())
    except BaseException:  # noqa: BLE001
        pass
    if sys.platform == "darwin":
        return " ".join(_run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=15.0).split())
    proc = platform.processor() or platform.machine()
    if not proc:
        raise RuntimeError("CPU 모델명을 어떤 경로로도 읽지 못했습니다")
    return proc


def _probe_cpu_count() -> int:
    """컨테이너에 실제로 할당된 논리 CPU 수를 우선합니다.

    os.cpu_count() 는 컨테이너 안에서도 호스트 전체 코어 수를 보여 줄 수 있으므로,
    가능하면 프로세스 affinity 기준으로 셉니다(RunPod 파드는 호스트의 일부만 받습니다).
    """
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    count = os.cpu_count()
    if not count:
        raise RuntimeError("논리 CPU 수를 읽지 못했습니다")
    return int(count)


def _probe_ram_gib() -> float:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        m = re.search(r"^MemTotal:\s*(\d+)\s*kB", _read_text(meminfo, limit=100_000), re.MULTILINE)
        if m:
            return round(int(m.group(1)) / (1024.0 * 1024.0), 2)
        raise RuntimeError("/proc/meminfo 에서 MemTotal 을 찾지 못했습니다")
    if sys.platform == "darwin":
        total = _to_int(_run(["sysctl", "-n", "hw.memsize"], timeout=15.0))
        if total:
            return round(total / (1024.0**3), 2)
    raise RuntimeError("시스템 RAM 총량을 읽을 수 있는 경로가 없습니다")


def _probe_cgroup_mem_limit_gib() -> float | None:
    """컨테이너 메모리 상한. cgroup v2 -> v1 순서. 무제한이면 None."""
    for path in (Path("/sys/fs/cgroup/memory.max"), Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        if path.is_file():
            raw = _read_text(path, limit=1000).strip()
            if raw == "max":
                return None
            value = _to_int(raw)
            # cgroup v1 은 '무제한'을 2^63 에 가까운 거대한 수로 표현합니다.
            if value is None or value <= 0 or value >= (1 << 62):
                return None
            return round(value / (1024.0**3), 2)
    return None


def _capture_hardware(rec: _Recorder) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    gpus = rec.probe("hardware.gpu(nvidia-smi)", _probe_gpus_via_smi)
    if not gpus:
        # nvidia-smi 가 없어도 torch 로 한 번 더 시도합니다(두 실패 이유가 모두 기록됩니다).
        gpus = rec.probe("hardware.gpu(torch)", _probe_gpus_via_torch)

    gpu_name: str | None = None
    gpu_count: int | None = None
    vram_total_mib: int | None = None
    if gpus:
        names = sorted({g["name"] for g in gpus if g.get("name")})
        gpu_name = " + ".join(names) if names else None
        gpu_count = len(gpus)
        vrams = [g["vram_mib"] for g in gpus if isinstance(g.get("vram_mib"), int)]
        # vram_total_mib = 파드 전체 VRAM 합계입니다. GPU 별 상세는 notes.gpu_detail 에 남깁니다.
        vram_total_mib = sum(vrams) if len(vrams) == len(gpus) else None
        if vram_total_mib is None:
            rec.fail("hardware.vram_total_mib", "일부 GPU 의 memory.total 을 정수로 읽지 못해 합계를 만들 수 없습니다")
        rec.note(
            "gpu_detail",
            "; ".join(
                f"GPU {g['index']}: {g['name']}, {g['vram_mib']} MiB"
                + (f", 드라이버 {g['driver_version']}" if g.get("driver_version") else "")
                + (f", sm_{str(g['compute_cap']).replace('.', '')}" if g.get("compute_cap") else "")
                + f" (출처 {g['source']})"
                for g in gpus
            ),
        )
        if len(names) > 1:
            rec.warn("한 파드에 서로 다른 GPU 모델이 섞여 있습니다. 성능/정확도 비교 시 주의하십시오.")
    else:
        rec.warn(
            "GPU 를 찾지 못했습니다. 이 env.json 은 GPU 가 없는 기계에서 만들어진 것이므로 "
            "보고서용 실험 환경 기록으로 쓸 수 없습니다(RunPod 파드 안에서 다시 실행하십시오)."
        )

    cpu_model = rec.probe("hardware.cpu_model", _probe_cpu_model)
    cpu_count = rec.probe("hardware.cpu_count", _probe_cpu_count)
    ram_gib = rec.probe("hardware.ram_gib", _probe_ram_gib)

    host_cpu = os.cpu_count()
    if cpu_count is not None and host_cpu:
        rec.note(
            "cpu_detail",
            f"프로세스에 할당된 논리 CPU {cpu_count}개 / os.cpu_count() 기준 {host_cpu}개. "
            "컨테이너에서는 두 값이 다를 수 있으며, 할당된 값이 실제 전처리 병렬도를 결정합니다.",
        )

    cgroup_limit = rec.probe("hardware.cgroup_mem_limit_gib", _probe_cgroup_mem_limit_gib)
    if ram_gib is not None:
        detail = f"시스템 RAM {ram_gib} GiB"
        if cgroup_limit:
            detail += f", 컨테이너 메모리 상한 {cgroup_limit} GiB (cgroup)"
        else:
            detail += ", 컨테이너 메모리 상한은 설정되어 있지 않거나 읽을 수 없습니다"
        rec.note("memory_detail", detail)

    # 키 구성은 INTERFACES 의 hardware 스키마와 정확히 일치해야 합니다.
    # 두 번째 반환값(GPU 상세 목록)은 driver_cuda 탐지의 드라이버 버전 보조 경로로만 씁니다.
    hardware = {
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "vram_total_mib": vram_total_mib,
        "cpu_model": cpu_model,
        "cpu_count": cpu_count,
        "ram_gib": ram_gib,
    }
    return hardware, list(gpus or [])


# ----------------------------------------------------------------------------
# 개별 탐지기 (driver_cuda) — FACTS 9
# ----------------------------------------------------------------------------

def _capture_driver_cuda(rec: _Recorder, gpus: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    smi_text = rec.probe("driver_cuda.nvidia_smi", _probe_nvidia_smi_text)

    def _smi_cuda() -> str:
        if not smi_text:
            raise RuntimeError("nvidia-smi 출력을 얻지 못했습니다")
        m = re.search(r"CUDA Version:\s*([0-9]+\.[0-9]+)", smi_text)
        if not m:
            raise RuntimeError("nvidia-smi 헤더에서 'CUDA Version' 을 찾지 못했습니다")
        return m.group(1)

    def _smi_driver() -> str:
        if not smi_text:
            raise RuntimeError("nvidia-smi 출력을 얻지 못했습니다")
        m = re.search(r"Driver Version:\s*([0-9][0-9.]*)", smi_text)
        if not m:
            raise RuntimeError("nvidia-smi 헤더에서 'Driver Version' 을 찾지 못했습니다")
        return m.group(1)

    def _nvcc() -> str:
        out = _run(["nvcc", "--version"], timeout=30.0)
        m = re.search(r"\bV([0-9]+\.[0-9]+\.[0-9]+)", out)
        if m:
            return m.group(1)
        m = re.search(r"release\s+([0-9]+\.[0-9]+)", out)
        if m:
            return m.group(1)
        raise RuntimeError("nvcc --version 출력에서 버전을 파싱하지 못했습니다")

    def _torch_cuda() -> str:
        torch = _import_torch()
        value = getattr(torch.version, "cuda", None)
        if not value:
            raise RuntimeError("torch.version.cuda 가 None 입니다 (CPU 전용 빌드일 수 있습니다)")
        return str(value)

    nvidia_smi_cuda = rec.probe("driver_cuda.nvidia_smi_cuda", _smi_cuda)
    driver_version = rec.probe("driver_cuda.driver_version", _smi_driver)
    if driver_version is None:
        # 헤더 파싱이 실패하면 --query-gpu 로 이미 읽어 둔 GPU별 driver_version 을 씁니다.
        for gpu in gpus or []:
            if gpu.get("driver_version"):
                driver_version = str(gpu["driver_version"])
                break
    nvcc_version = rec.probe("driver_cuda.nvcc_version", _nvcc)
    if nvcc_version is None:
        # FACTS 9: nvcc 는 보통 없습니다. null 이어도 전혀 문제가 아니라는 점을 이유에 명시합니다.
        rec.errors["driver_cuda.nvcc_version"] = (
            rec.errors.get("driver_cuda.nvcc_version", "")
            + " / FACTS 9: nvcc(로컬 CUDA 툴킷)는 컨테이너에 없는 것이 정상이며, "
            "미리 빌드된 PyTorch 휠과는 무관하므로 이 값이 null 이어도 고칠 것이 없습니다."
        ).strip()
    torch_version_cuda = rec.probe("driver_cuda.torch_version_cuda", _torch_cuda)

    def _torch_detail() -> str:
        torch = _import_torch()
        bits = [f"torch {torch.__version__}"]
        bits.append(f"torch.version.cuda={getattr(torch.version, 'cuda', None)}")
        try:
            bits.append(f"cudnn={torch.backends.cudnn.version()}")
        except BaseException:  # noqa: BLE001
            bits.append("cudnn=알 수 없음")
        try:
            bits.append(f"cuda.is_available()={torch.cuda.is_available()}")
        except BaseException:  # noqa: BLE001
            bits.append("cuda.is_available()=알 수 없음")
        return ", ".join(bits)

    detail = rec.probe("driver_cuda.torch_detail", _torch_detail)
    if detail:
        rec.note("torch_detail", detail)

    # FACTS 9 의 드라이버 하한 검증. 여기서 잡히면 실행 전에 파드를 바꿀 수 있습니다.
    drv = _vtuple(driver_version)
    tc = _vtuple(torch_version_cuda)
    if drv and tc:
        if tc[0] >= 13 and drv[0] < 580:
            rec.warn(
                f"torch 가 CUDA {torch_version_cuda} 로 빌드되었는데 드라이버가 {driver_version} 입니다. "
                "CUDA 13.x 는 드라이버 580 이상을 요구합니다(FACTS 9). 실행이 실패할 수 있습니다."
            )
        elif tc[0] == 12 and drv[0] < 525:
            rec.warn(
                f"torch 가 CUDA {torch_version_cuda} 로 빌드되었는데 드라이버가 {driver_version} 입니다. "
                "CUDA 12.x 는 드라이버 525 이상을 요구합니다(FACTS 9)."
            )

    return {
        "nvidia_smi_cuda": nvidia_smi_cuda,
        "torch_version_cuda": torch_version_cuda,
        "nvcc_version": nvcc_version,
        "driver_version": driver_version,
    }


# ----------------------------------------------------------------------------
# 개별 탐지기 (os / 컨테이너 / RunPod)
# ----------------------------------------------------------------------------

def _parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip().lower()] = value.strip().strip('"').strip("'")
    return data


def _probe_os_release() -> dict[str, Any]:
    for candidate in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        if candidate.is_file():
            parsed = _parse_os_release(_read_text(candidate, limit=20_000))
            return {
                "id": parsed.get("id"),
                "name": parsed.get("name"),
                "pretty_name": parsed.get("pretty_name"),
                "version_id": parsed.get("version_id"),
                "version_codename": parsed.get("version_codename"),
            }
    if sys.platform == "darwin":
        # macOS 는 os-release 가 없습니다. 개발용 노트북에서도 값이 비지 않도록 채웁니다.
        return {
            "id": "macos",
            "name": "macOS",
            "pretty_name": f"macOS {platform.mac_ver()[0]}".strip(),
            "version_id": platform.mac_ver()[0] or None,
            "version_codename": None,
        }
    raise FileNotFoundError("/etc/os-release 가 없습니다")


def _probe_container_hints() -> list[str]:
    hints: list[str] = []
    if Path("/.dockerenv").exists():
        hints.append("/.dockerenv 파일이 존재합니다 (Docker)")
    if Path("/run/.containerenv").exists():
        hints.append("/run/.containerenv 파일이 존재합니다 (Podman)")
    cgroup = Path("/proc/1/cgroup")
    if cgroup.is_file():
        text = _read_text(cgroup, limit=50_000)
        for marker, label in (
            ("docker", "PID 1 cgroup 에 docker 문자열이 있습니다"),
            ("kubepods", "PID 1 cgroup 에 kubepods 문자열이 있습니다 (Kubernetes)"),
            ("containerd", "PID 1 cgroup 에 containerd 문자열이 있습니다"),
            ("lxc", "PID 1 cgroup 에 lxc 문자열이 있습니다"),
        ):
            if marker in text:
                hints.append(label)
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        hints.append("KUBERNETES_SERVICE_HOST 환경 변수가 설정되어 있습니다")
    if os.environ.get("RUNPOD_POD_ID"):
        hints.append("RUNPOD_POD_ID 환경 변수가 설정되어 있습니다 (RunPod 파드)")
    return hints


def _capture_os(rec: _Recorder) -> dict[str, Any]:
    os_release = rec.probe("os.os_release", _probe_os_release, default={})
    hints = rec.probe("os.container.hints", _probe_container_hints, default=[]) or []

    def _libc() -> str:
        name, version = platform.libc_ver()
        if not name:
            raise RuntimeError("platform.libc_ver() 가 빈 값을 돌려주었습니다 (리눅스가 아닐 수 있습니다)")
        return f"{name} {version}".strip()

    # RunPod 파드 식별자. 공인 IP/개방 포트/API 키는 공개 저장소에 남기면 안 되므로 수집하지 않습니다.
    runpod = {
        "pod_id": os.environ.get("RUNPOD_POD_ID"),
        "pod_hostname": os.environ.get("RUNPOD_POD_HOSTNAME"),
        "gpu_count": os.environ.get("RUNPOD_GPU_COUNT"),
        "cpu_count": os.environ.get("RUNPOD_CPU_COUNT"),
        "mem_gb": os.environ.get("RUNPOD_MEM_GB"),
        "datacenter_id": os.environ.get("RUNPOD_DC_ID"),
        "volume_id": os.environ.get("RUNPOD_VOLUME_ID"),
        "volume_path": os.environ.get("RUNPOD_VOLUME_PATH"),
        "endpoint_id": os.environ.get("RUNPOD_ENDPOINT_ID"),
    }
    if not any(runpod.values()):
        rec.fail(
            "os.runpod",
            "RunPod 환경 변수가 하나도 없습니다. RunPod 파드 밖에서 실행한 경우이며, 그 자체가 오류는 아닙니다.",
        )

    # 이미지 태그는 환경 변수로 주입된 경우에만 알 수 있습니다(FACTS 8).
    image_tag = None
    for name in ("RUNPOD_IMAGE_NAME", "RUNPOD_IMAGE", "IMAGE_NAME", "DOCKER_IMAGE", "CONTAINER_IMAGE"):
        if os.environ.get(name):
            image_tag = f"{os.environ[name]} (환경 변수 {name})"
            break
    if image_tag is None:
        rec.fail(
            "os.container.image_tag",
            "컨테이너 이미지 태그를 알려 주는 환경 변수가 없습니다. RunPod 템플릿의 환경 변수에 "
            "RUNPOD_IMAGE_NAME 을 추가하면 자동으로 기록됩니다(FACTS 8).",
        )
    # FACTS 8: 컨테이너 내부에서는 자기 이미지의 다이제스트를 읽을 수 없습니다.
    # RepoDigests 는 Docker 데몬 메타데이터에 있고, 로컬 image ID 는 전혀 다른 해시입니다.
    # 따라서 이 값은 구조적으로 null 이며, 필요하면 레지스트리에 HEAD 요청을 보내 밖에서 구해야 합니다.
    image_digest = None
    rec.fail(
        "os.container.image_digest",
        "FACTS 8: 컨테이너 안에서는 자신의 이미지 다이제스트를 읽을 수 없습니다(RepoDigests 는 Docker "
        "데몬 메타데이터이고 로컬 image ID 는 다른 해시입니다). 구조적으로 null 입니다.",
    )

    relevant_env: dict[str, str] = {}
    for name in ENV_VAR_WHITELIST:
        if name in os.environ:
            relevant_env[name] = _redact_env_value(name, os.environ[name])

    # 결과 해석을 망치는 환경 변수 설정을 미리 경고합니다.
    if relevant_env.get("CUDA_LAUNCH_BLOCKING") == "1":
        rec.warn(
            "CUDA_LAUNCH_BLOCKING=1 이 설정되어 있습니다. 모든 CUDA 런치가 직렬화되어 "
            "교수님이 요구한 경과 시간 표가 무의미해집니다(FACTS 7). 해제하고 다시 측정하십시오."
        )
    if relevant_env.get("HF_HUB_ENABLE_HF_TRANSFER"):
        rec.warn(
            "HF_HUB_ENABLE_HF_TRANSFER 는 이제 아무 동작도 하지 않습니다(FACTS 5). "
            "다운로드 가속이 필요하면 HF_XET_HIGH_PERFORMANCE=1 을 쓰십시오."
        )
    if os.environ.get("RUNPOD_POD_ID") and not relevant_env.get("HF_HOME"):
        rec.warn(
            "RunPod 파드인데 HF_HOME 이 설정되어 있지 않습니다. 컨테이너 기본 경로에 모델이 내려가면 "
            "파드를 멈출 때 사라집니다. /workspace 아래로 HF_HOME 과 HF_HUB_CACHE 를 지정하십시오(FACTS 5)."
        )
    if relevant_env.get("HF_DATASETS_CACHE") and not relevant_env.get("HF_HOME"):
        rec.warn(
            "HF_DATASETS_CACHE 만 설정하면 Arrow 캐시만 옮겨지고 내려받은 parquet 은 옮겨지지 않습니다(FACTS 5). "
            "HF_HOME 과 HF_HUB_CACHE 를 함께 설정하십시오."
        )

    return {
        "system": platform.system(),
        "kernel_release": platform.release(),
        "kernel_version": platform.version(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "hostname": rec.probe("os.hostname", socket.gethostname),
        "libc": rec.probe("os.libc", _libc),
        "os_release": os_release,
        "container": {
            "in_container": bool(hints),
            "hints": hints,
            "image_tag": image_tag,
            "image_digest": image_digest,
        },
        "runpod": runpod,
        "relevant_env": relevant_env,
    }


# ----------------------------------------------------------------------------
# 개별 탐지기 (python / packages)
# ----------------------------------------------------------------------------

def _capture_python(rec: _Recorder) -> dict[str, Any]:
    info = {
        "version": platform.python_version(),
        "version_full": " ".join(sys.version.split()),
        "implementation": platform.python_implementation(),
        "compiler": platform.python_compiler(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": getattr(sys, "base_prefix", sys.prefix),
        "in_virtualenv": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
    }
    if (_vtuple(info["version"]) or ())[:2] != (3, 12):
        rec.warn(
            f"Python {info['version']} 에서 실행되었습니다. FACTS 5 의 STACK A 는 Python 3.12 를 "
            "기준으로 검증되었습니다. 팀원 전원이 같은 마이너 버전을 쓰는지 확인하십시오."
        )
    return info


def _probe_package_version(dist_name: str) -> str:
    """importlib.metadata 로 배포 패키지 버전을 읽습니다(이름 정규화는 표준이 처리합니다)."""
    return _md.version(dist_name)


def _probe_pip_freeze() -> tuple[list[str], str]:
    """pip freeze 전체 목록. pip 가 없으면 importlib.metadata 로 동등한 목록을 만듭니다."""
    try:
        out = _run(
            [sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
            timeout=180.0,
        )
        lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("WARNING")]
        if lines:
            return lines, "pip freeze"
    except BaseException:  # noqa: BLE001 - uv 등 pip 가 없는 환경을 위한 대체 경로로 내려갑니다.
        pass
    seen: dict[str, str] = {}
    for dist in _md.distributions():
        try:
            name = dist.metadata["Name"]
        except BaseException:  # noqa: BLE001
            name = None
        if not name:
            continue
        seen[str(name)] = str(dist.version)
    lines = [f"{name}=={version}" for name, version in sorted(seen.items(), key=lambda kv: kv[0].lower())]
    if not lines:
        raise RuntimeError("pip freeze 와 importlib.metadata 모두에서 패키지 목록을 얻지 못했습니다")
    return lines, "importlib.metadata (pip 를 사용할 수 없어 대체)"


def _capture_packages(rec: _Recorder) -> dict[str, Any]:
    packages: dict[str, Any] = {}
    for name in KEY_PACKAGES:
        packages[name] = rec.probe(f"packages.{name}", lambda n=name: _probe_package_version(n))
    if packages.get("flash-attn") is None:
        # FACTS 5: flash-attn 은 PyPI 에 sdist 만 있어 30~60분 컴파일이 필요합니다. 없는 것이 정상입니다.
        rec.errors["packages.flash-attn"] = (
            "설치되어 있지 않습니다. FACTS 5 기준으로 이는 정상이며 의도된 상태입니다"
            "(flash-attn 은 sdist 전용이라 긴 컴파일이 필요하고, Qwen3VL 은 _supports_sdpa=True 이므로 "
            'attn_implementation="sdpa" 로 충분합니다).'
        )
    if packages.get("qwen-vl-utils") is None:
        rec.errors["packages.qwen-vl-utils"] = (
            "설치되어 있지 않습니다. FACTS 5 기준으로 이미지 전용 MMMU 베이스라인에는 필요하지 않은 선택 패키지입니다."
        )

    freeze = rec.probe("packages.pip_freeze", _probe_pip_freeze)
    if freeze is None:
        pip_freeze: list[str] = []
    else:
        pip_freeze, source = freeze
        rec.note("pip_freeze_source", f"{source}, 총 {len(pip_freeze)}개 패키지")
    packages["pip_freeze"] = pip_freeze

    _check_stack_coherence(packages, rec)
    return packages


def _check_stack_coherence(packages: dict[str, Any], rec: _Recorder) -> None:
    """FACTS 5 의 버전 제약을 실행 전에 검증합니다. 여기서 걸러야 3시간을 아낍니다."""
    tf = _vtuple(packages.get("transformers"))
    vl = _vtuple(packages.get("vllm"))
    hub = _vtuple(packages.get("huggingface-hub"))
    tok = _vtuple(packages.get("tokenizers"))

    if tf is None:
        rec.warn("transformers 가 설치되어 있지 않습니다. Qwen3-VL 에는 transformers>=4.57.0 이 필요합니다(FACTS 5).")
    elif tf < (4, 57, 0):
        rec.warn(
            f"transformers {packages.get('transformers')} 는 Qwen3-VL 을 지원하지 않습니다. "
            "최소 4.57.0 이 필요합니다(FACTS 5, PR #40795)."
        )
    if vl is None:
        rec.warn(
            "vllm 이 설치되어 있지 않습니다. transformers 백엔드로 돌리면 FACTS 2 에 따라 "
            "presence_penalty=1.5 를 적용할 수 없고, 900 샘플에 2~6시간이 걸립니다(FACTS 13)."
        )
    elif vl < (0, 11, 0):
        rec.warn(
            f"vllm {packages.get('vllm')} 에는 Qwen3VLForConditionalGeneration 이 등록되어 있지 않습니다. "
            "최소 0.11.0 이 필요합니다(FACTS 5)."
        )
    if tf is not None and vl is not None and tf[:2] == (4, 57) and vl >= (0, 29, 0):
        rec.warn(
            "transformers 4.57.x 와 vllm 0.29 이상은 공존할 수 없습니다(vllm 0.29 메타데이터가 "
            "transformers>=5.10.4 를 요구합니다, FACTS 5). 스택 조합을 다시 확인하십시오."
        )
    if tf is not None and tf[:2] == (4, 57):
        if hub is not None and hub >= (1, 0, 0):
            rec.warn(
                f"transformers 4.57.x 는 huggingface-hub<1.0 을 요구하는데 현재 {packages.get('huggingface-hub')} 입니다(FACTS 5). "
                "0.35.3 으로 고정하십시오."
            )
        if tok is not None and tok > (0, 23, 0):
            rec.warn(
                f"transformers 4.57.1 은 tokenizers<=0.23.0 을 요구하는데 현재 {packages.get('tokenizers')} 입니다(FACTS 5)."
            )
    if packages.get("flash-attn"):
        rec.warn(
            "flash-attn 이 설치되어 있습니다. FACTS 5 는 설치하지 말 것을 권고합니다"
            '(sdist 전용 빌드). attn_implementation="sdpa" 로 충분합니다.'
        )

    # 어떤 스택인지 한 줄로 못 박아 둡니다. 팀원 간 비교 시 가장 먼저 보는 값입니다.
    if tf is not None and vl is not None and tf[:2] == (4, 57) and vl[:2] == (0, 11):
        stack = "STACK A (FACTS 5 권장: vllm 0.11.0 + transformers 4.57.1, 공개 점수 67.4 발표 시점과 릴리스가 맞는 조합)"
    elif tf is not None and vl is not None and tf[0] >= 5 and vl >= (0, 29, 0):
        stack = (
            "STACK B (최신 vLLM 필요 시: vllm 0.29.0 + transformers 5.17.0). "
            "코드 차이: torch_dtype= 대신 dtype=, config.vocab_size 대신 config.text_config.vocab_size (FACTS 5)"
        )
    else:
        stack = (
            "혼합/미확인 — FACTS 5 의 STACK A 도 STACK B 도 아닙니다. requirements.lock.txt 와 "
            "실제 설치 상태가 일치하는지 확인하십시오."
        )
    rec.note("stack", stack)


# ----------------------------------------------------------------------------
# 개별 탐지기 (model / dataset 리비전) — FACTS 6, 가장 많이 빠뜨리는 재현성 항목
# ----------------------------------------------------------------------------

def _hub_cache_dir() -> Path:
    """HuggingFace 허브 캐시 루트를 찾습니다.

    환경 변수 -> huggingface_hub 상수 -> 기본 경로 순서입니다. 상수 이름이 버전마다 다르고
    (구버전은 HUGGINGFACE_HUB_CACHE) huggingface_hub 자체가 없을 수도 있으므로,
    라이브러리 없이도 경로를 구할 수 있게 만들어 둡니다.
    """
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    try:
        from huggingface_hub import constants  # noqa: PLC0415 - 지연 임포트(의도적)

        for attr in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            value = getattr(constants, attr, None)
            if value:
                return Path(str(value)).expanduser()
    except BaseException:  # noqa: BLE001 - 아래의 기본 경로로 내려갑니다.
        pass
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _repo_cache_folder(repo_id: str, repo_type: str) -> Path:
    prefix = "datasets--" if repo_type == "dataset" else "models--"
    return _hub_cache_dir() / (prefix + repo_id.replace("/", "--"))


def _resolve_from_cache_ref(repo_id: str, revision: str, repo_type: str) -> str:
    """로컬 허브 캐시의 refs/<revision> 파일에서 커밋 SHA 를 읽습니다(오프라인에서도 동작)."""
    ref = _repo_cache_folder(repo_id, repo_type) / "refs" / revision
    if not ref.is_file():
        raise FileNotFoundError(f"로컬 캐시에 refs/{revision} 가 없습니다: {ref}")
    sha = _read_text(ref, limit=200).strip()
    if not _SHA_RE.match(sha):
        raise RuntimeError(f"refs/{revision} 의 내용이 커밋 SHA 형식이 아닙니다: {sha!r}")
    return sha


def _resolve_from_hub_api(repo_id: str, revision: str, repo_type: str) -> str:
    """HuggingFace API 로 'main' 같은 가변 포인터를 커밋 SHA 로 해석합니다."""
    if os.environ.get("HF_HUB_OFFLINE", "").strip() not in ("", "0", "false", "False"):
        raise RuntimeError("HF_HUB_OFFLINE 이 설정되어 있어 허브 API 조회를 건너뜁니다")
    from huggingface_hub import HfApi  # noqa: PLC0415 - 지연 임포트(의도적)

    api = HfApi()
    fn = api.dataset_info if repo_type == "dataset" else api.model_info
    try:
        # timeout 인자는 huggingface_hub 버전에 따라 있/없을 수 있으므로 TypeError 로 분기합니다.
        info = fn(repo_id, revision=revision, timeout=15.0)
    except TypeError:
        info = fn(repo_id, revision=revision)
    sha = getattr(info, "sha", None)
    if not sha or not _SHA_RE.match(str(sha)):
        raise RuntimeError(f"허브 응답에 사용 가능한 커밋 SHA 가 없습니다: {sha!r}")
    return str(sha)


def _resolve_git_head(path: str | os.PathLike[str]) -> str:
    """로컬 디렉터리가 git clone 인 경우(예: 데이터셋을 직접 clone 한 경우) HEAD SHA 를 읽습니다."""
    sha = _run(["git", "rev-parse", "HEAD"], cwd=path, timeout=30.0).strip()
    if not _SHA_RE.match(sha):
        raise RuntimeError(f"git rev-parse HEAD 결과가 SHA 가 아닙니다: {sha!r}")
    return sha


def _snapshot_dir(repo_id: str, sha: str, repo_type: str) -> str:
    path = _repo_cache_folder(repo_id, repo_type) / "snapshots" / sha
    if not path.is_dir():
        raise FileNotFoundError(
            f"로컬 캐시에 스냅샷 디렉터리가 없습니다: {path} "
            "(env.json 은 모델 로드 전에 기록되므로 첫 실행에서는 정상입니다)"
        )
    return str(path)


def _resolve_revision(
    rec: _Recorder,
    kind: str,
    repo_id_or_path: str,
    requested: str | None,
    repo_type: str,
) -> tuple[str | None, str | None, str]:
    """(해석된 SHA, 로컬 경로, 해석 경로 설명) 을 돌려줍니다.

    FACTS 6: "main" 은 가변 브랜치 포인터입니다. MMMU/MMMU 의 데이터 파일은 67.4 가 공개된
    이후에도 2026-02-12 / 04-21 / 07-10 에 바뀌었으므로, 리비전 없는 저장소 이름은
    재현 가능한 식별자가 아닙니다. 그래서 여기서 반드시 40자 SHA 까지 확정합니다.
    """
    local = Path(str(repo_id_or_path)).expanduser()
    if local.exists():
        # 로컬 경로를 직접 준 경우: 허브 리비전 개념이 없으므로 git clone 인지만 확인합니다.
        local_path = str(local.resolve())
        sha = rec.probe(f"{kind}.revision(git)", lambda: _resolve_git_head(local))
        if sha:
            return sha, local_path, "로컬 디렉터리의 git HEAD"
        if requested and _SHA_RE.match(requested):
            return requested, local_path, "로컬 디렉터리 + 인자로 받은 SHA (검증 불가)"
        rec.fail(
            f"{kind}.revision",
            f"로컬 경로 {local_path} 는 git 저장소가 아니어서 리비전을 확정할 수 없습니다. "
            f"재현성을 위해 --{kind}-revision 에 원본 허브 커밋 SHA 를 직접 적어 두십시오.",
        )
        return None, local_path, "해석 실패(로컬 경로)"

    revision = requested or "main"
    if _SHA_RE.match(revision):
        # 이미 SHA 입니다. 그래도 스냅샷 경로는 찾아서 기록합니다.
        local_path = rec.probe(
            f"{kind}.local_path", lambda: _snapshot_dir(repo_id_or_path, revision, repo_type)
        )
        return revision, local_path, "인자로 받은 값이 이미 커밋 SHA"

    sha = rec.probe(
        f"{kind}.revision(cache)", lambda: _resolve_from_cache_ref(repo_id_or_path, revision, repo_type)
    )
    source = "로컬 허브 캐시의 refs/" + revision
    if sha is None:
        sha = rec.probe(
            f"{kind}.revision(api)", lambda: _resolve_from_hub_api(repo_id_or_path, revision, repo_type)
        )
        source = "HuggingFace API 조회"
    if sha is None:
        rec.fail(
            f"{kind}.revision",
            f"'{revision}' 을 커밋 SHA 로 해석하지 못했습니다(캐시·API 모두 실패). "
            "가변 포인터만 남으면 재현이 불가능하므로(FACTS 6) 네트워크를 확인하거나 SHA 를 직접 지정하십시오.",
        )
        rec.warn(
            f"{kind} 리비전을 SHA 로 확정하지 못했습니다. 이 상태의 결과는 재현 가능한 기록이 아닙니다(FACTS 6)."
        )
        return None, None, "해석 실패"
    local_path = rec.probe(f"{kind}.local_path", lambda: _snapshot_dir(repo_id_or_path, sha, repo_type))
    return sha, local_path, source


def _capture_model(rec: _Recorder, requested: dict[str, Any]) -> dict[str, Any]:
    repo_id = requested.get("repo_id") or DEFAULT_MODEL_REPO
    asked = requested.get("revision") or DEFAULT_MODEL_REVISION
    sha, local_path, source = _resolve_revision(rec, "model", repo_id, asked, "model")
    rec.note("model_revision_resolution", f"요청 '{asked}' -> 확정 '{sha}' (해석 경로: {source})")
    if sha and asked and _SHA_RE.match(asked) and sha != asked:
        rec.warn(f"모델 리비전이 요청({asked})과 확정({sha})이 다릅니다. 즉시 확인하십시오.")

    dtype = requested.get("dtype")
    attn = requested.get("attn_implementation")
    if dtype is None:
        rec.fail(
            "model.dtype",
            "런타임 선택값이므로 탐지 대상이 아닙니다. eval 스크립트가 "
            "capture(extra={'model': {'dtype': ...}}) 로 전달합니다. 단독 실행 시 null 입니다.",
        )
    if attn is None:
        rec.fail(
            "model.attn_implementation",
            "런타임 선택값이므로 탐지 대상이 아닙니다. eval 스크립트가 전달합니다"
            '(FACTS 5 기준 권장값은 "sdpa" 이며 flash-attn 은 설치하지 않습니다).',
        )
    # 키 구성은 INTERFACES 의 model 스키마와 정확히 일치합니다.
    return {
        "repo_id": repo_id,
        "revision": sha,
        "local_path": local_path,
        "dtype": dtype,
        "attn_implementation": attn,
    }


def _capture_dataset(rec: _Recorder, requested: dict[str, Any]) -> dict[str, Any]:
    repo = requested.get("repo_id_or_path") or DEFAULT_DATASET_REPO
    asked = requested.get("revision") or DEFAULT_DATASET_REVISION
    sha, _local, source = _resolve_revision(rec, "dataset", repo, asked, "dataset")
    rec.note("dataset_revision_resolution", f"요청 '{asked}' -> 확정 '{sha}' (해석 경로: {source})")

    split = requested.get("split") or DEFAULT_SPLIT
    n_samples = requested.get("n_samples")
    if n_samples is None:
        rec.fail(
            "dataset.n_samples",
            "실제 평가한 샘플 수는 --subjects/--limit 에 따라 달라지므로 탐지하지 않습니다. "
            "eval 스크립트가 capture(extra={'dataset': {'n_samples': N}}) 로 전달합니다"
            "(필터 없는 validation 전체는 900입니다).",
        )
    # 키 구성은 INTERFACES 의 dataset 스키마와 정확히 일치합니다.
    return {
        "repo_id_or_path": repo,
        "revision": sha,
        "split": split,
        "n_samples": n_samples,
    }


# ----------------------------------------------------------------------------
# 개별 탐지기 (git)
# ----------------------------------------------------------------------------

def _capture_git(rec: _Recorder) -> dict[str, Any]:
    def _git(*args: str) -> str:
        return _run(["git", *args], cwd=REPO_ROOT, timeout=30.0).strip()

    inside = rec.probe("git.repo", lambda: _git("rev-parse", "--is-inside-work-tree"))
    if inside != "true":
        if inside is None:
            rec.errors.setdefault("git.repo", "git 저장소 여부를 확인하지 못했습니다")
        else:
            rec.fail("git.repo", f"{REPO_ROOT} 는 git 작업 트리가 아닙니다 (git 응답: {inside!r})")
        rec.warn(
            f"{REPO_ROOT} 가 git 저장소가 아니어서 커밋을 기록할 수 없습니다. "
            "제출용 실행은 반드시 커밋된 상태에서 해야 합니다(FACTS 12)."
        )
        return {"commit": None, "branch": None, "dirty": None}

    commit = rec.probe("git.commit", lambda: _git("rev-parse", "HEAD"))
    branch = rec.probe("git.branch", lambda: _git("rev-parse", "--abbrev-ref", "HEAD"))

    def _dirty_info() -> tuple[bool, list[str]]:
        out = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT, timeout=60.0)
        files = [line for line in out.splitlines() if line.strip()]
        return bool(files), files

    info = rec.probe("git.dirty", _dirty_info)
    dirty: bool | None = None
    if info is not None:
        dirty, changed = info
        if dirty:
            shown = ", ".join(changed[:20])
            suffix = f" 외 {len(changed) - 20}개" if len(changed) > 20 else ""
            rec.note("git_dirty_files", f"{len(changed)}개 변경/미추적 항목: {shown}{suffix}")
            rec.warn(
                "작업 트리가 깨끗하지 않습니다(dirty=true). FACTS 12 에 따라 보고서에 쓸 실행은 "
                "커밋 후에 해야 합니다. 그렇지 않으면 같은 커밋으로 결과를 재현할 수 없습니다."
            )

    if branch == "HEAD":
        rec.note("git_branch_detail", "detached HEAD 상태입니다(브랜치 이름 없음).")

    remote = rec.probe("git.remote", lambda: _git("remote", "get-url", "origin"))
    if remote:
        # https://user:token@github.com/... 형태로 자격 증명이 들어가 있으면 지웁니다.
        rec.note("git_remote", _URL_CRED_RE.sub("//<자격증명 삭제>@", remote))

    # 키 구성은 INTERFACES 의 git 스키마와 정확히 일치합니다.
    return {"commit": commit, "branch": branch, "dirty": dirty}


# ----------------------------------------------------------------------------
# notes 고정 문구 (FACTS 인용)
# ----------------------------------------------------------------------------

NOTE_CUDA_VERSIONS = (
    "CUDA 버전 세 개는 서로 다른 것을 가리키므로 값이 일치하지 않는 것이 정상입니다(FACTS 9). "
    "① nvidia_smi_cuda = 설치된 드라이버가 지원하는 최대 CUDA 런타임 버전. "
    "② nvcc_version = 컨테이너에 설치된 로컬 CUDA 툴킷 버전이며, 보통 설치되어 있지 않고 "
    "미리 빌드된 PyTorch 휠과는 아무 관계가 없습니다(null 이어도 정상). "
    "③ torch_version_cuda = 실제로 중요한 값으로, 사용 중인 PyTorch 휠이 어떤 CUDA 로 빌드되었는지를 "
    "나타냅니다. 예컨대 nvidia-smi 가 13.0 인데 torch.version.cuda 가 12.9 인 상태는 '올바른' 상태이며 "
    "아무것도 고칠 필요가 없습니다. CUDA 12.x 는 드라이버 525 이상, 13.x 는 580 이상만 요구합니다. "
    "이 항목을 맞추려고 드라이버나 툴킷을 재설치하며 시간을 쓰지 마십시오."
)

NOTE_IMAGE_DIGEST = (
    "컨테이너 이미지 다이제스트는 컨테이너 내부에서 읽을 수 없습니다(FACTS 8). RepoDigests 는 Docker "
    "데몬 메타데이터에 있고 로컬 image ID 는 전혀 다른 해시입니다. 따라서 image_digest 는 구조적으로 "
    "null 이며, 정확히 남기려면 RunPod 템플릿에서 이미지 태그를 환경 변수로 주입한 뒤 레지스트리에 "
    "HEAD 요청을 보내 다이제스트를 확인해야 합니다."
)

NOTE_ARTIFACT_REVISION = (
    "model.revision 과 dataset.revision 은 'main' 같은 가변 포인터가 아니라 해석된 40자 커밋 SHA 여야 "
    "합니다(FACTS 6). MMMU/MMMU 의 데이터 파일은 공개 점수 67.4 가 발표된 이후에도 2026-02-12, "
    "2026-04-21, 2026-07-10 에 변경되었으므로 'MMMU/MMMU' 라는 이름만으로는 재현이 불가능합니다. "
    "vLLM 을 쓸 때는 tokenizer_revision 도 따로 고정해야 합니다(기본값 None 이면 main 을 따라갑니다)."
)

NOTE_RUNPOD_DRIVER = (
    "RunPod 의 머신은 호스트마다 NVIDIA 드라이버가 다릅니다(FACTS 8). 파드를 고를 때 "
    "UI 의 Filters > CUDA version(또는 GraphQL 의 allowedCudaVersions)으로 드라이버 CUDA 를 고정해 "
    "팀원 4명이 같은 드라이버를 받도록 하십시오. 드라이버가 다르면 커널 경로가 달라져 설명할 수 없는 "
    "정확도 차이가 생깁니다."
)

NOTE_DETERMINISM = (
    "temperature=0.7 / top_p=0.8 / top_k=20 은 확률적 샘플링이므로 실행은 비트 단위로 재현되지 않고 "
    "팀원 4명의 점수는 서로 다릅니다(FACTS 7). n=900, p=0.674 에서 한 문제는 0.111pp, 표준오차는 "
    "1.56pp, 독립 실행 두 번의 차이에 대한 95% 구간은 ±4.33pp 입니다. 즉 1~2pp 차이는 버그가 아니라 "
    "노이즈입니다. 원인을 확인하려면 예측을 diff 하십시오(샘플링 노이즈는 원문 차이가 많고 라벨 변화가 "
    "적으며, 파서/정답키 버그는 원문 차이가 적은데 점수 차이가 큽니다). 또한 타이밍 표를 위해 "
    "transformers.enable_full_determinism() 은 쓰지 마십시오(CUDA_LAUNCH_BLOCKING=1 때문에 "
    "경과 시간이 무의미해집니다)."
)

NOTE_FILE_PURPOSE = (
    "이 파일은 eval 스크립트가 모델을 적재하기 전에 자동으로 생성합니다(FACTS 12). 손으로 고치지 마십시오. "
    "팀원끼리 환경이 같은지 확인할 때는 `python -m src.capture_env --check <상대방의 env.json>` 을 "
    "실행해 한국어 비교 표를 보십시오."
)


# ----------------------------------------------------------------------------
# 공개 API
# ----------------------------------------------------------------------------

def _section(rec: _Recorder, path: str, fn: Callable[[], Any], skeleton: Any) -> Any:
    """섹션 조립 코드 자체가 터지더라도 캡처 전체를 중단시키지 않기 위한 마지막 방어선입니다."""
    try:
        return fn()
    except BaseException as exc:  # noqa: BLE001
        rec.errors[path] = _reason(exc) + " / 이 섹션 전체를 수집하지 못했습니다"
        return skeleton


def capture(extra: dict | None = None) -> dict:
    """현재 실험 환경 전체를 탐지해 env.json 스키마의 dict 로 돌려줍니다.

    extra 로 eval 스크립트가 아는 값(model.dtype, dataset.n_samples, run_config 등)을 덮어씁니다.
    extra 의 None 값은 이미 탐지한 값을 지우지 않습니다.
    """
    rec = _Recorder()
    extra = dict(extra or {})

    known_sections = {
        "hardware", "driver_cuda", "os", "python", "packages",
        "model", "dataset", "run_config", "git", "notes",
    }
    extra_model = dict(extra.get("model") or {})
    extra_dataset = dict(extra.get("dataset") or {})
    run_config = dict(extra.get("run_config") or {})
    leftovers = {k: v for k, v in extra.items() if k not in known_sections}
    if leftovers:
        # 최상위 키는 스키마에 고정되어 있으므로, 모르는 키는 run_config 안으로 넣어 보존합니다.
        run_config.update(leftovers)
        rec.warn(
            "extra 에 스키마 밖의 최상위 키가 있었습니다: "
            + ", ".join(sorted(leftovers))
            + " → run_config 안으로 옮겨 기록했습니다."
        )

    hw_skeleton = {
        "gpu_name": None, "gpu_count": None, "vram_total_mib": None,
        "cpu_model": None, "cpu_count": None, "ram_gib": None,
    }
    hardware, gpus = _section(rec, "hardware", lambda: _capture_hardware(rec), (hw_skeleton, []))
    driver_cuda = _section(
        rec,
        "driver_cuda",
        lambda: _capture_driver_cuda(rec, gpus),
        {"nvidia_smi_cuda": None, "torch_version_cuda": None, "nvcc_version": None, "driver_version": None},
    )
    os_info = _section(rec, "os", lambda: _capture_os(rec), {})
    python_info = _section(rec, "python", lambda: _capture_python(rec), {})
    packages = _section(rec, "packages", lambda: _capture_packages(rec), {"pip_freeze": []})
    model = _section(
        rec,
        "model",
        lambda: _capture_model(rec, extra_model),
        {"repo_id": extra_model.get("repo_id") or DEFAULT_MODEL_REPO, "revision": None,
         "local_path": None, "dtype": None, "attn_implementation": None},
    )
    dataset = _section(
        rec,
        "dataset",
        lambda: _capture_dataset(rec, extra_dataset),
        {"repo_id_or_path": extra_dataset.get("repo_id_or_path") or DEFAULT_DATASET_REPO,
         "revision": None, "split": extra_dataset.get("split") or DEFAULT_SPLIT, "n_samples": None},
    )
    git_info = _section(rec, "git", lambda: _capture_git(rec), {"commit": None, "branch": None, "dirty": None})

    if not run_config:
        rec.note(
            "run_config",
            "비어 있습니다. capture_env 를 단독 실행한 경우이며, eval 스크립트는 "
            "extra={'run_config': {...}} 로 실제 실행 인자(템플릿, 샘플링 값, 픽셀 예산 등)를 채워 넣습니다.",
        )

    # notes: 고정 설명문(FACTS 인용) -> 탐지 중 남긴 메모 -> 실패/경고. 순서를 유지합니다.
    notes: dict[str, Any] = {
        "file_purpose": NOTE_FILE_PURPOSE,
        "cuda_versions": NOTE_CUDA_VERSIONS,
        "container_image_digest": NOTE_IMAGE_DIGEST,
        "artifact_revision": NOTE_ARTIFACT_REVISION,
        "runpod_driver": NOTE_RUNPOD_DRIVER,
        "determinism": NOTE_DETERMINISM,
    }
    notes.update(rec.notes)
    extra_notes = extra.get("notes")
    if isinstance(extra_notes, dict):
        notes.update({str(k): v for k, v in extra_notes.items()})
    elif extra_notes:
        notes["extra"] = extra_notes
    notes["probe_errors"] = dict(sorted(rec.errors.items()))
    notes["probe_warnings"] = list(rec.warnings)

    env: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hardware": hardware,
        "driver_cuda": driver_cuda,
        "os": os_info,
        "python": python_info,
        "packages": packages,
        "model": model,
        "dataset": dataset,
        "run_config": run_config,
        "git": git_info,
        "notes": notes,
    }

    # extra 의 나머지 섹션(hardware/driver_cuda/os/python/packages/git)도 덮어쓸 수 있게 합니다.
    # 탐지값보다 호출자가 명시한 값을 우선하되, None 으로 지우지는 않습니다.
    for section in ("hardware", "driver_cuda", "os", "python", "packages", "git"):
        override = extra.get(section)
        if isinstance(override, dict) and override:
            env[section] = _deep_merge(env[section], override)
    return env


def render_markdown(env: dict) -> str:
    """보고서에 그대로 붙여 넣을 한국어 ENVIRONMENT.md 를 생성합니다.

    제목은 교수님이 요구한 절 제목 "실험 환경 및 설정" 을 그대로 사용합니다.
    """
    hw = env.get("hardware") or {}
    cuda = env.get("driver_cuda") or {}
    osi = env.get("os") or {}
    osr = osi.get("os_release") or {}
    cont = osi.get("container") or {}
    pod = osi.get("runpod") or {}
    py = env.get("python") or {}
    pkgs = env.get("packages") or {}
    model = env.get("model") or {}
    dataset = env.get("dataset") or {}
    run_config = env.get("run_config") or {}
    git = env.get("git") or {}
    notes = env.get("notes") or {}

    out: list[str] = []
    out.append("## 실험 환경 및 설정")
    out.append("")
    out.append(
        f"이 문서는 `src/capture_env.py` 가 평가 실행 시점에 자동으로 생성했습니다. "
        f"캡처 시각(UTC) **{_md_cell(env.get('captured_at_utc'))}**, 스키마 버전 "
        f"`{_md_cell(env.get('schema_version'))}`."
    )
    out.append("")
    out.append("### 1. 하드웨어")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값"],
            [
                ["GPU", hw.get("gpu_name")],
                ["GPU 개수", hw.get("gpu_count")],
                ["VRAM 합계 (MiB)", hw.get("vram_total_mib")],
                ["CPU", hw.get("cpu_model")],
                ["논리 CPU 수", hw.get("cpu_count")],
                ["시스템 RAM (GiB)", hw.get("ram_gib")],
            ],
        )
    )
    # 표 바로 뒤에 목록이 붙으면 렌더러가 표의 일부로 오해할 수 있으므로 빈 줄을 한 번만 넣습니다.
    bullets = [
        (label, notes.get(key))
        for key, label in (("gpu_detail", "GPU 상세"), ("cpu_detail", "CPU 상세"), ("memory_detail", "메모리 상세"))
        if notes.get(key)
    ]
    if bullets:
        out.append("")
        out.extend(f"- {label}: {_md_cell(value)}" for label, value in bullets)

    out.append("")
    out.append("### 2. CUDA 및 드라이버 (세 값은 서로 다른 대상입니다)")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값", "무엇을 뜻하는가"],
            [
                ["nvidia-smi 헤더 CUDA", cuda.get("nvidia_smi_cuda"), "드라이버가 지원하는 최대 CUDA 런타임 버전"],
                ["nvcc --version", cuda.get("nvcc_version"), "컨테이너의 로컬 CUDA 툴킷. 보통 없으며 휠과 무관합니다"],
                ["torch.version.cuda", cuda.get("torch_version_cuda"), "실제로 중요한 값. PyTorch 휠이 빌드된 CUDA"],
                ["NVIDIA 드라이버", cuda.get("driver_version"), "CUDA 12.x 는 525 이상, 13.x 는 580 이상 필요"],
            ],
        )
    )
    out.append("")
    out.append(f"> {_md_cell(notes.get('cuda_versions', NOTE_CUDA_VERSIONS))}")
    if notes.get("torch_detail"):
        out.append("")
        out.append(f"- torch 상세: {_md_cell(notes['torch_detail'])}")

    out.append("")
    out.append("### 3. 운영체제 및 컨테이너")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값"],
            [
                ["OS", osr.get("pretty_name") or osi.get("system")],
                ["OS ID / 버전", f"{osr.get('id')} / {osr.get('version_id')}"],
                ["커널 릴리스", osi.get("kernel_release")],
                ["커널 버전", osi.get("kernel_version")],
                ["아키텍처", osi.get("machine")],
                ["libc", osi.get("libc")],
                ["호스트명", osi.get("hostname")],
                ["컨테이너 내부 여부", cont.get("in_container")],
                ["컨테이너 근거", cont.get("hints")],
                ["이미지 태그", cont.get("image_tag")],
                ["이미지 다이제스트", cont.get("image_digest")],
            ],
        )
    )
    out.append("")
    out.append(f"> {_md_cell(notes.get('container_image_digest', NOTE_IMAGE_DIGEST))}")
    if any(pod.values()):
        out.append("")
        out.append("**RunPod 파드 정보** (공개 저장소에 커밋되므로 공인 IP·포트·API 키는 수집하지 않습니다)")
        out.append("")
        out.extend(
            _md_table(
                ["항목", "값"],
                [
                    ["Pod ID", pod.get("pod_id")],
                    ["Pod 호스트명", pod.get("pod_hostname")],
                    ["데이터센터", pod.get("datacenter_id")],
                    ["GPU 개수(환경 변수)", pod.get("gpu_count")],
                    ["CPU 개수(환경 변수)", pod.get("cpu_count")],
                    ["메모리 GB(환경 변수)", pod.get("mem_gb")],
                    ["네트워크 볼륨 ID", pod.get("volume_id")],
                    ["네트워크 볼륨 경로", pod.get("volume_path")],
                ],
            )
        )
    if osi.get("relevant_env"):
        out.append("")
        out.append("**결과에 영향을 주는 환경 변수**")
        out.append("")
        out.extend(_md_table(["이름", "값"], [[k, v] for k, v in sorted(osi["relevant_env"].items())]))

    out.append("")
    out.append("### 4. Python")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값"],
            [
                ["버전", py.get("version")],
                ["구현", py.get("implementation")],
                ["전체 버전 문자열", py.get("version_full")],
                ["실행 파일", py.get("executable")],
                ["prefix", py.get("prefix")],
                ["가상환경 여부", py.get("in_virtualenv")],
                ["컴파일러", py.get("compiler")],
            ],
        )
    )

    out.append("")
    out.append("### 5. 핵심 패키지 버전")
    out.append("")
    out.extend(_md_table(["패키지", "버전"], [[name, pkgs.get(name)] for name in KEY_PACKAGES]))
    pkg_bullets = [
        (label, notes.get(key))
        for key, label in (("stack", "스택 판정"), ("pip_freeze_source", "전체 목록 출처"))
        if notes.get(key)
    ]
    if pkg_bullets:
        out.append("")
        out.extend(f"- {label}: {_md_cell(value)}" for label, value in pkg_bullets)
    freeze = pkgs.get("pip_freeze") or []
    if freeze:
        out.append("")
        out.append(f"<details><summary>설치된 전체 패키지 목록 ({len(freeze)}개)</summary>")
        out.append("")
        out.append("```text")
        out.extend(str(line) for line in freeze)
        out.append("```")
        out.append("")
        out.append("</details>")

    out.append("")
    out.append("### 6. 모델 및 데이터셋 (리비전 고정)")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값"],
            [
                ["모델 repo_id", model.get("repo_id")],
                ["모델 리비전 (커밋 SHA)", model.get("revision")],
                ["모델 로컬 경로", model.get("local_path")],
                ["dtype", model.get("dtype")],
                ["attn_implementation", model.get("attn_implementation")],
                ["데이터셋", dataset.get("repo_id_or_path")],
                ["데이터셋 리비전 (커밋 SHA)", dataset.get("revision")],
                ["split", dataset.get("split")],
                ["샘플 수", dataset.get("n_samples")],
            ],
        )
    )
    out.append("")
    out.append(f"> {_md_cell(notes.get('artifact_revision', NOTE_ARTIFACT_REVISION))}")
    for key, label in (("model_revision_resolution", "모델 리비전 해석"), ("dataset_revision_resolution", "데이터셋 리비전 해석")):
        if notes.get(key):
            out.append("")
            out.append(f"- {label}: {_md_cell(notes[key])}")

    out.append("")
    out.append("### 7. 실행 설정 (run_config)")
    out.append("")
    if run_config:
        out.extend(_md_table(["설정", "값"], [[k, run_config[k]] for k in sorted(run_config)]))
    else:
        out.append("기록된 실행 설정이 없습니다(capture_env 를 단독 실행한 경우입니다).")

    out.append("")
    out.append("### 8. Git 상태")
    out.append("")
    out.extend(
        _md_table(
            ["항목", "값"],
            [
                ["커밋", git.get("commit")],
                ["브랜치", git.get("branch")],
                ["변경 사항 있음(dirty)", git.get("dirty")],
            ],
        )
    )
    git_bullets = [
        (label, notes.get(key))
        for key, label in (
            ("git_remote", "원격 저장소"),
            ("git_dirty_files", "변경된 항목"),
            ("git_branch_detail", "브랜치 비고"),
        )
        if notes.get(key)
    ]
    if git_bullets:
        out.append("")
        out.extend(f"- {label}: {_md_cell(value)}" for label, value in git_bullets)

    out.append("")
    out.append("### 9. 팀 비교 시 알아야 할 점")
    out.append("")
    out.append(f"> {_md_cell(notes.get('determinism', NOTE_DETERMINISM))}")
    out.append("")
    out.append(f"> {_md_cell(notes.get('runpod_driver', NOTE_RUNPOD_DRIVER))}")
    out.append("")
    out.append(
        "팀원끼리 스택이 같은지 확인하려면 서로의 `env.json` 을 주고받아 다음을 실행하십시오: "
        "`python -m src.capture_env --check <상대방_env.json>`"
    )

    warnings = notes.get("probe_warnings") or []
    out.append("")
    out.append("### 10. 경고")
    out.append("")
    if warnings:
        out.extend(f"- {_md_cell(w)}" for w in warnings)
    else:
        out.append("경고 없음. 스택 점검 항목에서 걸린 문제가 없습니다.")

    errors = notes.get("probe_errors") or {}
    out.append("")
    out.append("### 11. 수집하지 못한 항목과 이유")
    out.append("")
    if errors:
        out.append("값이 null 인 항목은 모두 아래에 이유가 남습니다. (nvcc 처럼 없는 것이 정상인 항목도 포함됩니다.)")
        out.append("")
        out.extend(_md_table(["항목", "이유"], [[k, v] for k, v in sorted(errors.items())]))
    else:
        out.append("모든 항목을 정상적으로 수집했습니다.")

    other_notes = {
        k: v
        for k, v in notes.items()
        if k
        not in {
            "probe_errors", "probe_warnings", "gpu_detail", "cpu_detail", "memory_detail",
            "torch_detail", "cuda_versions", "container_image_digest", "artifact_revision",
            "runpod_driver", "determinism", "file_purpose", "stack", "pip_freeze_source",
            "model_revision_resolution", "dataset_revision_resolution", "git_remote",
            "git_dirty_files", "git_branch_detail",
        }
    }
    if other_notes:
        out.append("")
        out.append("### 12. 기타 메모")
        out.append("")
        out.extend(_md_table(["항목", "내용"], [[k, v] for k, v in other_notes.items()]))

    out.append("")
    return "\n".join(out)


def _dump_json(env: dict) -> str:
    # default=str: 직렬화 불가능한 값이 extra 로 들어와도 캡처 파일이 깨지지 않게 합니다.
    return json.dumps(env, ensure_ascii=False, indent=2, default=str)


def _write_files(outdir: str | os.PathLike[str], env: dict) -> tuple[Path, Path]:
    """env.json 과 ENVIRONMENT.md 를 씁니다(write_env 와 CLI 가 같은 경로를 쓰도록 공유)."""
    target = Path(outdir)
    json_path = target / "env.json"
    md_path = target / "ENVIRONMENT.md"
    _atomic_write(json_path, _dump_json(env) + "\n")
    _atomic_write(md_path, render_markdown(env))
    return json_path, md_path


def write_env(outdir: str | os.PathLike[str], extra: dict | None = None) -> dict:
    """env.json 과 ENVIRONMENT.md 를 outdir 에 쓰고 캡처한 dict 를 돌려줍니다."""
    env = capture(extra)
    _write_files(outdir, env)
    return env


# ----------------------------------------------------------------------------
# Markdown 렌더링 보조
# ----------------------------------------------------------------------------

def _md_cell(value: Any) -> str:
    """Markdown 표 한 칸으로 안전하게 변환합니다(파이프 이스케이프, 줄바꿈 제거)."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return "<br>".join(_md_cell(v) for v in value)
    if isinstance(value, dict):
        if not value:
            return "—"
        return "<br>".join(f"`{k}` = {_md_cell(v)}" for k, v in value.items())
    text = " ".join(str(value).split())
    return text.replace("|", "\\|") if text else "—"


def _md_table(headers: list[str], rows: Iterable[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in row) + " |")
    return lines


# ----------------------------------------------------------------------------
# --check : 팀원 환경 비교
# ----------------------------------------------------------------------------

#: (경로, 한국어 라벨, 심각도). critical = 이 값이 다르면 점수를 직접 비교할 수 없습니다.
CHECK_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("hardware.gpu_name", "GPU", "critical"),
    ("hardware.gpu_count", "GPU 개수", "critical"),
    ("hardware.vram_total_mib", "VRAM 합계(MiB)", "warn"),
    ("hardware.cpu_model", "CPU", "warn"),
    ("hardware.cpu_count", "논리 CPU 수", "warn"),
    ("hardware.ram_gib", "시스템 RAM(GiB)", "warn"),
    ("driver_cuda.nvidia_smi_cuda", "nvidia-smi CUDA", "critical"),
    ("driver_cuda.driver_version", "NVIDIA 드라이버", "critical"),
    ("driver_cuda.torch_version_cuda", "torch.version.cuda", "critical"),
    ("driver_cuda.nvcc_version", "nvcc", "warn"),
    ("os.os_release.pretty_name", "OS", "warn"),
    ("os.kernel_release", "커널", "warn"),
    ("os.container.image_tag", "컨테이너 이미지 태그", "warn"),
    ("python.version", "Python", "critical"),
    ("packages.torch", "torch", "critical"),
    ("packages.torchvision", "torchvision", "critical"),
    ("packages.transformers", "transformers", "critical"),
    ("packages.tokenizers", "tokenizers", "critical"),
    ("packages.huggingface-hub", "huggingface-hub", "critical"),
    ("packages.vllm", "vllm", "critical"),
    ("packages.datasets", "datasets", "critical"),
    ("packages.pillow", "pillow", "critical"),
    ("packages.accelerate", "accelerate", "warn"),
    ("packages.safetensors", "safetensors", "warn"),
    ("packages.numpy", "numpy", "warn"),
    ("packages.qwen-vl-utils", "qwen-vl-utils", "warn"),
    ("packages.flash-attn", "flash-attn", "warn"),
    ("model.repo_id", "모델", "critical"),
    ("model.revision", "모델 리비전", "critical"),
    ("model.dtype", "dtype", "critical"),
    ("model.attn_implementation", "attn_implementation", "critical"),
    ("dataset.repo_id_or_path", "데이터셋", "critical"),
    ("dataset.revision", "데이터셋 리비전", "critical"),
    ("dataset.split", "split", "critical"),
    ("dataset.n_samples", "샘플 수", "critical"),
    ("git.commit", "Git 커밋", "warn"),
    ("git.branch", "Git 브랜치", "warn"),
    ("git.dirty", "Git dirty", "warn"),
)

#: 측정 단위 반올림 때문에 미세하게 달라질 수 있는 값의 허용 오차입니다.
_CHECK_TOLERANCE: dict[str, float] = {"hardware.ram_gib": 1.0, "hardware.vram_total_mib": 64.0}


def _values_equal(field: str, left: Any, right: Any) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    tol = _CHECK_TOLERANCE.get(field)
    if tol is not None:
        try:
            return abs(float(left) - float(right)) <= tol
        except (TypeError, ValueError):
            pass
    if left == right:
        return True
    return str(left).strip() == str(right).strip()


def _norm_pkg_name(name: str) -> str:
    # PEP 503 정규화: 대소문자 무시, -_. 을 모두 하이픈으로 통일합니다.
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _freeze_map(lines: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in lines or []:
        line = str(raw).strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-e ") or line.startswith("--"):
            result[_norm_pkg_name(line)] = "(편집 가능 설치)"
            continue
        if "==" in line:
            name, _, version = line.partition("==")
            result[_norm_pkg_name(name)] = version.strip()
        elif " @ " in line:
            name, _, url = line.partition(" @ ")
            result[_norm_pkg_name(name)] = url.strip()
        else:
            result[_norm_pkg_name(line)] = "(버전 정보 없음)"
    return result


def compare_env(reference: dict, live: dict) -> dict:
    """기준 env.json 과 현재 환경을 비교해 구조화된 결과를 돌려줍니다."""
    rows: list[dict[str, Any]] = []
    n_critical = 0
    n_warn = 0
    for field, label, severity in CHECK_FIELDS:
        ref_present, ref_value = _flat_get(reference, field)
        cur_present, cur_value = _flat_get(live, field)
        if not ref_present and not cur_present:
            verdict = "양쪽 모두 없음"
            match = True
        elif not ref_present or not cur_present:
            verdict = "한쪽에만 존재"
            match = False
        elif _values_equal(field, ref_value, cur_value):
            verdict = "일치"
            match = True
        else:
            verdict = "불일치"
            match = False
        if not match:
            if severity == "critical":
                n_critical += 1
            else:
                n_warn += 1
        rows.append(
            {
                "field": field,
                "label": label,
                "severity": severity,
                "reference": ref_value if ref_present else None,
                "current": cur_value if cur_present else None,
                "verdict": verdict,
                "match": match,
            }
        )

    ref_freeze = _freeze_map((reference.get("packages") or {}).get("pip_freeze"))
    cur_freeze = _freeze_map((live.get("packages") or {}).get("pip_freeze"))
    changed = sorted(n for n in set(ref_freeze) & set(cur_freeze) if ref_freeze[n] != cur_freeze[n])
    return {
        "rows": rows,
        "n_critical": n_critical,
        "n_warn": n_warn,
        "freeze": {
            "only_reference": sorted(set(ref_freeze) - set(cur_freeze)),
            "only_current": sorted(set(cur_freeze) - set(ref_freeze)),
            "version_differs": [(n, ref_freeze[n], cur_freeze[n]) for n in changed],
            "reference_total": len(ref_freeze),
            "current_total": len(cur_freeze),
        },
    }


def render_check_markdown(reference: dict, live: dict, ref_path: str | None = None) -> tuple[str, int]:
    """한국어 비교 표를 Markdown 으로 돌려줍니다. -> (본문, 종료 코드)"""
    result = compare_env(reference, live)
    rows = result["rows"]
    out: list[str] = []
    out.append("## 실험 환경 일치 점검 (팀원 간 비교)")
    out.append("")
    out.append(
        f"- 기준 파일: `{ref_path or '(메모리)'}` — 캡처 시각(UTC) "
        f"{_md_cell(reference.get('captured_at_utc'))}, 스키마 `{_md_cell(reference.get('schema_version'))}`"
    )
    out.append(
        f"- 현재 환경: 캡처 시각(UTC) {_md_cell(live.get('captured_at_utc'))}, "
        f"스키마 `{_md_cell(live.get('schema_version'))}`"
    )
    if reference.get("schema_version") != live.get("schema_version"):
        out.append(
            "- 주의: 두 파일의 스키마 버전이 다릅니다. capture_env.py 버전을 맞춘 뒤 다시 비교하십시오."
        )
    out.append("")
    out.append("### 항목별 비교")
    out.append("")
    table_rows = []
    for row in rows:
        if row["match"]:
            mark = "일치"
        elif row["severity"] == "critical":
            mark = "**불일치(치명적)**"
        else:
            mark = "불일치(주의)"
        if row["verdict"] == "양쪽 모두 없음":
            mark = "양쪽 모두 없음"
        elif row["verdict"] == "한쪽에만 존재":
            mark = "**한쪽에만 존재**" if row["severity"] == "critical" else "한쪽에만 존재"
        table_rows.append([row["label"], row["reference"], row["current"], mark])
    out.extend(_md_table(["항목", "기준", "현재", "판정"], table_rows))

    freeze = result["freeze"]
    out.append("")
    out.append(
        f"### 전체 패키지 목록 차이 (기준 {freeze['reference_total']}개 / 현재 {freeze['current_total']}개)"
    )
    out.append("")
    if not (freeze["only_reference"] or freeze["only_current"] or freeze["version_differs"]):
        out.append("설치된 패키지 목록이 완전히 동일합니다.")
    else:
        limit = 60
        diff_rows: list[list[Any]] = []
        for name, ref_v, cur_v in freeze["version_differs"]:
            diff_rows.append([name, ref_v, cur_v])
        for name in freeze["only_reference"]:
            diff_rows.append([name, "설치됨", "없음"])
        for name in freeze["only_current"]:
            diff_rows.append([name, "없음", "설치됨"])
        out.extend(_md_table(["패키지", "기준", "현재"], diff_rows[:limit]))
        if len(diff_rows) > limit:
            out.append("")
            out.append(f"- 표에 표시하지 않은 차이 {len(diff_rows) - limit}건이 더 있습니다.")

    out.append("")
    out.append("### 결론")
    out.append("")
    if result["n_critical"] == 0 and result["n_warn"] == 0:
        out.append("핵심 항목이 모두 일치합니다. 두 실행의 점수를 직접 비교할 수 있습니다.")
        out.append("")
        out.append(
            "단, temperature=0.7 샘플링 때문에 점수는 여전히 다릅니다. n=900 에서 독립 실행 두 번의 "
            "차이에 대한 95% 구간은 ±4.33pp 이므로 1~2pp 차이는 노이즈입니다(FACTS 7)."
        )
    elif result["n_critical"] == 0:
        out.append(
            f"치명적 불일치는 없고 주의 항목 {result['n_warn']}건만 다릅니다. "
            "점수 비교는 가능하지만 보고서에 차이를 한 줄 적어 두십시오."
        )
    else:
        out.append(
            f"치명적 불일치 {result['n_critical']}건, 주의 {result['n_warn']}건. "
            "스택이 다르므로 두 실행의 점수를 같은 조건의 결과로 묶어서는 안 됩니다. "
            "requirements.lock.txt 로 환경을 맞춘 뒤 다시 실행하십시오."
        )
    out.append("")
    return "\n".join(out), (1 if result["n_critical"] else 0)


def _load_reference(path: str) -> tuple[dict, str]:
    """env.json 경로 또는 env.json 을 담고 있는 실행 디렉터리를 모두 받아 줍니다."""
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        candidate = candidate / "env.json"
    if not candidate.is_file():
        raise FileNotFoundError(f"기준 env.json 을 찾을 수 없습니다: {candidate}")
    data = json.loads(_read_text(candidate, limit=50_000_000))
    if not isinstance(data, dict):
        raise ValueError(f"{candidate} 의 최상위 구조가 JSON 객체가 아닙니다")
    return data, str(candidate)


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

_EPILOG = """사용 예
  python -m src.capture_env --out outputs/env
      현재 환경을 탐지해 outputs/env/env.json 과 outputs/env/ENVIRONMENT.md 를 만듭니다.

  python -m src.capture_env
      ENVIRONMENT.md 내용을 화면에 출력합니다(파일은 만들지 않습니다).

  python -m src.capture_env --print json
      env.json 내용을 표준출력으로 내보냅니다.

  python -m src.capture_env --check outputs/run_kim/env.json
      팀원의 env.json 과 현재 환경을 비교한 한국어 표를 출력합니다.
      치명적 불일치가 있으면 종료 코드 1 을 돌려줍니다(CI 나 스크립트에서 사용 가능).

종료 코드: 0 정상 / 1 치명적 환경 불일치 / 2 기준 파일을 읽을 수 없음
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.capture_env",
        description="실험 환경(하드웨어·드라이버·패키지·리비전)을 env.json 과 ENVIRONMENT.md 로 기록합니다.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--out", metavar="DIR", default=None, help="env.json 과 ENVIRONMENT.md 를 쓸 디렉터리")
    parser.add_argument(
        "--check",
        metavar="PATH",
        default=None,
        help="기준 env.json(또는 그것을 담은 실행 디렉터리)과 현재 환경을 비교합니다",
    )
    parser.add_argument(
        "--print",
        dest="print_format",
        choices=("md", "json", "none"),
        default=None,
        help="표준출력 형식. 기본값은 --out/--check 가 없으면 md, 있으면 none 입니다",
    )
    parser.add_argument("--extra", metavar="FILE", default=None, help="env 에 병합할 추가 정보 JSON 파일")
    parser.add_argument("--model", default=None, help="모델 repo_id 또는 로컬 경로")
    parser.add_argument("--model-revision", default=None, help="모델 리비전(커밋 SHA 권장)")
    parser.add_argument("--dataset", default=None, help="데이터셋 repo_id 또는 로컬 경로")
    parser.add_argument("--dataset-revision", default=None, help="데이터셋 리비전(커밋 SHA 권장)")
    parser.add_argument("--split", default=None, help="데이터셋 split (기본 validation)")
    args = parser.parse_args(argv)

    extra: dict[str, Any] = {}
    if args.extra:
        try:
            loaded = json.loads(_read_text(args.extra, limit=50_000_000))
        except BaseException as exc:  # noqa: BLE001
            print(f"[오류] --extra 파일을 읽지 못했습니다: {_reason(exc)}", file=sys.stderr)
            return 2
        if not isinstance(loaded, dict):
            print("[오류] --extra 파일의 최상위 구조는 JSON 객체여야 합니다.", file=sys.stderr)
            return 2
        extra = loaded

    model_extra = {k: v for k, v in (("repo_id", args.model), ("revision", args.model_revision)) if v}
    if model_extra:
        extra["model"] = _deep_merge(dict(extra.get("model") or {}), model_extra)
    dataset_extra = {
        k: v
        for k, v in (
            ("repo_id_or_path", args.dataset),
            ("revision", args.dataset_revision),
            ("split", args.split),
        )
        if v
    }
    if dataset_extra:
        extra["dataset"] = _deep_merge(dict(extra.get("dataset") or {}), dataset_extra)

    reference: dict | None = None
    ref_path: str | None = None
    if args.check:
        # 기준 파일을 먼저 읽습니다. 읽을 수 없으면 시간이 걸리는 탐지를 시작하지 않습니다.
        try:
            reference, ref_path = _load_reference(args.check)
        except BaseException as exc:  # noqa: BLE001
            print(f"[오류] {_reason(exc)}", file=sys.stderr)
            return 2

    print("환경을 탐지하는 중입니다... (torch 임포트와 pip 목록 수집에 수 초가 걸립니다)", file=sys.stderr)
    env = capture(extra)

    notes = env.get("notes") or {}
    for warning in notes.get("probe_warnings") or []:
        print(f"[경고] {warning}", file=sys.stderr)
    n_errors = len(notes.get("probe_errors") or {})
    if n_errors:
        print(
            f"[안내] 수집하지 못한 항목 {n_errors}건이 있습니다. 각 항목의 이유는 "
            "env.json 의 notes.probe_errors 와 ENVIRONMENT.md 11절에 기록되어 있습니다.",
            file=sys.stderr,
        )

    if args.out:
        json_path, md_path = _write_files(args.out, env)
        print(f"[완료] {json_path}", file=sys.stderr)
        print(f"[완료] {md_path}", file=sys.stderr)

    exit_code = 0
    if reference is not None:
        text, exit_code = render_check_markdown(reference, env, ref_path)
        print(text)

    fmt = args.print_format
    if fmt is None:
        fmt = "none" if (args.out or reference is not None) else "md"
    if fmt == "md":
        print(render_markdown(env))
    elif fmt == "json":
        print(_dump_json(env))
    return exit_code


__all__ = [
    "SCHEMA_VERSION",
    "KEY_PACKAGES",
    "CHECK_FIELDS",
    "capture",
    "render_markdown",
    "write_env",
    "compare_env",
    "render_check_markdown",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())

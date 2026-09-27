# RunPod 실행 가이드 — Qwen3-VL-4B-Instruct × MMMU validation 베이스라인

이 문서는 **GPU를 한 번도 빌려본 적이 없는 팀원**이 혼자서 처음부터 끝까지 따라갈 수 있도록 쓴 절차서입니다.
목표 지점은 하나입니다.

> "MMMU validation 900문항 베이스라인 평가가 끝났고, `outputs/` 결과와 실험 환경 기록(`env.json`)이 내 GitHub 계정으로 커밋되어 있다."

읽는 순서대로 그대로 따라 하시면 됩니다. 중간을 건너뛰어도 되는 절은 제목에 `(선택)`을 붙여 두었습니다.

> **먼저 읽어야 하는 한 줄**: 이 과제의 최우선 산출물은 점수만이 아니라 **실험 환경의 완전한 기록**입니다.
> 하드웨어, 드라이버, 패키지 버전이 4명 사이에서 일치하지 않으면 점수를 비교할 수 없고, 비교할 수 없으면 보고서의
> "실험 환경 및 설정" 항목이 성립하지 않습니다. 그래서 이 가이드는 **0절의 팀 합의표를 채우기 전에는 아무도 파드를
> 켜지 말라**고 요구합니다.

---

## 목차

0. [시작 전 팀 합의표 (가장 중요)](#0-시작-전-팀-합의표-가장-중요)
1. [계정 생성과 크레딧 충전](#1-계정-생성과-크레딧-충전)
2. [GPU 선택 — 실제 가격표와 권장안](#2-gpu-선택--실제-가격표와-권장안)
3. [Community냐 Secure냐 — 네트워크 볼륨이 갈림길입니다](#3-community냐-secure냐--네트워크-볼륨이-갈림길입니다)
4. [CUDA 버전 필터 — 4명이 먼저 드라이버를 통일해야 하는 이유](#4-cuda-버전-필터--4명이-먼저-드라이버를-통일해야-하는-이유)
5. [템플릿과 디스크 크기, /workspace가 남기는 것과 지우는 것](#5-템플릿과-디스크-크기-workspace가-남기는-것과-지우는-것)
6. [파드 생성 화면 — 항목별 입력값](#6-파드-생성-화면--항목별-입력값)
7. [접속: SSH · JupyterLab · VS Code Remote](#7-접속-ssh--jupyterlab--vs-code-remote)
8. [접속 직후 5분 점검](#8-접속-직후-5분-점검)
9. [환경 구축 — venv 두 개와 Stack A 설치](#9-환경-구축--venv-두-개와-stack-a-설치)
10. [모델과 데이터셋 내려받기 (리비전 고정)](#10-모델과-데이터셋-내려받기-리비전-고정)
11. [킷 실행 — dry-run → 스모크 → 본 런](#11-킷-실행--dry-run--스모크--본-런)
12. [결과를 파드 밖으로 꺼내기](#12-결과를-파드-밖으로-꺼내기)
13. [종료 — 과금 함정 3개](#13-종료--과금-함정-3개)
14. [비용 계산 예시 (1인 1회 / 4인 팀)](#14-비용-계산-예시-1인-1회--4인-팀)
15. [트러블슈팅](#15-트러블슈팅)
16. [최종 체크리스트](#16-최종-체크리스트)

---

## 0. 시작 전 팀 합의표 (가장 중요)

아래 표를 **4명이 같은 값으로 채우고 나서** 파드를 켭니다. 한 칸이라도 다르면 점수 차이의 원인을 끝까지 설명할 수
없게 됩니다. 표를 팀 채팅에 붙여 놓고, 각자 자기 열을 채운 뒤 서로 대조하십시오.

| 합의 항목 | 합의값 (예시) | 왜 일치해야 하는가 |
|---|---|---|
| 클라우드 종류 | Community | 가격·IP 안정성·네트워크 볼륨 가용성이 달라집니다 (3절) |
| GPU 모델 | RTX 4090 24GB | 커널 경로와 속도가 다릅니다. 재현성은 **동일 하드웨어에서만** 성립합니다 |
| CUDA 버전 필터 | 12.8 (또는 팀이 고른 단일 값) | 머신마다 NVIDIA 드라이버가 다릅니다 (4절) |
| 의존성 스택 | Stack A (torch 2.8.0 / vllm 0.11.0 / transformers 4.57.1) | 9절. 버전 조합이 다르면 생성 결과 자체가 달라집니다 |
| 모델 리비전 | `ebb281ec70b05090aa6165b016eac8ec08e71b17` | `main`은 움직이는 포인터입니다 |
| 데이터셋 리비전 | `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` | MMMU 데이터 파일은 2026-02-12 / 04-21 / 07-10에 변경되었습니다 |
| 프롬프트 템플릿 | `anchored` | 템플릿에 따라 MMMU 점수가 몇 점씩 움직입니다 |
| 시드 | `--seed 3407` | vLLM의 `LLM(seed=)`와 `SamplingParams.seed`를 모두 고정합니다 |
| 컨테이너 이미지 태그 | 파드 생성 화면에 표시된 문자열 그대로 | 컨테이너 **안에서는** 이미지 다이제스트를 읽을 수 없습니다 (5절) |

> **주의**: `temperature=0.7 / top_p=0.8 / top_k=20`은 교수님이 지정한 **확률적(stochastic)** 설정입니다.
> 위 표를 완벽히 맞춰도 팀원 간 점수는 조금씩 다릅니다. n=900에서 표본 1개는 0.111pp, 표준오차는 1.56pp이고,
> 독립된 두 런의 **차이**에 대한 95% 구간은 ±4.33pp입니다. **1~2pp 차이는 버그가 아니라 잡음입니다.**
> 팀 비교 규칙은 `docs/TEAM_PROTOCOL.md`를 따르십시오.

---

## 1. 계정 생성과 크레딧 충전

1. <https://www.runpod.io> 에 접속해 회원가입합니다. GitHub/Google 계정 연동이 가능합니다.
2. **각자 자기 계정을 만드십시오.** 팀 리더 계정 하나를 4명이 돌려 쓰는 방식은 권장하지 않습니다.
   과제 요구사항이 "각 팀원이 **자기 계정으로** 커밋"이고, 동시에 파드를 켜면 서로의 실행을 덮어쓸 위험이 있습니다.
3. RunPod은 **선불 크레딧** 방식입니다. Billing 화면에서 결제 수단을 등록하고 크레딧을 충전합니다.
   - 최소 충전 금액·지원 결제 수단은 화면에 표시되는 값을 그대로 따르십시오. 해외 결제가 가능한 카드가 필요합니다.
   - 14절의 계산대로 **1인 1회 실행은 $1 미만**입니다. 재시도 여유를 포함해 $5 정도면 충분합니다.
   - 자동 충전(auto top-up)은 **끄는 쪽을 권장**합니다. 파드를 끄는 것을 잊었을 때 조용히 돈이 빠져나가는 경로입니다.
4. **크레딧이 바닥나면 파드가 중지·종료될 수 있습니다.** 결과를 회수하기 전에 크레딧이 0에 가까워지는 상황을 만들지
   마십시오. 본 런을 시작할 때 잔액이 최소 $2 이상인지 확인하십시오.
5. Settings → **SSH Public Keys**에 본인 노트북의 공개키를 등록합니다 (7절에서 키를 만드는 방법을 설명합니다).
   **파드를 만들기 전에 등록**해 두면 생성 시점에 키가 주입되어 바로 접속할 수 있습니다.

> **Serverless가 아니라 Pods를 쓰십시오.** 이 과제는 한 번에 900문항을 돌리는 배치 평가이고, 모델 로드 시간과
> 경과 시간을 직접 측정해야 합니다. Serverless는 요청 단위 과금·콜드스타트 구조라 시간 측정표가 의미를 잃습니다.

---

## 2. GPU 선택 — 실제 가격표와 권장안

아래는 **2026-09-12에 RunPod에서 직접 읽은 On-Demand 시간당 단가**입니다.

> ⚠️ **가격은 근사값이며 계속 변합니다.** RunPod의 단가는 수요·재고에 따라 수시로 조정되고 리전별로도 다릅니다.
> 보고서에는 "2026-09-12 기준 약 $0.34/hr"처럼 **읽은 날짜와 함께 근사값으로** 적고, 결제 직전에 콘솔의 실제
> 숫자를 다시 확인하십시오.

| GPU | VRAM | Community ($/hr, 근사) | Secure ($/hr, 근사) |
|---|---|---|---|
| RTX A5000 | 24GB | 0.16 | 0.27 |
| **RTX 4090** | **24GB** | **0.34** | **0.74** |
| A40 | 48GB | 0.35 | 0.49 |
| L40S | 48GB | 0.79 | 1.09 |
| A100 PCIe | 80GB | 1.19 | 1.59 |
| A100 SXM | 80GB | 1.39 | 1.59 |
| H100 PCIe | 80GB | 1.99 | 2.89 |
| H100 SXM | 80GB | 2.69 | 3.49 |
| H100 NVL | 94GB | 2.59 | 3.19 |

### 권장: RTX 4090 24GB (Community)

- 교수님의 권장 설정 자체가 "Recommended settings for an RTX 4090"입니다. 기준 하드웨어를 그대로 쓰는 것이
  보고서 해석에 가장 유리합니다.
- 4B 모델에서 토큰당 비용이 가장 싼 선택입니다. Ada 세대, 메모리 대역폭 1008 GB/s.
- **24GB에 들어맞는지 계산** (이 숫자는 보고서의 "실험 환경" 절에 그대로 쓸 수 있습니다):
  - 가중치 BF16 **8.28 GiB** (파라미터 4,437,815,808개, 파일 크기 8.89 GB / 2 샤드)
  - KV 캐시 = 2(K+V) × 36층 × 8 KV heads × 128 head_dim × 2 bytes = **147,456 B/token = 144 KiB/token**
    → `max_model_len=9048`인 시퀀스 하나가 **1.24 GiB**
  - `gpu_memory_utilization=0.90`일 때: 21.6 − 8.28 − 약 2.5(ViT·활성값·CUDA 그래프) ≈ **10.8 GiB가 KV 캐시**
    → 9048토큰 시퀀스 약 **8개 동시 처리**
  - 따라서 기본값은 **0.90**, vLLM 프로파일링 단계에서 OOM이 나면 **0.85**로 내립니다 (15절 T1).

### A40 48GB를 고르는 경우

- Community 단가는 4090과 거의 같지만(0.35 vs 0.34) **Ampere 세대**입니다. 대역폭 약 696 GB/s, FP8 미지원이라
  **달러당 속도가 대략 절반**입니다. VRAM 여유(48GB)가 꼭 필요할 때만 고르십시오.
- 단, **Secure Cloud에서는 A40이 더 쌉니다** (A40 $0.49 < 4090 $0.74). Secure로 가기로 결정했다면 A40이 합리적입니다.
  대신 본 런 시간을 4090 기준의 **1.5~2배로 추정**해 두십시오(13절 wall-clock은 4090 기준 수치입니다).

### 쓰지 마십시오

- A100/H100 계열은 4B 모델 900문항에 **과분합니다.** 비용이 3~8배인데 벽시계 시간은 그만큼 줄지 않습니다.
- A5000($0.16)은 싸 보이지만 4090보다 느리고, 교수님의 기준 하드웨어가 아닙니다. 비용 절감액($0.18/hr × 1.5h ≈ $0.27)이
  보고서의 해석 난이도 증가를 정당화하지 못합니다.

---

## 3. Community냐 Secure냐 — 네트워크 볼륨이 갈림길입니다

이 결정은 취향 문제가 아니고, **하나의 기술적 제약**에서 출발합니다.

> RunPod 공식 문서(docs.runpod.io/storage/network-volumes)는 이렇게 적고 있습니다:
> "Network volumes are only available for Pods in the Secure Cloud."
> 즉 **네트워크 볼륨은 Secure Cloud 전용**입니다.

따라서 **$0.34/hr Community 4090 + 팀 공유 네트워크 볼륨** 조합은 **존재하지 않습니다.** 둘 중 하나를 골라야 합니다.

| | Community Cloud | Secure Cloud |
|---|---|---|
| 4090 단가(근사) | $0.34/hr | $0.74/hr |
| 인프라 | 제3자 호스트의 P2P 방식 | T3/T4 데이터센터 |
| 업타임 SLA | 없음 | 99.5% |
| 공인 IP | 재시작·마이그레이션 시 **바뀔 수 있음** | 안정적 |
| 네트워크 볼륨 | **사용 불가** | 사용 가능 ($0.07/GB/월, 1TB 미만) |
| 신규 호스트 | RunPod이 신규 Community 호스트를 더 받지 않습니다 | — |

### 4인 팀 관점에서의 정직한 트레이드오프

**네트워크 볼륨이 주는 것**은 하나입니다: 모델 가중치 8.89 GB와 validation parquet 341 MB를 **한 번만 내려받아
4명이 공유**하는 것. 그 대가는 (a) 시간당 단가가 4090에서 $0.34 → $0.74로 2배 이상, (b) 볼륨 자체가
**아무도 실행하지 않는 동안에도 계속 과금**된다는 점입니다.

그런데 이 과제에서 공유로 절약되는 시간은 **1인당 10분 내외**입니다. RunPod 데이터센터 네트워크에서 8.89 GB는 빨리
받아집니다. 반대로 Secure로 옮기면 1인당 본 런 비용이 $0.17 → $0.37로 오르고, 볼륨 100GB는 월 $7이 추가됩니다.
**10분을 아끼려고 과제 전체 비용을 3~5배로 올리는 셈입니다.**

### 권장

> **Community Cloud + RTX 4090 + 네트워크 볼륨 없이, 각자 독립 파드.**
> 4명이 각자 모델을 내려받는 중복을 그대로 받아들입니다. 대신 **0절 합의표**로 동일성을 보장하고,
> Community의 약점(SLA 없음, IP 변경)은 **tmux 사용 + 잦은 커밋**으로 방어합니다 (11절, 15절 T5).

**다음 경우에만 Secure + 네트워크 볼륨으로 가십시오.**

- 같은 캐시를 며칠에 걸쳐 반복해서 쓸 계획이 있다 (예: 과제 2의 파인튜닝까지 이어서 할 환경을 미리 만든다).
- 파드가 중간에 내려가면 곤란한 장시간 작업을 한다 (이번 베이스라인은 15~45분이므로 해당되지 않습니다).
- 고정 IP가 필요한 방식으로 원격 개발 환경을 구성해 두었다.

이 경우 GPU는 **A40 48GB Secure ($0.49/hr)**가 4090 Secure($0.74/hr)보다 싸므로 A40을 고르고,
볼륨은 팀 리더 계정에 하나 만들어 같은 리전에 파드를 띄우게 하십시오. 그리고 **제출이 끝난 날 볼륨을 삭제**하십시오.

---

## 4. CUDA 버전 필터 — 4명이 먼저 드라이버를 통일해야 하는 이유

RunPod의 머신은 호스트마다 **NVIDIA 드라이버 버전이 다릅니다.** 같은 "RTX 4090"을 빌려도 어떤 호스트는 드라이버
CUDA 12.8, 어떤 호스트는 13.0입니다. 드라이버 CUDA가 다르면 커널 선택 경로가 달라질 수 있고, 그 결과
**설명할 수 없는 정확도 차이**가 생깁니다. 보고서에서 "왜 저는 66.2, 너는 68.0인가"를 설명해야 하는 상황에서
드라이버가 다르다는 사실은 원인 후보를 지저분하게 늘립니다.

**방법:**

- 파드 생성 화면 왼쪽/상단의 **Filters → CUDA Version**에서 값을 고릅니다.
- GraphQL/API로 만든다면 `allowedCudaVersions` 필드를 사용합니다.
- **팀이 고른 단일 값**(예: `12.8`)만 체크하고, 4명 모두 같은 값으로 필터링합니다. 합의값은 0절 표에 적어 둡니다.
- 해당 값의 재고가 없으면 **혼자 바꾸지 말고 팀 채팅에 알리고 다시 합의**하십시오. 이것이 이 절의 핵심입니다.

> 참고: Stack A는 cu128 휠을 쓰므로 **기능상으로는** CUDA 12.x 드라이버(버전 525 이상)면 동작합니다.
> 그래도 값을 하나로 묶는 이유는 "동작 가능"이 아니라 **"4명의 숫자를 비교 가능하게"** 만들기 위함입니다.
> 세 가지 CUDA 버전이 왜 헷갈리는지는 15절 T3에 정리해 두었습니다.

---

## 5. 템플릿과 디스크 크기, /workspace가 남기는 것과 지우는 것

### 템플릿

- RunPod 공식 **PyTorch 템플릿**(Ubuntu + CUDA + PyTorch + JupyterLab이 들어 있는 이미지) 중,
  4절에서 합의한 CUDA 버전과 맞는 것을 고릅니다.
- **템플릿에 미리 깔린 torch/vllm 버전에 의존하지 마십시오.** 템플릿 태그는 수시로 바뀌고 팀원 간에 달라질 수 있습니다.
  우리는 9절에서 **새 venv를 만들어 Stack A를 직접 핀으로 설치**합니다. 그러면 템플릿이 무엇이든 결과 환경은 같습니다.
  템플릿은 "CUDA 드라이버가 보이는 우분투 컨테이너" 역할만 합니다.
- **이미지 태그는 손으로 기록하십시오.** 컨테이너 **내부에서는 자기 이미지의 다이제스트를 읽을 수 없습니다**
  (RepoDigests는 Docker 데몬 메타데이터에 있고, 로컬 이미지 ID는 다른 해시입니다). 그래서:
  1. 파드 생성 화면의 이미지 이름:태그를 **그대로 복사**해 팀 채팅/메모에 남기고,
  2. 파드 생성 시 **Environment Variables**에 `MMDL_CONTAINER_IMAGE=<이미지:태그>`를 추가해 두면
     파드 안에서 `printenv MMDL_CONTAINER_IMAGE`로 언제든 확인할 수 있습니다,
  3. 보고서의 실험 환경 표에 그 값을 옮겨 적고 **4명의 태그가 같은지 대조**하십시오.

### 디스크 크기

파드 생성 화면에는 디스크가 **두 개** 있습니다. 역할이 전혀 다릅니다.

| | Container Disk | Volume Disk (`/workspace`) |
|---|---|---|
| 마운트 위치 | `/`, `/root`, `/usr` 등 전부 | `/workspace` |
| 파드 stop → start | **초기화됩니다** | 유지됩니다 |
| 파드 terminate | 삭제 | **삭제** (네트워크 볼륨만 예외) |
| 권장 크기 | **20 GB** | **60 GB** |

**60 GB 산정 근거** — 전부 `/workspace`에 두기 때문입니다.

| 항목 | 크기 |
|---|---|
| 모델 가중치 (`Qwen3-VL-4B-Instruct`, 2 샤드) | 8.89 GB |
| MMMU validation parquet (`*/validation-*.parquet`) | 약 341 MB (325 MiB) |
| `datasets`가 만드는 Arrow 캐시 | 원본과 비슷한 규모를 한 번 더 |
| venv 2개 (torch + vllm 휠 포함) | 수 GB |
| pip 캐시 | 수 GB |
| `outputs/` (predictions.jsonl 최악 7.4 MB 수준) | 무시 가능 |
| 여유 | 나머지 |

> 디스크를 아끼려면 **MMMU 전체(3.66 GB, 92개 parquet)를 받지 말고 validation만** 받으십시오.
> 10절의 `--include "*/validation-*.parquet"`가 그 역할을 합니다. 약 3 GB와 상당한 파드 시간을 아낍니다.

### `/workspace`가 남기는 것과 남기지 않는 것

**남습니다 (stop → start 사이)**

- `/workspace` 아래의 모든 것: 저장소 클론, venv, HF 캐시, 데이터셋, `outputs/`.

**남지 않습니다**

- `/root/.cache/huggingface` ← **HF 기본 캐시 위치입니다. 반드시 `HF_HOME`을 옮기십시오** (15절 T4)
- `/root/.cache/pip` ← `PIP_CACHE_DIR`로 옮기십시오
- `/root/.ssh`, `/root/.gitconfig`, `/root/.vscode-server`, `apt-get install`로 깐 것들
- **terminate하면 `/workspace`도 사라집니다.** "중지"와 "종료"는 전혀 다릅니다 (13절)

> 그래서 작업 규칙은 단 하나입니다: **모든 것을 `/workspace` 아래에서 하십시오.**
> 저장소는 `/workspace/MMDL`, venv는 `/workspace/venv`, HF 캐시는 `/workspace/hf`, 데이터는 `/workspace/data`.

---

## 6. 파드 생성 화면 — 항목별 입력값

Console → **Pods → Deploy** 순서로 들어가 아래대로 채웁니다.

| 항목 | 입력값 | 비고 |
|---|---|---|
| Cloud Type | **Community** | 3절 권장안. Secure로 합의했다면 Secure |
| Filters → CUDA Version | **팀 합의값 하나만** | 4절. 여기서 타협하지 마십시오 |
| GPU | **RTX 4090 × 1** | GPU 개수는 **1개**. 4B 모델에 다중 GPU는 불필요하고 비교만 복잡해집니다 |
| Template | 합의한 PyTorch 템플릿 | 태그를 복사해 기록 (5절) |
| Container Disk | 20 GB | |
| Volume Disk | 60 GB | `/workspace`에 마운트되는지 확인 |
| Volume Mount Path | `/workspace` | 기본값이 다르면 `/workspace`로 맞추십시오 |
| Expose TCP Ports | **22 포함** | 빠지면 Direct TCP SSH와 `scp`가 막힙니다 (7절) |
| Expose HTTP Ports | 8888 (JupyterLab을 쓸 경우) | 생성 후에는 추가가 번거로우니 미리 넣습니다 |
| Environment Variables | `MMDL_CONTAINER_IMAGE=<이미지:태그>` | 5절 |
| Pod Name | `mmdl-<본인이름>-4090` | 팀원 파드와 구분 |

Deploy를 누르면 상태가 `provisioning` → `running`으로 바뀝니다. 여기서부터 **초 단위 과금이 시작됩니다.**

---

## 7. 접속: SSH · JupyterLab · VS Code Remote

### 7.1 SSH 키 만들기 (노트북에서, 파드를 만들기 전에 한 번만)

```bash
# macOS / Linux / Windows(WSL 또는 Git Bash)
ssh-keygen -t ed25519 -C "runpod-mmdl-$(whoami)"
# 저장 경로 기본값(~/.ssh/id_ed25519) 그대로 Enter, 패스프레이즈는 원하면 설정

cat ~/.ssh/id_ed25519.pub     # 이 한 줄 전체를 복사
```

복사한 **공개키(.pub)** 를 RunPod **Settings → SSH Public Keys**에 붙여 넣고 저장합니다.
비밀키(`id_ed25519`, 확장자 없는 쪽)는 **절대 어디에도 붙여 넣지 마십시오.**

### 7.2 SSH 접속

파드의 **Connect** 버튼을 누르면 두 가지 명령이 보입니다. **표시된 문자열을 그대로 복사해 쓰십시오**
(IP·포트는 파드마다 다르고, Community에서는 재시작 시 바뀔 수 있습니다).

```bash
# (A) Direct TCP — 권장. scp/rsync가 됩니다. Expose TCP Ports에 22가 있어야 나타납니다.
ssh root@<PUBLIC_IP> -p <PORT> -i ~/.ssh/id_ed25519

# (B) SSH over RunPod proxy — 터미널만 필요할 때
ssh <POD_ID>-<HASH>@ssh.runpod.io -i ~/.ssh/id_ed25519
```

(B) 프록시 방식은 파일 전송(scp/sftp)을 지원하지 않는 경우가 많습니다. **결과를 꺼내올 생각을 하면 (A)를 쓰십시오.**

접속이 끊기는 것을 줄이려면 노트북의 `~/.ssh/config`에 다음을 추가합니다.

```sshconfig
Host runpod
    HostName <PUBLIC_IP>          # Community는 재시작 시 바뀔 수 있으니 그때마다 수정
    User root
    Port <PORT>
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 30        # 30초마다 keepalive — 유휴 끊김 방지
    ServerAliveCountMax 6
    # 파드는 매번 새로 만들어지므로 호스트키가 계속 바뀝니다.
    # 일반 서버에는 절대 쓰지 말아야 할 설정이지만, 일회용 GPU 파드에 한해 허용합니다.
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
```

이제 `ssh runpod` 한 줄로 접속됩니다.

### 7.3 JupyterLab

- 파드 **Connect → HTTP Service [Port 8888]** 버튼을 누르면 브라우저가 열립니다.
- 토큰/비밀번호를 묻는다면 파드의 **Logs** 탭에 출력된 token을 찾거나, 템플릿이 `JUPYTER_PASSWORD` 환경변수를
  쓰는 경우 파드의 Environment Variables에서 확인하십시오.
- 템플릿에 Jupyter가 없거나 죽어 있으면 직접 띄웁니다(8888이 Expose HTTP Ports에 있어야 합니다).

```bash
source /workspace/venv/bin/activate
pip install jupyterlab          # eval venv를 더럽히고 싶지 않다면 별도 venv에 설치하십시오
jupyter lab --ip=0.0.0.0 --port=8888 --allow-root --no-browser
```

> **본 런은 Jupyter 노트북에서 돌리지 마십시오.** 브라우저 탭이 닫히거나 커널이 끊기면 40분짜리 런이 날아갑니다.
> Jupyter는 결과 JSON을 열어 보거나 이미지를 확인할 때만 쓰고, 실행은 11절의 tmux로 하십시오.

### 7.4 VS Code Remote-SSH

1. VS Code에 **Remote - SSH** 확장을 설치합니다.
2. 7.2의 `~/.ssh/config` 항목(`Host runpod`)이 그대로 쓰입니다.
3. `F1` → **Remote-SSH: Connect to Host** → `runpod` 선택.
4. 붙은 뒤 `File → Open Folder` → `/workspace/MMDL`.

주의할 점 두 가지입니다.

- VS Code 서버는 `/root/.vscode-server`에 설치됩니다. 즉 **컨테이너 디스크**이므로 파드를 재생성하면 다시 받습니다.
  정상 동작입니다.
- Community에서 IP가 바뀌면 `~/.ssh/config`의 `HostName`을 수정하고 VS Code 창을 다시 연결해야 합니다.
- **VS Code의 내장 터미널도 SSH 세션입니다.** 창을 닫으면 거기서 돌던 프로세스가 죽습니다. 반드시 tmux 안에서 실행하십시오.

---

## 8. 접속 직후 5분 점검

환경을 깔기 **전에** 아래를 돌려, 기대한 머신을 받았는지 확인합니다. 여기서 틀렸으면 파드를 버리고 다시 만드는 편이
싸게 끝납니다(몇 센트입니다).

```bash
# GPU와 드라이버
nvidia-smi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

# 디스크 — /workspace가 60GB로 잡혀 있는지
df -h / /workspace

# CPU / RAM (보고서 실험 환경 표에 들어갑니다)
lscpu | sed -n '1,20p'
free -g

# 파이썬 버전 — Stack A는 Python 3.12입니다
python3 --version

# 5절에서 넣어 둔 이미지 태그
printenv MMDL_CONTAINER_IMAGE
```

확인 사항:

- `nvidia-smi`의 GPU 이름이 **합의한 GPU**인가? (`NVIDIA GeForce RTX 4090`)
- `Driver Version`과 헤더의 `CUDA Version`이 **팀 합의값과 맞는가?** (→ 다르면 15절 T3을 읽고 팀에 공유)
- `/workspace`가 별도 파일시스템으로 마운트되어 있고 용량이 맞는가?
- `python3 --version`이 3.12인가? 3.12가 아니라면:

```bash
# Ubuntu 24.04 계열에서는 3.12가 기본입니다. 없으면:
apt-get update && apt-get install -y python3.12 python3.12-venv
python3.12 --version
```

---

## 9. 환경 구축 — venv 두 개와 Stack A 설치

### 9.1 왜 venv를 두 개 만드는가 (중요)

Stack A는 `transformers==4.57.1`을 쓰고, 이 버전은 **`huggingface-hub<1.0`을 요구**합니다. 그래서 eval venv에는
`huggingface-hub==0.35.3`을 핀으로 박습니다. 그런데 `hf` CLI와 `hf cache verify` 명령은 **huggingface_hub v1에서
도입**된 것이므로 0.35.3에는 없습니다(0.35.3에서는 `huggingface-cli`가 CLI 이름입니다).

→ 그래서 **다운로드·검증용 도구 venv를 따로 하나** 만듭니다. 한 venv에서 둘을 동시에 만족시키려다
`pip install -U`를 치는 순간 Stack A가 깨집니다.

| venv | 경로 | 용도 | 핵심 핀 |
|---|---|---|---|
| eval venv | `/workspace/venv` | 평가 실행 | Stack A 전체 |
| tools venv | `/workspace/venv-tools` | `hf download` / `hf cache verify` | `huggingface_hub==1.31.0` |

### 9.2 환경변수 — **python을 실행하기 전에** export

HuggingFace 환경변수는 **import 시점에 읽힙니다.** python이 이미 떠 있는 상태에서 export해도 소용없습니다.
아래 블록을 `/workspace/env.sh`로 만들어 두고, **새 쉘을 열 때마다 `source` 하십시오.**

```bash
cat > /workspace/env.sh <<'EOF'
# --- 캐시를 전부 /workspace(볼륨 디스크)로 옮깁니다 -------------------------
# HF_DATASETS_CACHE만 설정하면 Arrow 캐시만 옮겨지고 "내려받은 parquet"은 그대로
# /root/.cache에 쌓입니다. 그래서 HF_HOME과 HF_HUB_CACHE를 함께 지정합니다.
export HF_HOME=/workspace/hf
export HF_HUB_CACHE=/workspace/hf/hub
export HF_DATASETS_CACHE=/workspace/hf/datasets
export PIP_CACHE_DIR=/workspace/pipcache

# hf-xet 고속 전송. HF_HUB_ENABLE_HF_TRANSFER는 이제 아무 동작도 하지 않으므로 쓰지 않습니다.
export HF_XET_HIGH_PERFORMANCE=1

# vLLM 재현성: 오프라인(LLM 클래스) 경로에서 멀티프로세싱을 끕니다.
export VLLM_ENABLE_V1_MULTIPROCESSING=0

# 토크나이저 병렬 경고 억제(로그 가독성용, 결과에는 영향 없음)
export TOKENIZERS_PARALLELISM=false
EOF

mkdir -p /workspace/hf /workspace/pipcache /workspace/data
source /workspace/env.sh
printenv | grep -E '^HF_|^VLLM_|^PIP_CACHE'   # 제대로 들어갔는지 눈으로 확인
```

### 9.3 저장소 클론

```bash
cd /workspace
git clone https://github.com/<TEAM_LEADER_GITHUB_ID>/MMDL.git
cd /workspace/MMDL
git log --oneline -3          # 팀원과 같은 커밋에서 출발하는지 확인
```

### 9.4 eval venv + Stack A 설치

**설치 순서가 중요합니다**: torch를 **cu128 인덱스에서 먼저**, 나머지 다음, **vLLM을 마지막에**.
그리고 설치가 끝난 뒤에는 **절대 `pip install -U`를 치지 마십시오.**

```bash
source /workspace/env.sh
python3.12 -m venv /workspace/venv
source /workspace/venv/bin/activate
python -m pip install -U pip wheel setuptools      # pip 자체 업그레이드는 무해합니다

# (1) torch 3종 — vllm 0.11.0이 정확히 이 버전을 요구합니다
pip install --index-url https://download.pytorch.org/whl/cu128 \
    torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0

# (2) 나머지 런타임
pip install \
    transformers==4.57.1 \
    tokenizers==0.22.2 \
    huggingface-hub==0.35.3 \
    accelerate==1.11.0 \
    safetensors==0.6.2 \
    datasets==4.0.0 \
    pillow==11.3.0

# (3) vLLM 마지막
pip install vllm==0.11.0
```

**설치 직후 반드시 검증하십시오.** vLLM이 의존성을 끌어오면서 `transformers`를 올려 버리는 경우가 있습니다.

```bash
pip list | grep -Ei '^(torch|torchvision|torchaudio|vllm|transformers|tokenizers|huggingface-hub|accelerate|safetensors|datasets|pillow) '
python - <<'EOF'
import torch, transformers, vllm
print("torch       ", torch.__version__)
print("torch.cuda  ", torch.version.cuda)      # 휠이 빌드된 CUDA. nvidia-smi 값과 달라도 정상입니다
print("transformers", transformers.__version__)
print("vllm        ", vllm.__version__)
print("GPU         ", torch.cuda.get_device_name(0))
EOF
```

기대값: `torch 2.8.0+cu128`, `transformers 4.57.1`, `vllm 0.11.0`.
`transformers`가 다른 값이면 되돌립니다.

```bash
pip install --no-deps --force-reinstall transformers==4.57.1 tokenizers==0.22.2 huggingface-hub==0.35.3
```

### 9.5 절대 설치하지 말 것 — `flash-attn`

`flash-attn`은 PyPI에 **소스 배포(sdist)만** 있고 휠이 없습니다. `pip install flash-attn`을 치면
**30~60분을 컴파일에 태우고**, 그 시간만큼 파드 요금을 냅니다. Qwen3-VL은 `_supports_sdpa = True`이므로
`attn_implementation="sdpa"`가 그대로 대체품입니다. 평가 스크립트는 sdpa를 씁니다.

### 9.6 tools venv

```bash
deactivate 2>/dev/null
python3.12 -m venv /workspace/venv-tools
source /workspace/venv-tools/bin/activate
pip install -U pip
pip install "huggingface_hub[cli]==1.31.0"
hf --version          # 0.35.3에는 없는 명령입니다. 여기서만 씁니다.
deactivate
```

### 9.7 (선택) 동봉 스크립트

저장소의 `scripts/setup_pod.sh`와 `scripts/fetch_data.sh`는 9절과 10절을 묶어 실행하는 래퍼입니다.
**쓰기 전에 `cat`으로 내용을 한 번 읽어 보십시오.** 스크립트와 이 문서가 다르면 저장소의 스크립트(실제로 실행되는 쪽)가
정답입니다.

```bash
cat /workspace/MMDL/scripts/setup_pod.sh
bash /workspace/MMDL/scripts/setup_pod.sh
```

---

## 10. 모델과 데이터셋 내려받기 (리비전 고정)

`main`은 **움직이는 브랜치 포인터**입니다. MMMU/MMMU의 데이터 파일은 2026-02-12, 2026-04-21, 2026-07-10에
실제로 바뀌었습니다. 즉 `"MMMU/MMMU"`라는 문자열만으로는 **재현 가능한 식별자가 아닙니다.** 항상 커밋 SHA를 박습니다.

```bash
source /workspace/env.sh
source /workspace/venv-tools/bin/activate

MODEL_REV=ebb281ec70b05090aa6165b016eac8ec08e71b17
DATA_REV=98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68

# (1) 모델 — HF 캐시(/workspace/hf/hub)에 받습니다. 약 8.89 GB / 2 샤드
hf download Qwen/Qwen3-VL-4B-Instruct --revision "$MODEL_REV"

# (2) MMMU validation만 — 전체 3.66 GB 대신 약 341 MB
hf download MMMU/MMMU \
    --repo-type dataset \
    --revision "$DATA_REV" \
    --include "*/validation-*.parquet" \
    --local-dir /workspace/data/MMMU

# (3) 체크섬 검증 (hf cache verify는 huggingface_hub >= 1.1.0 필요 → tools venv에서만 가능)
hf cache verify MMMU/MMMU \
    --repo-type dataset \
    --revision "$DATA_REV" \
    --local-dir /workspace/data/MMMU \
    --fail-on-missing-files
echo "verify exit code = $?"      # 0이 아니면 다시 받으십시오

deactivate
```

받은 구조를 눈으로 확인합니다. MMMU는 **설정(config)이 과목별로 30개**이고 `"all"` 설정이 없습니다.
그래서 디렉터리도 과목별로 생깁니다.

```bash
ls /workspace/data/MMMU | head -40
ls /workspace/data/MMMU | wc -l            # 30개 과목 디렉터리
du -sh /workspace/data/MMMU                # 약 325 MiB
find /workspace/data/MMMU -name 'validation-*.parquet' | wc -l
```

기대값: validation 900행 = 30과목 × 30문항. 카테고리는 6개이고 구성은
120 / 150 / 150 / 150 / 120 / 210입니다.

---

## 11. 킷 실행 — dry-run → 스모크 → 본 런

### 11.0 반드시 tmux 안에서

SSH 세션이 끊기면 그 세션의 자식 프로세스가 전부 죽습니다. **40분짜리 본 런을 맨 쉘에서 돌리면 안 됩니다.**

```bash
tmux new -s mmmu          # 세션 생성 (이미 있으면: tmux attach -t mmmu)
# ── 이 안에서 아래 모든 명령을 실행합니다 ──
source /workspace/env.sh
source /workspace/venv/bin/activate
cd /workspace/MMDL
```

- 분리(detach): `Ctrl+b` 를 누르고 손을 뗀 뒤 `d`
- 재접속: `ssh runpod` → `tmux attach -t mmmu`
- 세션 목록: `tmux ls`

tmux가 없으면 `apt-get update && apt-get install -y tmux`로 설치합니다.
tmux를 쓸 수 없다면 `nohup` 방식(15절 T5)을 쓰십시오.

### 11.1 환경 기록부터 (이번 주 최우선 산출물)

모델을 올리기 전에 환경 기록이 제대로 나오는지 확인합니다. `env.json`은 **스크립트가 직접 생성**해야 하며,
나중에 손으로 고쳐 쓰는 것이 아닙니다.

```bash
python -m src.capture_env --out outputs/_envcheck
cat outputs/_envcheck/env.json | python -m json.tool | head -60
cat outputs/_envcheck/ENVIRONMENT.md
```

확인할 것:

- `hardware.gpu_name` = `NVIDIA GeForce RTX 4090`, `vram_total_mib` ≈ 24564
- `driver_cuda`의 네 값(`nvidia_smi_cuda`, `torch_version_cuda`, `nvcc_version`, `driver_version`)이 모두 채워졌는지
  — `nvcc_version`은 보통 `null`입니다. **정상입니다** (15절 T3)
- `packages`에 `torch 2.8.0+cu128`, `vllm 0.11.0`, `transformers 4.57.1`, 그리고 `pip_freeze` 전체 목록
- `git.dirty`가 `false`인지. **`true`면 보고용 런을 돌리지 마십시오.** 커밋되지 않은 코드로 낸 숫자는
  재현할 수 없습니다.

```bash
git status --short        # 비어 있어야 합니다
```

### 11.2 dry-run — 모델 없이 프롬프트와 토큰 수만 점검

```bash
python src/eval_mmmu.py --data-path /workspace/data/MMMU --dry-run
```

여기서 확인할 것:

- 샘플 수 **900**
- `min-pixels` / `max-pixels`의 **해결된 토큰 환산값이 980 / 3920**으로 출력되는지
  (교수님이 적으신 `1280*28*28`, `5120*28*28`은 Qwen2.5-VL의 28그리드 관습입니다. Qwen3-VL은
  patch_size 16 × merge 2 = **32그리드**이므로 같은 픽셀 수가 1280/5120 토큰이 아니라 980/3920 토큰이 됩니다.
  이 차이는 보고서에 쓸 만한 좋은 분석 재료입니다.)
- 다중 이미지 문항이 살아 있는지: 1장 857 / 2장 24 / 3장 5 / 4장 8 / 5장 6 = 900.
  **2장 이상 문항 43개가 1장으로 줄어 있으면 `<image N>` 처리에 버그가 있는 것입니다.**
- 프롬프트 토큰 최대값이 약 5,616 근처이고 **9048을 넘는 문항이 0건**인지

### 11.3 스모크 테스트 — 20문항

```bash
python src/eval_mmmu.py \
  --data-path /workspace/data/MMMU \
  --limit 20 \
  --out outputs/_smoke
```

`outputs/_smoke/metrics.json`과 `predictions.jsonl`이 생기고, 응답이 비어 있지 않은지 확인합니다.
여기서 OOM이 나면 15절 T1으로 가십시오. 스모크가 깨진 채로 본 런을 돌리면 40분을 버립니다.

### 11.4 캐시 워밍 런 (폐기용)

**첫 실행은 시간 측정에 쓸 수 없습니다.** 콜드 캐시 + vLLM의 torch.compile / CUDA 그래프 캡처가 섞여 들어갑니다.
그래서 한 번 버리는 런을 돌립니다.

```bash
python src/eval_mmmu.py --data-path /workspace/data/MMMU --limit 100 --out outputs/_warm
```

### 11.5 본 런 — 900문항

모든 값을 **명시적으로** 적습니다. 기본값에 의존하지 않는 것이 팀 간 대조에 유리합니다.

```bash
time python src/eval_mmmu.py \
  --data-path /workspace/data/MMMU \
  --split validation \
  --model Qwen/Qwen3-VL-4B-Instruct \
  --model-revision ebb281ec70b05090aa6165b016eac8ec08e71b17 \
  --dataset-revision 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 \
  --backend vllm \
  --template anchored \
  --max-model-len 9048 \
  --max-new-tokens 2048 \
  --temperature 0.7 --top-p 0.8 --top-k 20 \
  --repetition-penalty 1.0 --presence-penalty 1.5 \
  --min-pixels '1280*28*28' --max-pixels '5120*28*28' \
  --seed 3407 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 32 \
  2>&1 | tee /workspace/run_console.log
```

- `--out`을 생략하면 인자로부터 결정되는 디렉터리 이름이 자동으로 정해집니다(타임스탬프가 아닙니다).
  로그 첫 줄에 찍히는 경로를 받아 적으십시오.
- **백엔드는 `vllm`입니다.** 이유 두 가지: (1) 벽시계 시간이 `hf` 백엔드의 2~6시간 대비 **15~45분**,
  (2) 교수님이 지정한 `presence_penalty=1.5`는 **transformers에 존재하지 않는 인자**입니다
  (transformers의 `GenerationConfig`에는 `presence_penalty`도 `frequency_penalty`도 없습니다).
  `hf` 백엔드로 돌리면 스크립트가 "presence_penalty가 적용되지 않았다"는 경고를 크게 출력합니다.
  보고서에 적용했다고 쓸 수 없게 되므로, **vllm을 쓰십시오.**
- 시작 직후 vLLM이 `The context length ... is too short to hold the multi-modal embeddings in the worst case`
  경고를 냅니다. **정상이며 오류가 아닙니다.** 이유는 15절 T2에 있습니다.

진행 상황은 다른 tmux 창(`Ctrl+b` → `c`)에서 봅니다.

```bash
watch -n 5 nvidia-smi
tail -f /workspace/MMDL/outputs/<런디렉터리>/run.log
```

### 11.6 결과 확인

```bash
RUN=outputs/<런디렉터리>
python -m json.tool $RUN/metrics.json
python -m json.tool $RUN/timing.json
wc -l $RUN/predictions.jsonl        # 900이어야 합니다
```

점검 항목:

| 항목 | 기대값 |
|---|---|
| `overall.n` | 900 |
| `multiple_choice.n` + `open_ended.n` | 847 + 53 = 900 |
| `by_subject` 키 개수 | 30 |
| `by_category` 키 개수 | 6 (n이 120/150/150/150/120/210) |
| `n_unparseable` | 작을수록 좋습니다. 이 수치 자체가 진단 지표입니다 |
| `aggregation` | `"micro / sample-weighted"` |
| `timing.json`의 `model_load_s` | `inference_s`와 분리되어 있어야 합니다 |

> `n_unparseable`을 꼭 보십시오. 공식 MMMU 파서는 아무것도 파싱되지 않으면 **무작위 선택으로 떨어집니다.**
> `**C**`(마크다운 볼드)나 `c`(소문자) 같은 응답이 조용히 무작위 추측으로 바뀝니다. 이 숫자가 크면
> 점수가 떨어진 원인이 모델이 아니라 **프롬프트/파싱**입니다 — 보고서 분석 절에 쓸 핵심 재료입니다.

### 11.7 리포트 생성

```bash
python src/report.py --run-dir $RUN --out /workspace/MMDL/outputs/report_$(whoami).md
head -40 /workspace/MMDL/outputs/report_$(whoami).md
```

팀원들의 런 디렉터리를 모았다면 비교표도 만들 수 있습니다.

```bash
python src/report.py --run-dir $RUN --compare outputs/run_A outputs/run_B outputs/run_C
```

---

## 12. 결과를 파드 밖으로 꺼내기

**파드를 끄기 전에 반드시 이 절을 끝내십시오.** terminate하면 `/workspace`도 같이 사라집니다.

### 12.1 방법 A — 파드 안에서 바로 커밋·푸시 (권장)

과제 요구사항이 "각 팀원이 자기 계정으로 커밋"이므로, 파드에서 **본인 계정으로** 커밋하는 것이 가장 깔끔합니다.

```bash
cd /workspace/MMDL
git config user.name  "<본인 이름>"
git config user.email "<본인 GitHub 이메일>"

# .gitignore가 대용량 파일을 막고 있는지 먼저 확인하십시오.
cat .gitignore
git status --short
du -sh outputs/<런디렉터리>

git checkout -b baseline-$(whoami)
git add outputs/<런디렉터리>
git commit -m "baseline: MMMU validation 900 on RTX 4090 (vllm 0.11.0)"
git push -u origin baseline-$(whoami)
```

- `predictions.jsonl`은 **그냥 커밋하면 됩니다.** 최악의 경우(900개 응답이 모두 2048토큰)도 약 7.4 MB로
  GitHub의 50 MiB 경고선 아래입니다. **Git LFS는 필요 없습니다.**
- `*.parquet`, `*.safetensors`, `data/`, `.venv/`는 **절대 커밋하지 마십시오.** GitHub은 100 MiB 초과 파일을
  하드 블록하고, 한 번 히스토리에 들어가면 히스토리 재작성 없이는 빼낼 수 없습니다.
- 인증은 본인 GitHub 계정의 **fine-grained Personal Access Token**이나 SSH 키로 하십시오.
  토큰을 쓴다면 이 과제 저장소에만 권한을 준 **짧은 유효기간**으로 발급하고, **제출 후 폐기**하십시오.
  토큰 문자열을 저장소 파일이나 쉘 히스토리에 남기지 마십시오. 파드는 남의 하드웨어입니다.

### 12.2 방법 B — 노트북으로 `scp` (Direct TCP 접속일 때)

```bash
# 노트북에서 실행합니다
scp -P <PORT> -i ~/.ssh/id_ed25519 -r \
    root@<PUBLIC_IP>:/workspace/MMDL/outputs/<런디렉터리> \
    ./outputs/

# ~/.ssh/config에 Host runpod를 넣어 두었다면
scp -r runpod:/workspace/MMDL/outputs/<런디렉터리> ./outputs/
```

### 12.3 방법 C — `runpodctl` (포트가 막혔거나 방화벽 문제일 때)

```bash
# 파드에서
tar czf /workspace/result.tar.gz -C /workspace/MMDL outputs/<런디렉터리>
runpodctl send /workspace/result.tar.gz      # 출력되는 코드(단어 조합)를 복사

# 노트북에서 (runpodctl 설치 후)
runpodctl receive <코드>
```

### 12.4 꺼냈는지 최종 확인

노트북에서 아래 파일이 **모두** 있는지 확인합니다. 하나라도 없으면 보고서의 필수 항목이 빕니다.

```
outputs/<런디렉터리>/env.json          ← 실험 환경 (이번 주 최우선)
outputs/<런디렉터리>/ENVIRONMENT.md    ← 사람이 읽는 환경 표
outputs/<런디렉터리>/config.json       ← 실행 인자 전체
outputs/<런디렉터리>/predictions.jsonl ← 900줄
outputs/<런디렉터리>/metrics.json      ← 과목별·카테고리별 정확도
outputs/<런디렉터리>/timing.json       ← 총/과목별 경과 시간
outputs/<런디렉터리>/run.log
```

---

## 13. 종료 — 과금 함정 3개

### 함정 1 — 파드는 **유휴 상태에서도** 과금됩니다

파드 요금은 시작부터 종료까지 **초 단위로, GPU 사용률과 무관하게** 부과됩니다. 런이 끝나고 터미널을 켜 둔 채
밥을 먹고 오면 그 시간만큼 돈을 냅니다. 4090 Community에서 1시간 방치 = 약 $0.34.

### 함정 2 — **중지(Stop)한 파드도 볼륨 디스크 요금을 냅니다**

정지된 파드의 볼륨 디스크는 **$0.20/GB/월**로 계속 과금됩니다.

> 60 GB × $0.20 = **월 $12 = 하루 $0.40**. 일주일 방치하면 약 **$2.80** — 본 런 비용($0.17)의 16배입니다.

즉 "나중에 또 쓸지도 모르니 Stop만 해 두자"는 **본 런보다 비싼 선택**입니다.

### 함정 3 — 네트워크 볼륨은 **실행 여부와 무관하게** 과금됩니다

네트워크 볼륨은 $0.07/GB/월(1TB 미만), $0.05/GB/월(1TB 이상)이고 파드가 켜져 있든 꺼져 있든 계속 청구됩니다.
100 GB 볼륨 = 월 $7. 3절에서 권장하지 않은 이유가 바로 이것입니다.

### 종료 절차

```bash
# 1) 결과를 꺼냈는지 12.4로 다시 확인
# 2) 푸시가 올라갔는지 GitHub 웹에서 눈으로 확인
# 3) tmux 세션 정리
tmux kill-server
```

그 다음 RunPod 콘솔에서:

| 상황 | 동작 | 비용 |
|---|---|---|
| 결과를 다 꺼냈고 더 쓸 일이 없다 | **Terminate** | 0 (볼륨까지 삭제) |
| 오늘 안에 한 번 더 돌릴 것이 확실하다 | Stop | 볼륨 $0.20/GB/월 계속 |
| 며칠 뒤에 다시 쓸 것이다 | **Terminate** 후 나중에 새로 만들기 | 재설치 15분 < 며칠분 볼륨 요금 |

> **기본 선택은 Terminate입니다.** 환경 재구축은 9절을 다시 돌리면 15분이고, 그 15분($0.09)이
> 며칠간의 볼륨 요금($0.40/일)보다 쌉니다.
> Terminate 후 Billing 화면에서 **잔액이 더 이상 줄지 않는지** 확인하십시오.

---

## 14. 비용 계산 예시 (1인 1회 / 4인 팀)

> 단가는 2026-09-12 기준 근사값입니다. 시간은 RTX 4090 기준이며, 본 런은 900문항에 15~45분(중간값 30분)입니다.

### 14.1 한 팀원의 1회 실행 — Community RTX 4090, $0.34/hr

| 단계 | 예상 시간 | 비용 |
|---|---|---|
| 파드 생성 + 접속 + 5분 점검 (8절) | 5분 | $0.03 |
| venv 2개 + Stack A 설치 (9절) | 15분 | $0.09 |
| 모델 8.89 GB + validation 341 MB 다운로드 (10절) | 10분 | $0.06 |
| `--dry-run` + 20문항 스모크 (11.2–11.3) | 10분 | $0.06 |
| 캐시 워밍 런, 폐기 (11.4) | 10분 | $0.06 |
| **본 런 900문항** (11.5) | 30분 | **$0.17** |
| 결과 회수 + 커밋 + 종료 (12–13절) | 10분 | $0.06 |
| **합계** | **약 1.4시간** | **약 $0.48** |

- 실패·재시도 1회 여유를 포함하면 **$0.65 ~ $0.80**.
- 끝나고 바로 Terminate하면 스토리지 추가 비용은 **$0**.
- 끄는 것을 잊고 3시간 방치하면 **+$1.02** — 본 런보다 6배 비쌉니다.

### 14.2 4인 팀 — 두 안의 비교

**안 A (권장): 각자 Community 4090, 네트워크 볼륨 없음**

| 항목 | 계산 | 비용 |
|---|---|---|
| 4명 × 1.4시간 × $0.34 | 4 × $0.48 | **$1.92** |
| 재시도 여유 (1인당 0.5시간) | 4 × 0.5 × $0.34 | $0.68 |
| 스토리지 (즉시 Terminate) | — | $0 |
| **팀 합계** | | **약 $2.6** |

중복으로 치르는 비용: 모델을 4번 내려받는 10분 × 4 = 약 **$0.23**. 그게 전부입니다.

**안 B: Secure A40 48GB ($0.49/hr) + 100GB 팀 네트워크 볼륨**

| 항목 | 계산 | 비용 |
|---|---|---|
| 1번째 멤버 (설치 + 캐시 적재) | 1.4시간 × $0.49 | $0.69 |
| 2~4번째 멤버 (캐시 재사용, A40은 더 느려 본 런 +15~30분 추정) | 3 × 1.3시간 × $0.49 | $1.91 |
| 네트워크 볼륨 100 GB | $0.07/GB/월 | **$7.00 / 월** |
| **팀 합계 (1개월)** | | **약 $9.6** |

- 볼륨 요금이 **전체 비용의 70%**이고, 아무도 실행하지 않는 밤낮에도 계속 청구됩니다.
- 실제 청구가 일할 계산되는지는 **Billing 화면에서 직접 확인**하십시오. 어느 쪽이든 **제출한 날 볼륨을 삭제**하면
  비용이 멈춥니다.
- 캐시 공유로 절약한 시간은 팀 전체 **30분 남짓**입니다.

**결론: 안 A를 권장합니다.** 안 B는 과제 2(파인튜닝)까지 같은 캐시를 며칠 쓸 계획이 확정된 경우에만 정당화됩니다.

---

## 15. 트러블슈팅

### T1. vLLM 시작 직후 OOM (`CUDA out of memory`, 보통 프로파일링 단계)

**증상**: 모델은 올라갔는데 vLLM의 메모리 프로파일링 또는 CUDA 그래프 캡처 중에 죽습니다.

**원인**: 24GB에 가중치 8.28 GiB + ViT/활성값/그래프 약 2.5 GiB + KV 캐시를 다 넣는데,
`gpu_memory_utilization`이 남은 공간을 넘겨 잡았습니다. 또는 **이전에 죽은 런의 파이썬 프로세스가 VRAM을
붙들고 있습니다.**

**처방 — 순서대로**

```bash
# (1) 먼저 유령 프로세스를 확인하십시오. 이게 원인인 경우가 가장 많습니다.
nvidia-smi
#  Processes 목록에 python이 남아 있으면:
pkill -f eval_mmmu.py ; pkill -f vllm ; sleep 5 ; nvidia-smi

# (2) 그래도 OOM이면 0.90 -> 0.85 (FACTS 8의 권장 폴백)
python src/eval_mmmu.py --data-path /workspace/data/MMMU --gpu-memory-utilization 0.85 ...

# (3) 동시 시퀀스 수를 줄입니다 (9048토큰 시퀀스 1개 = 1.24 GiB)
python src/eval_mmmu.py ... --gpu-memory-utilization 0.85 --max-num-seqs 8

# (4) 이미지 쪽 상한을 조입니다 (vision 메모리)
python src/eval_mmmu.py ... --max-pixels '2048*28*28'
```

**`--max-model-len`은 9048에서 내리지 마십시오.** 900문항 전부를 측정한 결과 최악의 요청이
프롬프트 5,616 토큰 + 출력 2,048 = 7,664 토큰이고, **9048을 넘는 문항은 0건**입니다. 9048은 맞는 값입니다.
여기를 줄이면 교수님 설정과 달라지고, 긴 문항이 잘려 점수가 떨어집니다.

---

### T2. `The context length ... is too short to hold the multi-modal embeddings in the worst case` 경고

**이것은 오류가 아니라 경고입니다. 그대로 진행하십시오.**

무슨 뜻인가: vLLM은 인코더 캐시 크기를 **여러분의 데이터가 아니라 모델 설정의 최악의 경우**로 계산합니다.
Qwen3-VL-4B-Instruct의 `preprocessor_config.json`은 `size = {"shortest_edge": 65536, "longest_edge": 16777216}`을
싣고 있고, 32그리드에서 `16,777,216 / 32² = 16,384`이므로 **이미지 1장이 최대 16,384 비전 토큰**이 될 수 있다고
봅니다. 16,384 > 9048이니 "컨텍스트가 최악의 경우를 담기엔 짧다"고 말하는 것입니다.

그런데 **실제 MMMU validation 900문항의 최대값은 완전히 다릅니다.**

| 측정 항목 | 실측값 |
|---|---|
| 문항당 비전 토큰 최대 | 5,536 (`validation_Music_21`, 이미지 2장: 3,136 + 2,400) |
| 단일 이미지 최대 | 5,360 (`validation_Agriculture_1`, 2560×2133) |
| 질문+선택지 텍스트 최대 | 512 토큰 (`validation_Psychology_22`) |
| 채팅 템플릿 오버헤드 | 약 10~12 토큰 |
| **최악의 실제 요청** | **5,616 프롬프트 토큰** (+2,048 출력 = 7,664) |
| 9048을 넘는 문항 수 | **0 / 900** |

즉 경고는 "이론적 최악"에 대한 것이고 **여러분의 데이터에는 해당되지 않습니다.**
다만 경고가 떠 있는 동안 vLLM은 `encoder_cache_size`를 그 최악값으로 잡아 둡니다. 비전 메모리를 **실제로**
제한하고 싶다면 프로세서 상한(`mm_processor_kwargs`의 min/max pixels)과 `limit_mm_per_prompt`를
**둘 다** 지정해야 합니다 — 평가 스크립트가 이미 그렇게 하고 있습니다.

> 보고서에는 "경고가 출력되었으나 900문항 전부를 실측한 결과 최대 프롬프트 5,616 토큰으로 9048 내에
> 들어왔으며 초과 문항은 0건"이라고 적으십시오. 그 자체가 좋은 검증 기록입니다.

---

### T3. CUDA 버전이 세 개로 보여서 혼란스럽다 (여기서 몇 시간을 버립니다)

**세 숫자는 서로 다른 것을 가리킵니다. 일치할 이유가 없습니다.**

| 보이는 곳 | 실제 의미 | 중요도 |
|---|---|---|
| `nvidia-smi` 헤더의 `CUDA Version` | **드라이버가 지원하는 최대** 런타임 버전 | 드라이버 호환성 확인용 |
| `nvcc --version` | 컨테이너에 깔린 로컬 툴킷. **보통 없습니다** | 선행 빌드 휠에는 **무관** |
| `python -c "import torch; print(torch.version.cuda)"` | **휠이 빌드된 CUDA** | ★ 실제로 중요한 값 |

```bash
nvidia-smi | head -4
nvcc --version 2>/dev/null || echo "nvcc 없음 — 정상입니다"
python -c "import torch; print('torch.version.cuda =', torch.version.cuda)"
```

- `torch.version.cuda = 12.9`인데 `nvidia-smi`가 `CUDA Version: 13.0`이라고 나오는 것은 **정상이며 조치가
  필요 없습니다.** 드라이버가 12.9 런타임을 하위 호환으로 실행해 줍니다.
- 필요 조건은 하나뿐입니다: **CUDA 12.x는 드라이버 ≥ 525, CUDA 13.x는 드라이버 ≥ 580.**
- `nvcc: command not found`는 문제가 아닙니다. 우리는 아무것도 컴파일하지 않습니다(`flash-attn`을 깔지 않는
  이유이기도 합니다).
- `env.json`의 `nvcc_version`이 `null`인 것도 정상입니다. 보고서에는 **세 값을 모두** 적고 무엇이 무엇인지
  한 줄로 설명하십시오. 그러면 조교가 "CUDA 버전이 다른데요?"라고 물을 일이 없습니다.

---

### T4. 디스크가 꽉 찼다 (`No space left on device`) — HF_HOME을 export하기 전에 python을 띄웠습니다

**증상**: 모델 다운로드 중 또는 `datasets` 로딩 중에 디스크가 꽉 찼다고 죽습니다. `/workspace`에는 여유가 있는데
`/`가 100%입니다.

**원인**: HuggingFace 계열 환경변수는 **라이브러리 import 시점에 읽힙니다.** python을 먼저 띄우고 나서
(또는 주피터 커널 안에서) `os.environ`을 바꿔도 이미 결정된 캐시 경로는 바뀌지 않습니다. 그 결과 캐시가
기본 위치인 `/root/.cache/huggingface` = **컨테이너 디스크(20GB)** 에 쌓여 터집니다.

**함께 자주 틀리는 것**: `HF_DATASETS_CACHE`만 설정하는 경우. 이것은 **Arrow 캐시만** 옮기고
**내려받은 parquet 원본은 옮기지 않습니다.** `HF_HOME`과 `HF_HUB_CACHE`를 같이 지정해야 합니다.

**확인**

```bash
df -h / /workspace
du -sh /root/.cache/* 2>/dev/null
du -sh /workspace/hf 2>/dev/null
printenv | grep -E '^HF_'        # python을 띄운 쉘에서 확인하십시오
```

**처방**

```bash
# (1) 엉뚱한 곳에 쌓인 캐시를 옮깁니다
mkdir -p /workspace/hf
mv /root/.cache/huggingface/* /workspace/hf/ 2>/dev/null
rm -rf /root/.cache/huggingface
mv /root/.cache/pip /workspace/pipcache 2>/dev/null

# (2) 반드시 python을 띄우기 "전에" source 하십시오
source /workspace/env.sh
printenv HF_HOME            # /workspace/hf

# (3) 전체 repo를 받아 버렸다면 validation 외 parquet을 지웁니다 (3GB 회수)
find /workspace/data/MMMU -name '*.parquet' ! -name 'validation-*' -delete
```

**예방**: 새 터미널·새 tmux 창을 열 때마다 **첫 줄이 `source /workspace/env.sh`** 입니다. 예외 없습니다.
주피터에서 돌릴 때는 커널 자체가 그 환경변수를 물려받아야 하므로, 터미널에서 `source` 후 jupyter를 띄우십시오.

---

### T5. SSH가 끊겨서 40분 런이 죽었다

**증상**: 노트북 뚜껑을 덮었다 / 와이파이가 바뀌었다 / VS Code 창을 닫았다 → 돌아오니 프로세스가 없고
`outputs/`에 결과가 없습니다.

**원인**: SSH 세션이 끊기면 그 세션에 붙은 자식 프로세스에 `SIGHUP`이 가서 같이 죽습니다.
Community Cloud에서는 호스트 마이그레이션으로 **공인 IP가 바뀌어** 끊기는 경우도 있습니다.

**처방 1 — tmux (권장)**

```bash
tmux new -s mmmu                    # 세션 안에서 실행
# 실행 중 분리: Ctrl+b 를 누르고 손을 뗀 뒤 d
# 재접속 후:
ssh runpod
tmux attach -t mmmu                 # 런이 그대로 돌고 있습니다
tmux ls                             # 세션 목록
```

**처방 2 — nohup (tmux를 못 쓸 때)**

```bash
source /workspace/env.sh
source /workspace/venv/bin/activate
cd /workspace/MMDL
nohup python src/eval_mmmu.py --data-path /workspace/data/MMMU ... \
      > /workspace/run_nohup.log 2>&1 &
echo $! > /workspace/run.pid        # PID 저장
tail -f /workspace/run_nohup.log    # Ctrl+C로 tail만 끊어도 런은 계속됩니다

# 재접속 후 살아 있는지 확인
ps -p "$(cat /workspace/run.pid)" -o pid,etime,cmd
```

**보조 조치**

- `~/.ssh/config`에 `ServerAliveInterval 30` (7.2절)
- 노트북 절전 시 와이파이가 끊기지 않도록 설정, 또는 전원 연결
- **본 런을 주피터 노트북 셀에서 돌리지 마십시오.** 브라우저 탭이 곧 세션입니다.
- IP가 바뀌었으면 콘솔의 Connect 패널에서 새 IP/포트를 확인해 `~/.ssh/config`를 고칩니다. 파드 안의 tmux 세션은
  IP가 바뀌어도 **살아 있습니다.**

---

### T6. `hf: command not found`, 또는 `huggingface-hub`를 올렸더니 transformers가 깨졌다

**원인**: `hf` CLI는 huggingface_hub **v1**의 명령입니다. eval venv는 `transformers 4.57.1`의 요구사항
(`huggingface-hub<1.0`) 때문에 **0.35.3**을 쓰므로 `hf`가 없습니다. 여기서 `pip install -U huggingface_hub`를 하면
hub 1.x가 들어와 transformers가 깨집니다.

**처방**: 9.6절의 **tools venv**에서만 `hf`를 쓰십시오. eval venv에서 다운로드가 꼭 필요하면
deprecated 이름인 `huggingface-cli download ...`를 쓰고, `hf cache verify`는 **tools venv 전용**입니다
(hub ≥ 1.1.0 필요).
실수로 eval venv를 깼다면:

```bash
source /workspace/venv/bin/activate
pip install --no-deps --force-reinstall \
    transformers==4.57.1 tokenizers==0.22.2 huggingface-hub==0.35.3
python -c "import transformers, huggingface_hub; print(transformers.__version__, huggingface_hub.__version__)"
```

---

### T7. `load_dataset() got an unexpected keyword argument 'trust_remote_code'`

`MMMU/MMMU`는 `.py` 파일이 하나도 없는 순수 parquet 저장소이므로 `trust_remote_code`가 필요 없고,
`datasets` 4.0.0 이상에서는 **인자 자체가 제거**되어 `TypeError`가 납니다. 넘기지 마십시오.

---

### T8. 팀원과 점수가 다릅니다

먼저 **몇 점 차이인지** 보십시오.

- **1~2pp 차이 → 잡음입니다.** `temperature=0.7`은 확률적 설정이고, n=900에서 두 독립 런의 차이에 대한
  95% 구간은 **±4.33pp**입니다. 버그를 찾지 마십시오. 보고서에 "샘플링 분산 범위 내"라고 쓰십시오.
- **4pp 이상 차이 → 원인을 찾습니다.** 예측을 diff해 패턴을 보십시오.
  - 원문(`response`)은 많이 다른데 라벨(`parsed`) 뒤집힘은 적다 → **샘플링 잡음**
  - 원문은 거의 같은데 점수 차가 크다 → **파서 또는 정답 키 버그**

```bash
# 두 런의 정답 여부만 뽑아 비교
for d in outputs/run_me outputs/run_mate; do
  python -c "
import json,sys
rows={json.loads(l)['id']: json.loads(l) for l in open('$d/predictions.jsonl')}
print('$d', len(rows), sum(r['correct'] for r in rows.values()))
"
done
```

그리고 0절 합의표를 한 칸씩 대조하십시오: GPU 모델, 드라이버 CUDA, vllm 버전, 모델/데이터셋 리비전,
템플릿, 시드, `n_unparseable`. **`n_unparseable`이 크게 다르면 프롬프트나 파서가 다릅니다.**

---

### T9. 파드가 `provisioning`에서 넘어가지 않는다 / 원하는 GPU가 없다

- 해당 GPU × 해당 CUDA 필터 조합의 재고가 없는 상태입니다. 리전을 바꿔 보십시오.
- **CUDA 필터를 혼자 풀지 마십시오.** 4절의 이유 그대로, 팀 합의를 깨는 순간 비교가 불가능해집니다.
  팀 채팅에 알리고 새 합의값을 정하십시오.
- 10분 이상 `provisioning`이면 terminate하고 다시 만드는 편이 빠릅니다 (과금은 초 단위라 손실이 작습니다).

---

### T10. 첫 런의 시간이 이상하게 길다

정상입니다. 첫 실행에는 HF 다운로드, vLLM의 torch.compile, CUDA 그래프 캡처가 섞여 들어갑니다.
**그래서 11.4절에서 워밍업 런을 한 번 버립니다.** 그리고 `timing.json`의 `model_load_s`는 `inference_s`와
분리되어 기록되므로, 알파벳 순으로 첫 과목(`Accounting`)이 엔진 시작 비용을 떠안지 않습니다.
보고서의 과목별 시간 표를 해석할 때 이 점을 한 줄로 밝혀 두십시오.

> `transformers.enable_full_determinism()`을 **호출하지 마십시오.** 이 함수는 `CUDA_LAUNCH_BLOCKING=1`을
> 설정해 모든 CUDA 실행을 직렬화하므로, 교수님이 요구하는 경과 시간 표가 무의미해집니다.
> 재현성은 `set_seed()` + `VLLM_ENABLE_V1_MULTIPROCESSING=0` + 동일 하드웨어/버전으로 확보합니다.

---

## 16. 최종 체크리스트

파드를 끄기 전에 이 목록을 위에서 아래로 확인하십시오.

**시작 전**

- [ ] 0절 합의표를 4명이 같은 값으로 채웠다
- [ ] RunPod 크레딧이 $2 이상 있고 auto top-up은 꺼져 있다
- [ ] SSH 공개키를 Settings에 등록했다

**파드 생성**

- [ ] Community / RTX 4090 / **CUDA 필터 = 합의값**
- [ ] Container 20 GB, Volume 60 GB, Mount `/workspace`
- [ ] Expose TCP 22, (필요 시) HTTP 8888
- [ ] `MMDL_CONTAINER_IMAGE` 환경변수에 이미지 태그를 넣었다

**환경**

- [ ] 8절 5분 점검에서 GPU·드라이버·디스크가 기대값과 같다
- [ ] **python을 띄우기 전에** `source /workspace/env.sh`를 했다
- [ ] Stack A가 그대로 들어갔다 (`torch 2.8.0+cu128` / `vllm 0.11.0` / `transformers 4.57.1`)
- [ ] `flash-attn`을 설치하지 않았다
- [ ] 모델 리비전 `ebb281ec…`, 데이터셋 리비전 `98e6ac0c…`로 받았고 `hf cache verify`가 0을 반환했다

**실행**

- [ ] `git status --short`가 비어 있다 (`env.json`의 `git.dirty == false`)
- [ ] **tmux 안에서** 실행했다
- [ ] dry-run에서 900문항 / 이미지 1·2·3·4·5장이 857·24·5·8·6 / 토큰 환산 980·3920을 확인했다
- [ ] 워밍업 런을 한 번 버렸다
- [ ] 본 런을 `--backend vllm --template anchored --seed 3407`로 돌렸다

**결과**

- [ ] `predictions.jsonl`이 900줄이다
- [ ] `metrics.json`에 과목 30개 / 카테고리 6개 / `n_unparseable` / `aggregation`이 있다
- [ ] `timing.json`에 `model_load_s`가 `inference_s`와 분리되어 있다
- [ ] `env.json`과 `ENVIRONMENT.md`가 있고 하드웨어·드라이버·패키지가 전부 채워져 있다
- [ ] 결과를 노트북으로 꺼냈거나 **본인 GitHub 계정으로 푸시**했고, GitHub 웹에서 눈으로 확인했다
- [ ] 대용량 파일(`*.parquet`, `*.safetensors`)이 커밋되지 않았다

**종료**

- [ ] 파드를 **Terminate**했다 (Stop이 아니라)
- [ ] (Secure를 썼다면) 네트워크 볼륨을 지웠거나, 계속 과금됨을 팀이 알고 있다
- [ ] Billing에서 잔액이 더 줄지 않는다
- [ ] 사용한 GitHub 토큰을 폐기했다

---

### 참고 링크

- RunPod 문서: <https://docs.runpod.io>
- 네트워크 볼륨(Secure Cloud 전용): <https://docs.runpod.io/storage/network-volumes>
- Qwen3-VL: <https://github.com/QwenLM/Qwen3-VL>
- MMMU 벤치마크: <https://github.com/MMMU-Benchmark/MMMU> (공식 평가 코드는 `mmmu/utils/eval_utils.py`,
  `mmmu/utils/data_utils.py`. 현재 main에는 `eval/` 디렉터리가 없습니다)
- 데이터셋: <https://huggingface.co/datasets/MMMU/MMMU> (apache-2.0, arXiv:2311.16502)

문서에 없는 문제를 만났다면 **파드를 끄고**(돈이 새기 때문에) 팀 채팅에 다음 4개를 붙여 질문하십시오:
실행한 명령 전체, 에러 메시지 마지막 30줄, `outputs/*/env.json`, `nvidia-smi` 출력.

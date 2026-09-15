# 팀 실험 환경 기록 · 공유 프로토콜

> 대상: 2026-2학기 멀티모달 딥러닝 팀 프로젝트 Assignment 1 (Qwen3-VL-4B-Instruct / MMMU validation 900문항 베이스라인)
> 적용 범위: 팀원 4명 전원. 각자 자기 노트북에서 RunPod Pod을 빌려 동일한 평가를 1회 이상 수행합니다.
> 이 문서의 목적: **실험 환경을 전부 기록해 두고, 이후에 결과와 함께 팀원들에게 공유**하기 위한 절차를 고정하는 것입니다.

교수님 요구사항에는 "Experimental environment and settings (including HW infra and tool package version)"가
명시되어 있습니다. 즉 환경 기록은 부록이 아니라 **채점 항목**입니다. 그리고 4명이 서로 다른 Pod에서 돌리기
때문에, 환경 기록이 없으면 "왜 내 점수는 67.56이고 네 점수는 65.33인가"라는 질문에 **영원히 답할 수 없게 됩니다.**

이 문서는 다음 순서로 읽으십시오.

| 절 | 내용 | 언제 읽습니까 |
|---|---|---|
| 1 | 사전 합의 사항 — Pod를 빌리기 **전에** 4명이 합의할 값 | 첫 Pod 대여 전, 단 한 번 (전원 모여서) |
| 2 | 기록 대상 — 무엇을 남기는가, 왜 남기는가 | 1절 합의 직후 |
| 3 | 자동 기록 — `capture_env.py`가 대신 해 주는 부분 | 실행 직전 |
| 4 | 공유 방법 — 디렉터리 구조, 커밋 규칙, 공유 결과 표 | 실행 직후 |
| 5 | 결과가 다를 때 — 노이즈인가 버그인가 판정 절차 | 점수가 어긋났을 때 |
| 6 | 체크리스트 — 복사해서 쓰는 실행 전/후 점검표 | 매 실행마다 |

---

## 1. 사전 합의 사항 (Pod를 빌리기 전에 끝내야 합니다)

### 1.1 왜 "사전"이어야 합니까

합의를 나중에 하면 이미 돌려 버린 런은 전부 폐기해야 합니다. 특히 다음 두 항목은 **사후에 복구가 불가능합니다.**

1. **드라이버 CUDA 버전.** RunPod의 머신들은 서로 **다른 NVIDIA 드라이버를 탑재하고 있습니다.** 같은
   "RTX 4090"을 빌려도 드라이버가 다르면 커널 경로가 달라지고, 그 결과 **설명할 수 없는 정확도 차이**가
   생깁니다. RunPod UI의 `Filters > CUDA version` 필터(또는 GraphQL의 `allowedCudaVersions`)로
   **4명이 같은 드라이버 CUDA를 고정해야 합니다.** (FACTS 8)
2. **모델/데이터셋 revision SHA.** 런이 끝난 뒤에는 "그때 `main`이 무엇을 가리켰는지" 알 방법이 없습니다.
   `main`은 **움직이는 브랜치 포인터**입니다. (FACTS 6 — 자세한 이유는 2.5, 2.6절)

### 1.2 합의 표 (빈칸을 채워서 리포지터리에 커밋하십시오)

아래 표를 그대로 복사해 `합의값` 열을 채운 뒤 이 문서와 함께 커밋합니다. 합의값이 비어 있는 항목이 하나라도
있으면 **아직 Pod를 빌리지 않습니다.**

| # | 합의 항목 | 권장값 (근거) | 합의값 | 확인 방법 |
|---|---|---|---|---|
| 1 | GPU 모델 | `RTX 4090 24GB` (Ada, 1008 GB/s, 4B 모델에서 $/token 최고. FACTS 8) | `____________` | `nvidia-smi --query-gpu=name --format=csv` |
| 2 | 클라우드 타입 | `Community` (약 $0.34/hr, 2026-09-12 기준·변동) | `____________` | RunPod Pod 상세 화면 |
| 3 | 네트워크 볼륨 사용 여부 | **사용하지 않음** — 네트워크 볼륨은 Secure Cloud 전용입니다. Community 4090과 공용 볼륨은 **병행 불가**입니다 (FACTS 8) | `____________` | — |
| 4 | 드라이버 CUDA 필터 | `12.8` 로 고정 (Stack A가 cu128 휠) | `____________` | `nvidia-smi` 헤더 |
| 5 | 컨테이너 이미지 태그 | RunPod 템플릿의 이미지 문자열을 **글자 그대로** | `____________` | 2.4절 — 컨테이너 안에서는 digest를 읽을 수 없습니다 |
| 6 | lock 파일 | `requirements.lock.txt` (Stack A) | `____________` | `scripts/setup_pod.sh` |
| 7 | Python | `3.12` | `____________` | `python -V` |
| 8 | 모델 repo | `Qwen/Qwen3-VL-4B-Instruct` | `____________` | `--model` |
| 9 | **모델 revision SHA** | `ebb281ec70b05090aa6165b016eac8ec08e71b17` (FACTS 6) | `____________` | `--model-revision`, `env.json: model.revision` |
| 10 | 데이터셋 repo/경로 | `MMMU/MMMU` 또는 로컬 미러 경로 | `____________` | `--data-path` |
| 11 | **데이터셋 revision SHA** | `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` (FACTS 6) | `____________` | `--dataset-revision`, `env.json: dataset.revision` |
| 12 | split | `validation` (900문항) | `____________` | `env.json: dataset.split/n_samples` |
| 13 | 프롬프트 템플릿 | `anchored` (공식 프레이밍 + `Answer: <letter>` 파싱 앵커) | `____________` | `--template` |
| 14 | 생성 seed | `3407` (Qwen 공식 README의 Instruct 권장값. FACTS 7) | `____________` | `--seed` |
| 15 | 파서 seed | `42` **고정 — 합의 대상이 아닙니다.** 공식 `eval_utils.py`가 import 시점에 `random.seed(42)`를 호출하는 동작을 재현합니다 (FACTS 4c) | `42` | 코드 고정 |
| 16 | 샘플링 파라미터 | `temperature 0.7 / top_p 0.8 / top_k 20 / repetition_penalty 1.0 / presence_penalty 1.5` (교수님 슬라이드 16) | `____________` | `config.json` |
| 17 | 픽셀 예산 | `min_pixels 1280*28*28` / `max_pixels 5120*28*28` → **토큰으로는 980 / 3920** (1280/5120이 아닙니다. Qwen3-VL은 32 그리드. FACTS 1) | `____________` | 실행 시작 로그의 해석된 값 |
| 18 | `max_model_len` / `max_new_tokens` | `9048` / `2048` (900문항 최악 케이스 5,616 + 2,048 = 7,664로 여유 1,384. FACTS 3) | `____________` | `config.json` |
| 19 | backend | `vllm` (`presence_penalty`는 vLLM 경로에서만 존재합니다. FACTS 2) | `____________` | `--backend` |
| 20 | 기준 git commit | 4명이 **같은 커밋**에서 실행합니다 | `____________` | `env.json: git.commit` |
| 21 | 합의 일자 / 합의자 | — | `2026-__-__ / ____________` | — |

### 1.3 합의된 실행 명령 (한 줄로 고정합니다)

4명이 **문자 그대로 같은 명령**을 씁니다. `MEMBER`만 각자 자기 GitHub ID로 바꿉니다.

```bash
export MEMBER=<your-github-id>
export RUN_ID=qwen3vl4b-val-anchored-vllm-seed3407

python src/eval_mmmu.py \
  --data-path /workspace/mmmu \
  --model Qwen/Qwen3-VL-4B-Instruct \
  --model-revision ebb281ec70b05090aa6165b016eac8ec08e71b17 \
  --dataset-revision 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 \
  --backend vllm --split validation --template anchored \
  --max-model-len 9048 --max-new-tokens 2048 \
  --temperature 0.7 --top-p 0.8 --top-k 20 \
  --repetition-penalty 1.0 --presence-penalty 1.5 \
  --min-pixels 1280*28*28 --max-pixels 5120*28*28 \
  --seed 3407 --gpu-memory-utilization 0.90 --max-num-seqs 32 \
  --out results/$MEMBER/$RUN_ID
```

> `presence_penalty 1.5`는 **vLLM에서만** 적용됩니다. transformers의 `GenerationConfig`에는
> `presence_penalty`가 **존재하지 않습니다** (FACTS 2). `--backend hf`를 쓰면 `eval_mmmu.py`가
> 큰 경고를 출력합니다. 그 경고가 보이면 보고서에 "presence_penalty 미적용"을 **반드시** 적어야 합니다.
> 적용하지 않은 설정을 적용한 것처럼 쓰는 것이 이 과제에서 가장 흔한 감점 사유입니다.

---

## 2. 기록 대상 — 전체 체크리스트

`src/capture_env.py`가 만드는 `env.json`의 최상위 키는 다음과 같이 고정되어 있습니다.

```
schema_version, captured_at_utc, hardware, driver_cuda, os, python, packages,
model, dataset, run_config, git, notes
```

아래는 그 각 그룹이 무엇을 담고 **왜 필요한지**입니다.

### 2.1 hardware — `gpu_name, gpu_count, vram_total_mib, cpu_model, cpu_count, ram_gib`

**왜 필요한가:** 속도 비교의 분모입니다. 교수님은 총 소요시간과 과목별 소요시간을 요구합니다.
GPU가 다르면 그 표는 서로 비교 불가능합니다. A40(Ampere, 약 696 GB/s, FP8 없음)은 4090(Ada, 1008 GB/s)
대비 대략 2배 느리므로, GPU 모델을 적어두지 않은 시간 표는 숫자로서 의미가 없습니다 (FACTS 8).
VRAM은 `gpu_memory_utilization 0.90`이 타당했는지(24GB에서 가중치 8.28 GiB + KV 약 10.8 GiB ≈ 9048토큰 시퀀스 8개)
판단하는 근거입니다 (FACTS 8).

### 2.2 driver_cuda — `nvidia_smi_cuda, torch_version_cuda, nvcc_version, driver_version`

**왜 필요한가:** 여기서 학생들이 몇 시간을 낭비합니다. CUDA 버전은 **세 개가 서로 다른 것**입니다 (FACTS 9).

| 값 | 의미 | 중요도 |
|---|---|---|
| `nvidia-smi` 헤더의 CUDA | **드라이버가 지원하는 최대** 런타임 버전 | 팀 간 일치시켜야 하는 값 (1.2절 #4) |
| `nvcc --version` | 로컬 툴킷. 보통 **설치되어 있지도 않으며**, 미리 빌드된 휠과는 무관 | 기록만 하고 무시 |
| `torch.version.cuda` | **실제로 중요한 값** — 휠이 어떤 CUDA로 빌드되었는가 | 4명이 반드시 같아야 하는 값 |

> `nvidia-smi`가 CUDA 13.0인데 `torch.version.cuda`가 12.9/12.8인 것은 **정상이며 조치할 필요가 없습니다.**
> CUDA 12.x는 드라이버 >= 525, 13.x는 >= 580을 요구합니다. 이 설명은 `env.json`의 `notes`에 그대로 들어갑니다.

### 2.3 os + container

**왜 필요한가:** glibc/커널/컨테이너 이미지가 다르면 같은 휠도 다른 경로를 탈 수 있습니다. OS·커널·libc는
`capture_env.py`가 자동으로 읽습니다.

### 2.4 컨테이너 이미지 — **자동화의 유일한 예외**

컨테이너 **내부에서는 자기 이미지의 digest를 읽을 수 없습니다.** `RepoDigests`는 Docker 데몬 메타데이터에
있고, 로컬 이미지 ID는 그것과 다른 해시입니다 (FACTS 8). 따라서 다음 중 하나를 해야 합니다.

- RunPod 템플릿의 **환경 변수로 태그 문자열을 주입**합니다: `CONTAINER_IMAGE=<템플릿의 이미지 문자열>`.
  `capture_env.py`는 이 환경 변수를 읽어 기록합니다.
- 주입하지 않으면 이 필드는 **그냥 null이 됩니다.** 추측해서 채우지 마십시오.

### 2.5 python packages — 그리고 `pip_freeze` 전체

`env.json: packages`에는 다음이 개별 키로 들어갑니다.

```
torch torchvision transformers tokenizers huggingface-hub accelerate
safetensors vllm datasets pillow numpy qwen-vl-utils flash-attn
```

그리고 `packages.pip_freeze`에 **전체 목록**이 배열로 들어갑니다.

**왜 필요한가:**

- `vllm 0.11.0`은 Qwen3VLForConditionalGeneration이 처음 등록된 릴리스입니다(v0.10.2에는 없습니다).
  즉 vLLM 버전은 "돌아가냐 안 돌아가냐"를 가르는 값입니다 (FACTS 5).
- `vllm 0.29.0`의 메타데이터는 `transformers>=5.10.4`를 요구합니다. 그래서 **transformers 4.57.x + 최신 vLLM
  조합은 물리적으로 불가능합니다.** 둘 중 정합한 쌍을 골라야 하며, 어느 쌍을 골랐는지는 기록되어야 합니다 (FACTS 5).
- `tokenizers`는 Stack A에서 `0.22.2`를 씁니다(`0.23.0`은 PyPI에 없고, `0.23.1` 이상은 금지). `huggingface-hub`은 현재 1.31.0이
  최신이지만 transformers 4.57.1은 `<1.0`을 요구하므로 `0.35.3`으로 **반드시 핀**해야 합니다. 이런 항목은
  누군가 `pip install -U`를 한 번 눌렀는지 여부로 갈리므로, `pip_freeze` 전체가 필요합니다.
- `flash-attn`은 **설치하지 않는 것이 정답입니다.** PyPI에 sdist만 있어 30~60분 컴파일이 걸립니다.
  Qwen3VL은 `_supports_sdpa = True`이므로 `attn_implementation="sdpa"`로 충분합니다 (FACTS 5).
  그래서 `flash-attn` 키는 `null`로 기록되는 것이 **정상이며, 그 사실 자체가 기록 가치가 있습니다.**

### 2.6 model artifact — `repo_id, revision, local_path, dtype, attn_implementation`

### 2.7 dataset artifact — `repo_id_or_path, revision, split, n_samples`

> ### ★ 가장 많이 잊는 두 항목: model revision SHA / dataset revision SHA ★
>
> 이 두 줄이 이 문서에서 가장 중요합니다.
>
> - `MMMU/MMMU`의 현재 HEAD는 `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`입니다. 그런데 이 저장소의
>   **데이터 파일은 2026년에 세 번 바뀌었습니다** — 2026-02-12, 2026-04-21, 2026-07-10의 "Upload dataset"
>   커밋입니다. 즉 **공개 점수 67.4가 발표된 이후에 데이터셋이 변경되었습니다.** 따라서
>   **"MMMU validation" 또는 "MMMU/MMMU"라는 문자열만으로는 재현 가능한 식별자가 아닙니다.** (FACTS 6)
> - `main`은 **가변 브랜치 포인터**입니다. `from_pretrained` / `AutoProcessor` / `LLM()` / `load_dataset`
>   전부에 `revision=`을 넘겨야 합니다. vLLM에서는 `tokenizer_revision`도 **따로** 핀해야 합니다 —
>   기본값이 `None`이어서 모델과 무관하게 `main`을 따라갑니다 (FACTS 6).
> - 우리 팀은 Community Cloud 4090을 쓰므로 **공용 네트워크 볼륨을 쓸 수 없습니다**(FACTS 8). 즉 4명이
>   각자 따로 다운로드합니다. 그래서 revision 핀이 "있으면 좋은 것"이 아니라 **유일한 동일성 보증**입니다.
>
> 검증 방법은 스택에 따라 다릅니다.
> - `huggingface_hub >= 1.1.0` (Stack B): `hf cache verify <repo> --revision <sha> --repo-type dataset`
>   는 체크섬 불일치 시 non-zero로 종료합니다. `--local-dir`, `--fail-on-missing-files`,
>   `--fail-on-extra-files` 플래그를 함께 쓰십시오 (FACTS 5).
> - **Stack A는 `huggingface-hub==0.35.3`이므로 `hf` CLI도, `cache verify`도 없습니다.** 이 경우에는
>   `env.json`의 `model.revision` / `dataset.revision`에 **해석된 커밋 SHA**가 찍혔는지를 대조하는 것이
>   검증입니다. 1.2절 #9/#11의 합의값과 글자 단위로 같은지 확인하십시오.

### 2.8 run config

`--out` 디렉터리의 `config.json`에 전체 인자가 남습니다. 여기에는 샘플링 파라미터, 템플릿 이름,
seed, `max_model_len`, 그리고 **해석된 픽셀 예산**이 들어갑니다.

**왜 필요한가:** 프롬프트 템플릿 하나로 MMMU 점수는 **수 포인트** 움직입니다 (FACTS 11). 또한 픽셀 예산은
공식이 아니라 **해석된 값**을 기록해야 합니다. `AutoProcessor.from_pretrained()`에 `max_pixels`를 넘기는 것은
transformers <= 4.57.1에서 **조용히 무시되었습니다**(issue #41955, PR #41997로 수정). 그래서 안전한 형태는
`size={"shortest_edge":..., "longest_edge":...}`를 명시적으로 넘기고, **항상 해석된
`processor.image_processor.size` 딕트를 로그에 남기는 것**입니다 (FACTS 1). 공식만 적어둔 기록은 거짓일 수 있습니다.

또한 HF 환경 변수는 **import 시점에 읽힙니다.** `HF_HOME`(과 `HF_HUB_CACHE`)을 `/workspace`로
**python 실행 전에** export해야 하고, 그 값도 기록 대상입니다. `HF_DATASETS_CACHE`만 바꾸면 Arrow 캐시만
옮겨지고 **내려받은 parquet은 그대로 남습니다** (FACTS 5). 전송 가속은 `HF_HUB_ENABLE_HF_TRANSFER=1`이
아니라 `HF_XET_HIGH_PERFORMANCE=1`입니다(전자는 폐기되어 아무 동작도 하지 않습니다).

### 2.9 results provenance — `git.commit`, `git.branch`, `git.dirty`

**왜 필요한가:** 결과 파일만 있고 코드 버전이 없으면 그 결과는 재현 불가입니다. `eval_mmmu.py`는
**보고 가능한 런에서 `git.dirty == true`이면 실행을 거부합니다** (FACTS 12). 거부당했다면 커밋하거나
stash하고 다시 돌리십시오. 이 거부는 버그가 아니라 **기능**입니다.

### 2.10 기록 대상 요약표

| 그룹 | 핵심 필드 | 없으면 생기는 문제 |
|---|---|---|
| hardware | `gpu_name`, `vram_total_mib` | 시간 표가 비교 불가 |
| driver+CUDA | `nvidia_smi_cuda`, **`torch_version_cuda`** | 설명 불가능한 정확도 차이 (FACTS 8) |
| OS+container | `os`, `CONTAINER_IMAGE` | 동일 휠의 다른 동작을 추적 불가 |
| python packages | 13개 개별 키 + `pip_freeze` | 누가 `-U`를 눌렀는지 영구 미제 |
| **model artifact** | **`revision` (커밋 SHA)** | 서로 다른 가중치로 비교한 꼴 |
| **dataset artifact** | **`revision` (커밋 SHA)** | 서로 다른 900문항으로 비교한 꼴 (FACTS 6) |
| run config | `config.json` 전체 + 해석된 픽셀 예산 | 템플릿/픽셀 차이로 수 pp 이동 |
| results provenance | `git.commit`, `git.dirty` | 결과의 출처 소실 |

---

## 3. 자동 기록 — `capture_env.py`

### 3.1 손으로 적은 기록은 반드시 어긋납니다

손 기록이 실패하는 이유는 게으름이 아닙니다. 구조적입니다.

1. **시점이 어긋납니다.** 런이 끝난 뒤에 `pip list`를 다시 보면, 그 사이에 무언가를 설치했을 수 있습니다.
   특히 `pip install -U`를 한 번 누르면 Stack A는 조용히 깨집니다.
2. **해석된 값이 아니라 의도한 값을 적습니다.** "max_pixels = 5120*28*28"이라고 적지만 실제 프로세서는
   그 값을 무시했을 수 있습니다 (2.8절).
3. **`main`을 "main"이라고 적습니다.** SHA가 아니라 브랜치 이름을 적으면 기록이 아닙니다.
4. **누락이 보이지 않습니다.** 13개 패키지 중 하나를 빼먹어도 표는 완성된 것처럼 보입니다.

### 3.2 어떻게 자동화되어 있습니까

```bash
# 단독 실행 (Pod 세팅 직후 사전 점검용)
python -m src.capture_env --out results/$MEMBER/preflight
#  -> results/$MEMBER/preflight/env.json, ENVIRONMENT.md 두 개를 만듭니다.
```

평가 본 실행에서는 직접 호출하지 않아도 됩니다. `eval_mmmu.py`가 **모델을 로드하기 전에**
`env.json`과 `ENVIRONMENT.md`를 먼저 씁니다 (FACTS 12: "Emit env.json from INSIDE the eval script at
run start, never by hand afterwards"). 모델 로드 전에 쓰는 이유는 **OOM으로 죽어도 환경 기록은 남기기
위해서**입니다. 실패한 런의 환경 기록이 오히려 더 유용합니다.

`ENVIRONMENT.md`는 `env.json`을 사람이 읽는 표로 렌더한 것이며, 보고서의
"Experimental environment and settings" 절에 그대로 붙여 넣을 수 있는 형태입니다.

### 3.3 자동 기록으로 덮이지 않는 것

| 항목 | 이유 | 대응 |
|---|---|---|
| 컨테이너 이미지 digest | 컨테이너 내부에서 읽을 수 없습니다 (FACTS 8) | 템플릿 환경변수 `CONTAINER_IMAGE`로 주입 |
| RunPod 시간당 단가 | API로 노출되지 않습니다 | 합의 표 #2에 기록(근사치임을 명시) |
| "왜 그렇게 했는가" | 기계가 알 수 없습니다 | `env.json: notes` / 보고서 본문 |

---

## 4. 공유 방법

### 4.1 리포지터리 구조 — 팀원 1명당 디렉터리 1개

```
MMDL/
├── assignment/
│   └── assignment1.md                  <- 제출물 (팀장 계정 리포 기준 경로)
├── docs/
│   └── TEAM_PROTOCOL.md                <- 이 문서
├── requirements.lock.txt               <- Stack A (기본)
├── requirements-current.txt            <- Stack B (대안)
├── scripts/{setup_pod.sh,fetch_data.sh,run_baseline.sh}
├── src/
└── results/
    ├── SUMMARY.md                      <- 4.4절 공유 결과 표 (팀 공용, 각자 자기 행만 추가)
    ├── <github-id-1>/
    │   └── qwen3vl4b-val-anchored-vllm-seed3407/
    │       ├── env.json            ├── ENVIRONMENT.md
    │       ├── config.json         ├── metrics.json
    │       ├── timing.json         ├── predictions.jsonl
    │       ├── run.log             └── report.md
    ├── <github-id-2>/ ...
    ├── <github-id-3>/ ...
    └── <github-id-4>/ ...
```

**규칙:** 자기 디렉터리 밖의 파일은 건드리지 않습니다. `results/SUMMARY.md`만 공용이며, 각자 **자기 행 한 줄**만
추가합니다. 이렇게 하면 4명이 동시에 push해도 충돌 지점이 한 파일의 서로 다른 줄로 제한됩니다.

### 4.2 이름 규칙

```
results/<github-id>/<run_id>/
run_id = <model_short>-<split>-<template>-<backend>-seed<seed>
예:      qwen3vl4b-val-anchored-vllm-seed3407
```

- `run_id`는 **설정에서 결정론적으로 유도됩니다. 타임스탬프를 쓰지 않습니다.** 타임스탬프를 쓰면 같은 설정의
  런인지 눈으로 알 수 없고, 디렉터리 이름만으로 비교 가능 여부를 판단할 수 없게 됩니다.
  (`eval_mmmu.py --out`의 기본값도 같은 원리로 만들어집니다.)
- **같은 설정으로 두 번 이상 돌린 경우에만** 뒤에 `-r2`, `-r3`을 붙입니다. 설정이 조금이라도 다르면 접미사가
  아니라 `run_id` 자체가 달라져야 합니다. 예: `...-template-official-...`은 다른 런입니다.
- 설정이 다른 런을 같은 `run_id`로 덮어쓰는 것이 이 프로젝트에서 가장 위험한 실수입니다.

### 4.3 커밋 대상 / 절대 커밋 금지 (FACTS 12)

**커밋합니다 (전부 텍스트이며 작습니다):**

| 파일 | 비고 |
|---|---|
| `env.json`, `ENVIRONMENT.md` | 환경 기록 본체 |
| `config.json` | 실행 인자 전체 |
| `metrics.json`, `timing.json` | 점수·시간 표의 원천 |
| `predictions.jsonl` | **Git LFS 불필요.** 900개 응답이 전부 2048토큰인 최악의 경우도 약 7.4 MB로, 50 MiB 경고 임계값 아래입니다. 평문 JSONL로 커밋하십시오 |
| `run.log` | 경고·해석된 픽셀 예산·unparseable 카운트가 들어 있습니다 |
| `report.md` | `src/report.py` 출력 |

**절대 커밋하지 않습니다:**

```
*.safetensors      # 모델 가중치 8.89 GB / 2 shards
*.parquet          # MMMU 전체 3.66 GB, validation만도 약 341 MB
data/  images/     # 데이터셋·추출 이미지
.venv/  __pycache__/
HF 캐시 디렉터리 (HF_HOME 이하 전체)
HF_TOKEN 등 토큰·자격증명 (env.json에도 절대 들어가서는 안 됩니다)
```

> GitHub는 **100 MiB 초과 파일을 하드 블록**합니다. 그리고 큰 blob이 **한 번 히스토리에 들어가면 제거에
> 히스토리 재작성이 필요합니다.** 그래서 `.gitignore`를 **맨 처음에** 넣는 것이 중요합니다 (FACTS 12).
> 실수로 커밋했다면 push하기 전에 즉시 `git reset`하고, 이미 push했다면 팀 전체에 알리고 함께 처리하십시오.

**커밋 주체:** 각 팀원은 **자기 GitHub 계정으로 직접 커밋**합니다. 팀장이 대신 올리면 개인 기여가
기록되지 않습니다(과제 요구사항).

### 4.4 공유 결과 표 — `results/SUMMARY.md`

두 개의 표로 관리합니다. 둘은 `(member, run_id)`로 조인되는 **하나의 레코드**이며, 열 이름과 순서는 아래와
같이 **고정**합니다. 값은 전부 `metrics.json` / `timing.json` / `env.json`에서 그대로 옮깁니다.
손으로 계산하지 마십시오.

#### 표 A — 결과 (열 순서 고정)

`member | run_id | overall_acc | correct/n | mc_acc | open_acc | n_unparseable | total_wall_s | model_load_s | vs_67.4`

#### 표 B — 환경 (열 순서 고정)

`member | run_id | commit | gpu | driver_cuda | torch_cuda | torch | transformers | vllm | model_rev7 | dataset_rev7 | template | seed | note`

- `overall_acc`, `mc_acc`, `open_acc`: 퍼센트, 소수점 **둘째 자리까지**.
- `vs_67.4`: `overall_acc - 67.4`를 부호와 함께. 기준 67.4는 Qwen3-VL technical report(arXiv:2511.21631)의
  MMMU validation 공개 점수입니다.
- `model_rev7` / `dataset_rev7`: 커밋 SHA **앞 7자**. 전체 SHA는 각자의 `env.json`에 있습니다.
- `n_unparseable`: MC 파서가 랜덤 추측으로 빠진 문항 수. 점수보다 먼저 봐야 하는 진단값입니다 (5.3절).
- `total_wall_s`에는 `model_load_s`가 포함되지 않도록 `timing.json`의 값을 그대로 씁니다
  (엔진 기동 비용이 알파벳순 첫 과목에 전가되지 않게 분리되어 있습니다. FACTS 7).

#### 기입 예시 (형식을 오해하지 않도록 채운 예 — 실제 값이 아닙니다)

표 A

| member | run_id | overall_acc | correct/n | mc_acc | open_acc | n_unparseable | total_wall_s | model_load_s | vs_67.4 |
|---|---|---|---|---|---|---|---|---|---|
| jun-lee | qwen3vl4b-val-anchored-vllm-seed3407 | 66.89 | 602/900 | 68.24 | 45.28 | 18 | 1683.4 | 96.2 | -0.51 |
| minji-kim | qwen3vl4b-val-anchored-vllm-seed3407 | 67.56 | 608/900 | 68.83 | 47.17 | 15 | 1721.9 | 99.5 | +0.16 |
| sehun-park | qwen3vl4b-val-anchored-vllm-seed3407 | 67.22 | 605/900 | 68.60 | 45.28 | 21 | 1755.0 | 101.3 | -0.18 |
| yerin-choi | qwen3vl4b-val-anchored-vllm-seed3407 | 65.33 | 588/900 | 66.71 | 43.40 | 19 | 1702.1 | 97.0 | -2.07 |

표 B

| member | run_id | commit | gpu | driver_cuda | torch_cuda | torch | transformers | vllm | model_rev7 | dataset_rev7 | template | seed | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| jun-lee | qwen3vl4b-val-anchored-vllm-seed3407 | a1b2c3d | RTX 4090 24GB | 12.8 | 12.8 | 2.8.0 | 4.57.1 | 0.11.0 | ebb281e | 98e6ac0 | anchored | 3407 | 기준 런 |
| minji-kim | qwen3vl4b-val-anchored-vllm-seed3407 | a1b2c3d | RTX 4090 24GB | 12.8 | 12.8 | 2.8.0 | 4.57.1 | 0.11.0 | ebb281e | 98e6ac0 | anchored | 3407 | — |
| sehun-park | qwen3vl4b-val-anchored-vllm-seed3407 | a1b2c3d | RTX 4090 24GB | 13.0 | 12.8 | 2.8.0 | 4.57.1 | 0.11.0 | ebb281e | 98e6ac0 | anchored | 3407 | 합의 위반: CUDA 필터 12.8 미적용(드라이버 13.0). torch_cuda 12.8은 정상(FACTS 9). 재런 예정 |
| yerin-choi | qwen3vl4b-val-anchored-vllm-seed3407 | a1b2c3d | RTX 4090 24GB | 12.8 | 12.8 | 2.8.0 | 4.57.1 | 0.11.0 | ebb281e | 98e6ac0 | anchored | 3407 | 최저값. 5절 판정 결과 = 샘플링 노이즈 |
| 팀 요약 | — | 최소 65.33 / 최대 67.56 / **폭 2.23 pp** | — | — | — | — | — | — | — | — | — | — | 2.23 pp < 4.33 pp → 노이즈 범위 (5.1절) |

> 위 예시에서 `sehun-park`의 행이 알려 주는 것: 점수(67.22)는 멀쩡해 보이지만 **드라이버 CUDA가 13.0으로
> 혼자 다릅니다.** 표 B가 없으면 이 사실이 영구히 묻힙니다. 바로 이것이 1.2절 #4(CUDA 필터)를 합의하는 이유입니다.

### 4.5 보고서 본문으로 옮기는 방법

```bash
# 자기 런의 보고서 생성
python src/report.py --run-dir results/$MEMBER/$RUN_ID --out results/$MEMBER/$RUN_ID/report.md

# 팀원 비교 표까지 포함한 통합 보고서 (팀장이 1회 수행)
python src/report.py \
  --run-dir results/jun-lee/$RUN_ID \
  --compare results/minji-kim/$RUN_ID results/sehun-park/$RUN_ID results/yerin-choi/$RUN_ID \
  --out assignment/assignment1.md
```

`report.py`는 전체 정확도 표, 6개 카테고리 표, 30개 과목 표, 시간 표, 환경 표, 공개 점수 대비 비교 행을
GitHub Flavored Markdown으로 출력합니다. **집계는 micro(샘플 가중) 평균입니다.** 카테고리별 표본 수가
120/150/150/150/120/210으로 다르므로 **6개 카테고리 정확도의 단순 평균은 Overall과 일치하지 않습니다.**
보고서에 집계 방식을 명시하십시오 (FACTS 4b).

---

## 5. 결과가 다를 때 — 노이즈인가 버그인가

**이 절이 이 문서에서 실무적으로 가장 많이 쓰일 부분입니다.**

### 5.1 먼저: 1~2 pp 차이는 정상입니다

교수님이 지정한 샘플링 설정 `temperature=0.7 / top_p=0.8 / top_k=20`은 **확률적(stochastic)** 입니다.
비트 단위 재현은 불가능하며, **팀원 4명은 반드시 서로 다른 숫자를 얻습니다** (FACTS 7).

n=900, p=0.674에서의 통계량입니다 (FACTS 7).

| 양 | 값 | 의미 |
|---|---|---|
| 1문항의 가치 | **0.111 pp** | 9문항 차이 = 1 pp |
| 표준오차 (SE) | **1.56 pp** | 한 번의 런이 참값 주변에서 흔들리는 폭 |
| 한 런의 95% 구간 | 약 ±3.06 pp (= 1.96 × 1.56) | 단일 런을 참값으로 오해하면 안 되는 범위 |
| **두 독립 런 차이의 95% 구간** | **±4.33 pp** | **두 팀원의 점수 차가 이 안이면 노이즈입니다** |
| ±4.33 pp의 문항 환산 | 약 39문항 | 39문항까지는 "그럴 수 있다"의 영역 |

**판정 기준:**

- 두 팀원의 `overall_acc` 차이가 **4.33 pp 이내 → 노이즈로 간주합니다. 버그를 찾지 마십시오.**
  4.4절 예시의 2.23 pp는 정확히 이 경우입니다.
- **4.33 pp를 초과 → 조사합니다.** 다만 초과했다는 사실 자체가 버그의 증명은 아닙니다. 5.3절의 절차로
  원인을 분리합니다.

> 보고서에 이 문장을 넣으십시오: "4명의 런은 확률적 샘플링 설정 하에서 수행되었으며, n=900에서 두 독립
> 런 차이의 95% 구간은 ±4.33 pp이다. 따라서 관측된 폭 X pp는 샘플링 변동과 구분되지 않는다."
> 이것은 변명이 아니라 **정량적 분석이며, 성능 분석 항목의 점수를 받는 서술입니다.**

### 5.2 차이를 줄이고 싶다면 (완전히 없앨 수는 없습니다)

- vLLM의 seed는 **두 군데**입니다. `LLM(seed=...)`는 기본 0, `SamplingParams.seed`는 기본 `None`입니다.
  **둘 다** 설정해야 합니다 (FACTS 7).
- 추가로 오프라인 추론에서는 `VLLM_ENABLE_V1_MULTIPROCESSING=0`, 또는 `VLLM_BATCH_INVARIANT=1`이 필요합니다.
- 그리고 이 재현성은 **동일한 하드웨어 + 동일한 vLLM 버전에서만** 성립합니다. 그래서 1절 합의가 선행합니다.
- 파서 쪽 변동도 있습니다. 공식 MC 파서는 아무것도 파싱되지 않으면 `random.choice(all_choices)`로
  **랜덤 추측**합니다. 즉 점수가 전역 `random` 스트림에, 따라서 **샘플 순서에** 의존합니다.
  우리 코드는 순서를 `(SUBJECTS.index(subject), id의 마지막 숫자)`로 고정하고 파싱 루프 직전에
  `random.seed(42)`를 호출합니다 (FACTS 4c). **순서를 바꾸면 점수가 바뀝니다. 바꾸지 마십시오.**
- **`transformers.enable_full_determinism()`은 절대 호출하지 마십시오.** 이 함수는
  `CUDA_LAUNCH_BLOCKING=1`을 설정해 모든 CUDA 실행을 직렬화하므로, **교수님이 요구한 소요시간 표가
  무의미해집니다** (FACTS 7). `set_seed()` + 위의 vLLM 환경변수까지만 씁니다.

### 5.3 판정 절차 (순서대로, 멈추지 않고 끝까지)

#### Step 0 — 같은 실험인지 확인합니다

```bash
diff <(python -m json.tool results/A/$RUN_ID/config.json) \
     <(python -m json.tool results/B/$RUN_ID/config.json)
diff <(python -m json.tool results/A/$RUN_ID/env.json) \
     <(python -m json.tool results/B/$RUN_ID/env.json)
```

`config.json`에 차이가 있으면 **그 차이가 원인입니다. 여기서 끝입니다.** 특히 `template`, `min/max_pixels`,
`max_model_len`, `backend`를 보십시오. `env.json`에서는 `model.revision`, `dataset.revision`,
`packages.transformers`, `packages.vllm`, `driver_cuda.*`, `hardware.gpu_name`을 보십시오.
**revision이 다르면 두 사람은 애초에 다른 실험을 한 것입니다** (2.6/2.7절).

#### Step 1 — 차이의 크기를 4.33 pp와 비교합니다

```bash
python src/report.py --run-dir results/A/$RUN_ID --compare results/B/$RUN_ID
```

4.33 pp 이내라면 기록만 하고 종료합니다(5.1절).

#### Step 2 — 예측을 문항 단위로 비교합니다

```bash
python src/report.py --run-dir results/A/$RUN_ID --compare results/B/$RUN_ID
```

비교 리포트가 요약해 주는 수치를 직접 세어 보고 싶거나, 쓰고 있는 `report.py`가 예측 단위 비교 플래그
(`--diff`)를 제공하지 않는다면 아래 스니펫이 **정확히 같은 판정값**을 출력합니다. 의존성은 표준 라이브러리뿐입니다.

```bash
python - results/A/$RUN_ID/predictions.jsonl results/B/$RUN_ID/predictions.jsonl <<'PY'
import json, sys

def load(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                rows[r["id"]] = r
    return rows

a, b = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(set(a) & set(b))
only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
n = max(len(ids), 1)

text  = sum(1 for i in ids if a[i]["response"] != b[i]["response"])   # 생성 텍스트가 다른 문항
label = sum(1 for i in ids if a[i]["parsed"]   != b[i]["parsed"])     # 파싱된 라벨이 다른 문항
flip  = sum(1 for i in ids if bool(a[i]["correct"]) != bool(b[i]["correct"]))  # 정오가 뒤집힌 문항
acc   = lambda d: 100.0 * sum(bool(r["correct"]) for r in d.values()) / max(len(d), 1)
unp   = lambda d: sum(bool(r.get("unparseable")) for r in d.values())

print(f"공통 문항           : {len(ids)}")
print(f"A에만 / B에만       : {len(only_a)} / {len(only_b)}  {only_a[:5]} {only_b[:5]}")
print(f"응답 텍스트 불일치  : {text}  ({100.0*text/n:.1f}%)")
print(f"파싱 라벨 불일치    : {label} ({100.0*label/n:.1f}%)")
print(f"정오 반전           : {flip}  -> 점수 차 상한 {100.0*flip/n:.2f} pp")
print(f"정확도 A / B        : {acc(a):.2f} / {acc(b):.2f}  (차이 {acc(a)-acc(b):+.2f} pp)")
print(f"unparseable A / B   : {unp(a)} / {unp(b)}")
PY
```

#### Step 3 — 판정표를 적용합니다

| 관측 패턴 | 판정 | 다음 행동 |
|---|---|---|
| 응답 텍스트 불일치 **많음**(수백 건) + 정오 반전 **적음** + 점수 차 ≤ 4.33 pp | **샘플링 노이즈. 정상입니다.** | 기록만 하고 종료. 보고서에 폭과 4.33 pp를 같이 씁니다 |
| 응답 텍스트 불일치 **적음**(수십 건 이하) + 점수 차 **큼** | **파서 또는 정답 키 버그** | 5.4절 점검 목록으로 내려갑니다 |
| 응답 텍스트 불일치 **거의 0** + 점수 차 존재 | **같은 생성물을 다르게 채점**했습니다 → 파서/정답 키 확정 | 코드 버전 확인(`git.commit`), 5.4절 |
| `unparseable` 수가 **크게 다름** | 프롬프트 템플릿 또는 파싱 경로 문제 | `config.json`의 `template` 비교 → 5.4절 |
| `A에만`/`B에만` 문항이 존재 | **데이터 로딩 자체가 다름** (가장 심각) | `dataset.revision`, `--subjects`, `--limit` 확인 |
| 공통 문항 수가 900이 아님 | 필터가 걸려 있거나 로딩이 누락됨 | `--limit` 제거, 30개 config 전부 로드됐는지 확인 |

**요약:** *텍스트는 많이 다르지만 라벨은 거의 같다 → 노이즈.* *텍스트는 거의 같은데 점수가 다르다 → 버그.*

#### Step 4 — 시간이 다를 때

시간 차이는 정확도와 별개로 판정합니다. 첫 런은 **콜드 캐시**이며 HF 다운로드와 vLLM의
`torch.compile`/CUDA 그래프 캡처가 포함됩니다. 그래서 **캐시를 예열하고 한 런을 버린 뒤 본 런을 측정**하며,
`model_load_s`는 따로 기록합니다 (FACTS 7). `total_wall_s`가 2배 이상 차이 난다면 먼저
`hardware.gpu_name`(4090 vs A40 — 약 2배)과 `model_load_s`를 보십시오.

### 5.4 버그로 판정되었을 때 점검 목록 (흔한 순서대로)

1. **`<image N>` 매핑** — 마커 `<image N>`은 **컬럼 `image_N`** 에 대응합니다(1-indexed).
   **왼쪽에서 오른쪽 순서로 이미지를 소비하면 안 됩니다.** `validation_Math_19`의 마커 순서는
   `[1,2,1,1,2]`로 같은 이미지를 4번 참조합니다 (FACTS 4a).
2. **options 안의 마커** — 900행 중 **13행은 `question`에 마커가 전혀 없고** 마커가 `options` 문자열
   안에만 있습니다(예: `validation_Biology_24`). `question`과 `options`를 **둘 다** 스캔해야 합니다 (FACTS 4a).
3. **고아(orphan) 이미지** — `validation_Agriculture_26`, `validation_Materials_15`,
   `validation_Pharmacy_4`, `validation_Pharmacy_22`는 참조되지 않는 이미지를 들고 있습니다.
   **참조된 이미지만** 넣어야 합니다. 넣으면 토큰 수가 바뀌고 답이 바뀔 수 있습니다 (FACTS 4a).
4. **`options` 파싱** — `options`와 `img_type`은 **JSON이 아니라 Python repr 문자열**입니다.
   `json.loads`는 예외를 던집니다. `ast.literal_eval`을 써야 합니다 (FACTS 4).
5. **보기 개수 하드코딩** — MC 정답은 **A..I(최대 9개)** 범위입니다. 847개 MC 중 **241개는 보기가 4개가
   아닙니다**(2,3,5,6,7,9개). `['A','B','C','D']`를 하드코딩하면 안 됩니다 (FACTS 4).
6. **open-ended 정답** — 3개는 **리스트를 문자열로 저장**한 형태입니다
   (`validation_Chemistry_30`, `validation_Geography_4`, `validation_Math_15`).
   `ast.literal_eval`이 필요합니다. 또 4개는 정답이 한 글자(`C`,`B`,`A`,`A`)여서 MC처럼 보입니다 (FACTS 4c).
7. **파서의 랜덤 폴백** — `**C**`, `C) $8`, `c`, `` (빈 문자열)은 실측으로 랜덤 추측으로 빠집니다.
   마크다운 굵게 표시가 조용히 랜덤 추측이 됩니다. 또 보기 본문 매칭 패스는 응답 길이 > 5 토큰일 때만
   동작하므로 `The correct option is $8`(정확히 5토큰)도 랜덤 추측이 됩니다 (FACTS 4c).
   **`n_unparseable`이 올라갔다면 점수보다 먼저 이 값을 의심하십시오.**
8. **집계 방식** — 6개 카테고리 정확도의 단순 평균과 Overall은 다릅니다. micro(샘플 가중)인지 확인하십시오 (FACTS 4b).

---

## 6. 체크리스트 (복사해서 쓰십시오)

### 6.1 실행 전 (Pre-run)

```
[ ] 1.2절 합의 표의 빈칸이 전부 채워져 커밋되어 있다
[ ] RunPod에서 CUDA version 필터를 합의값(예: 12.8)으로 걸고 Pod를 생성했다   (FACTS 8)
[ ] GPU 모델이 합의값과 같다            : nvidia-smi --query-gpu=name,memory.total --format=csv
[ ] 세 CUDA 값을 눈으로 확인했다        : nvidia-smi 헤더 / nvcc --version(없어도 정상) /
                                          python -c "import torch;print(torch.version.cuda)"
[ ] HF 환경변수를 python 실행 "전에" export했다 (import 시점에 읽힙니다)      (FACTS 5)
        export HF_HOME=/workspace/hf  HF_HUB_CACHE=/workspace/hf/hub
        export HF_XET_HIGH_PERFORMANCE=1     # HF_HUB_ENABLE_HF_TRANSFER 는 폐기됨
[ ] export CONTAINER_IMAGE="<RunPod 템플릿의 이미지 문자열>"                  (FACTS 8)
[ ] bash scripts/setup_pod.sh 로 Stack A를 설치했다 (torch를 cu128 인덱스에서 먼저)
[ ] 설치 후 pip install -U 를 단 한 번도 실행하지 않았다                       (FACTS 5)
[ ] flash-attn 을 설치하지 않았다 (sdist만 존재, 30~60분 컴파일)               (FACTS 5)
[ ] bash scripts/fetch_data.sh 로 validation parquet만 내려받았다 (전체 3.66 GB → 약 341 MB)
[ ] 모델/데이터셋 revision SHA가 합의값과 같다                                 (FACTS 6)
[ ] git 작업 트리가 깨끗하다             : git status --porcelain  → 출력 없음  (FACTS 12)
[ ] 기준 커밋이 합의값과 같다            : git rev-parse --short HEAD
[ ] 사전 환경 기록을 남겼다              : python -m src.capture_env --out results/$MEMBER/preflight
[ ] 스모크 테스트가 통과했다             : python src/eval_mmmu.py --data-path ... --dry-run --limit 8
[ ] 시작 로그의 해석된 픽셀 예산이 980 / 3920 토큰으로 찍혔다                  (FACTS 1)
[ ] 캐시 예열용 런을 1회 돌리고 "버렸다" (콜드 캐시 시간을 본 런에 섞지 않음)   (FACTS 7)
[ ] 1.3절의 합의된 명령을 그대로 실행한다 (임의로 플래그를 바꾸지 않는다)
```

### 6.2 실행 후 (Post-run)

```
[ ] results/$MEMBER/$RUN_ID 에 8개 파일이 모두 있다
        env.json ENVIRONMENT.md config.json metrics.json timing.json
        predictions.jsonl run.log report.md
[ ] env.json 최상위 키 12개가 전부 있다
        schema_version captured_at_utc hardware driver_cuda os python packages
        model dataset run_config git notes
[ ] env.json: model.revision / dataset.revision 이 "main" 이 아니라 "커밋 SHA" 다   (FACTS 6)
[ ] env.json: git.dirty == false
[ ] env.json: packages.pip_freeze 가 비어 있지 않다
[ ] metrics.json: overall.n == 900  (필터가 걸리지 않았다)
[ ] metrics.json: multiple_choice.n == 847, open_ended.n == 53                      (FACTS 4)
[ ] metrics.json: n_unparseable 을 확인하고 기록했다 (급증했다면 5.4절 7번)
[ ] metrics.json: aggregation == "micro / sample-weighted"
[ ] timing.json: model_load_s 가 total_wall_s 와 분리되어 있다                       (FACTS 7)
[ ] run.log 에서 경고를 읽었다 (특히 hf 백엔드의 presence_penalty 미적용 경고)        (FACTS 2)
[ ] 보고서를 생성했다 : python src/report.py --run-dir results/$MEMBER/$RUN_ID \
                                            --out results/$MEMBER/$RUN_ID/report.md
[ ] results/SUMMARY.md 의 표 A / 표 B 에 "자기 행만" 한 줄씩 추가했다
[ ] 커밋 금지 목록(4.3절)에 해당하는 파일이 스테이징되지 않았다 : git status --short
[ ] 자기 GitHub 계정으로 커밋·push 했다
[ ] 팀 폭(최대 - 최소)을 계산해 4.33 pp 와 비교했다. 초과 시 5.3절 절차를 수행했다    (FACTS 7)
[ ] Pod를 "terminate" 했다. stop 만으로는 볼륨 디스크가 계속 과금됩니다
      (Pod는 GPU 사용률과 무관하게 초 단위로 과금되고, 정지된 Pod도 볼륨 $0.20/GB/월)  (FACTS 8)
```

### 6.3 팀 전체 마무리 (팀장)

```
[ ] 4명의 표 B 행에서 gpu / driver_cuda / torch_cuda / 패키지 버전 / revision 이 일치하는지 확인
[ ] 불일치 행에 note 를 달고, 필요하면 재런을 요청
[ ] 통합 보고서 생성:
      python src/report.py --run-dir results/<leader>/$RUN_ID \
        --compare results/<m2>/$RUN_ID results/<m3>/$RUN_ID results/<m4>/$RUN_ID \
        --out assignment/assignment1.md
[ ] assignment/assignment1.md 에 다음이 모두 있는지 확인 (교수님 요구 항목)
      과목별 + 카테고리별 상세 성능 / 전체 성능 / 공개 점수 67.4 대비 비교 /
      평가 코드와 실행 방법 / 실험 환경과 설정(HW + 패키지 버전) /
      총 소요시간 + 과목·카테고리별 소요시간 / 성능 분석
[ ] 환경 표가 ENVIRONMENT.md 에서 온 "자동 생성 값"인지 확인 (손으로 적은 표가 섞이지 않았는지)
```

## 실험 환경 및 설정

이 문서는 `src/capture_env.py` 가 평가 실행 시점에 자동으로 생성했습니다. 캡처 시각(UTC) **2026-09-14T16:48:17Z**, 스키마 버전 `1.0.0`.

### 1. 하드웨어

| 항목 | 값 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 4090 |
| GPU 개수 | 1 |
| VRAM 합계 (MiB) | 24564 |
| CPU | AMD EPYC 7542 32-Core Processor |
| 논리 CPU 수 | 64 |
| 시스템 RAM (GiB) | 503.55 |

- GPU 상세: GPU 0: NVIDIA GeForce RTX 4090, 24564 MiB, 드라이버 580.159.04, sm_89 (출처 nvidia-smi)
- CPU 상세: 프로세스에 할당된 논리 CPU 64개 / os.cpu_count() 기준 64개. 컨테이너에서는 두 값이 다를 수 있으며, 할당된 값이 실제 전처리 병렬도를 결정합니다.
- 메모리 상세: 시스템 RAM 503.55 GiB, 컨테이너 메모리 상한 93.13 GiB (cgroup)

### 2. CUDA 및 드라이버 (세 값은 서로 다른 대상입니다)

| 항목 | 값 | 무엇을 뜻하는가 |
| --- | --- | --- |
| nvidia-smi 헤더 CUDA | 13.0 | 드라이버가 지원하는 최대 CUDA 런타임 버전 |
| nvcc --version | 12.8.93 | 컨테이너의 로컬 CUDA 툴킷. 보통 없으며 휠과 무관합니다 |
| torch.version.cuda | 12.8 | 실제로 중요한 값. PyTorch 휠이 빌드된 CUDA |
| NVIDIA 드라이버 | 580.159.04 | CUDA 12.x 는 525 이상, 13.x 는 580 이상 필요 |

> CUDA 버전 세 개는 서로 다른 것을 가리키므로 값이 일치하지 않는 것이 정상입니다(FACTS 9). ① nvidia_smi_cuda = 설치된 드라이버가 지원하는 최대 CUDA 런타임 버전. ② nvcc_version = 컨테이너에 설치된 로컬 CUDA 툴킷 버전이며, 보통 설치되어 있지 않고 미리 빌드된 PyTorch 휠과는 아무 관계가 없습니다(null 이어도 정상). ③ torch_version_cuda = 실제로 중요한 값으로, 사용 중인 PyTorch 휠이 어떤 CUDA 로 빌드되었는지를 나타냅니다. 예컨대 nvidia-smi 가 13.0 인데 torch.version.cuda 가 12.9 인 상태는 '올바른' 상태이며 아무것도 고칠 필요가 없습니다. CUDA 12.x 는 드라이버 525 이상, 13.x 는 580 이상만 요구합니다. 이 항목을 맞추려고 드라이버나 툴킷을 재설치하며 시간을 쓰지 마십시오.

- torch 상세: torch 2.8.0+cu128, torch.version.cuda=12.8, cudnn=91002, cuda.is_available()=True

### 3. 운영체제 및 컨테이너

| 항목 | 값 |
| --- | --- |
| OS | Ubuntu 24.04.3 LTS |
| OS ID / 버전 | ubuntu / 24.04 |
| 커널 릴리스 | 6.8.0-134-generic |
| 커널 버전 | #134~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC Tue Jun 30 14:05:04 UTC |
| 아키텍처 | x86_64 |
| libc | glibc 2.39 |
| 호스트명 | a2347273df5e |
| 컨테이너 내부 여부 | 예 |
| 컨테이너 근거 | /.dockerenv 파일이 존재합니다 (Docker)<br>PID 1 cgroup 에 docker 문자열이 있습니다<br>RUNPOD_POD_ID 환경 변수가 설정되어 있습니다 (RunPod 파드) |
| 이미지 태그 | — |
| 이미지 다이제스트 | — |

> 컨테이너 이미지 다이제스트는 컨테이너 내부에서 읽을 수 없습니다(FACTS 8). RepoDigests 는 Docker 데몬 메타데이터에 있고 로컬 image ID 는 전혀 다른 해시입니다. 따라서 image_digest 는 구조적으로 null 이며, 정확히 남기려면 RunPod 템플릿에서 이미지 태그를 환경 변수로 주입한 뒤 레지스트리에 HEAD 요청을 보내 다이제스트를 확인해야 합니다.

**RunPod 파드 정보** (공개 저장소에 커밋되므로 공인 IP·포트·API 키는 수집하지 않습니다)

| 항목 | 값 |
| --- | --- |
| Pod ID | p0vdltcdw4o654 |
| Pod 호스트명 | p0vdltcdw4o654-6441156a |
| 데이터센터 | EUR-IS-2 |
| GPU 개수(환경 변수) | 1 |
| CPU 개수(환경 변수) | 12 |
| 메모리 GB(환경 변수) | 100 |
| 네트워크 볼륨 ID | — |
| 네트워크 볼륨 경로 | — |

**결과에 영향을 주는 환경 변수**

| 이름 | 값 |
| --- | --- |
| CUDA_VERSION | 12.8.1 |
| HF_DATASETS_CACHE | /workspace/.cache/huggingface//datasets |
| HF_HOME | /workspace/.cache/huggingface/ |
| HF_HUB_CACHE | /workspace/.cache/huggingface//hub |
| HF_XET_HIGH_PERFORMANCE | 1 |
| LD_LIBRARY_PATH | /usr/local/cuda/lib64 |
| NVIDIA_DRIVER_CAPABILITIES | compute,utility |
| NVIDIA_VISIBLE_DEVICES | void |
| TOKENIZERS_PARALLELISM | <비밀값이므로 기록하지 않음> |
| TZ | Etc/UTC |
| VLLM_ENABLE_V1_MULTIPROCESSING | 0 |

### 4. Python

| 항목 | 값 |
| --- | --- |
| 버전 | 3.12.3 |
| 구현 | CPython |
| 전체 버전 문자열 | 3.12.3 (main, Aug 14 2025, 17:47:21) [GCC 13.3.0] |
| 실행 파일 | /workspace/venv/bin/python |
| prefix | /workspace/venv |
| 가상환경 여부 | 예 |
| 컴파일러 | GCC 13.3.0 |

### 5. 핵심 패키지 버전

| 패키지 | 버전 |
| --- | --- |
| torch | 2.8.0+cu128 |
| torchvision | 0.23.0+cu128 |
| transformers | 4.57.1 |
| tokenizers | 0.22.2 |
| huggingface-hub | 0.35.3 |
| accelerate | 1.11.0 |
| safetensors | 0.6.2 |
| vllm | 0.11.0 |
| datasets | 4.0.0 |
| pillow | 11.3.0 |
| numpy | 2.2.6 |
| qwen-vl-utils | — |
| flash-attn | — |

- 스택 판정: STACK A (FACTS 5 권장: vllm 0.11.0 + transformers 4.57.1, 공개 점수 67.4 발표 시점과 릴리스가 맞는 조합)
- 전체 목록 출처: pip freeze, 총 156개 패키지

<details><summary>설치된 전체 패키지 목록 (156개)</summary>

```text
accelerate==1.11.0
agent-detector==2.0.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.3
aiosignal==1.4.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
astor==0.8.1
attrs==26.1.0
blake3==1.0.9
cachetools==7.1.8
cbor2==6.1.4
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
click==8.5.0
cloudpickle==3.1.2
compressed-tensors==0.11.0
cuda-pathfinder==1.8.1
cupy-cuda12x==14.2.0
datasets==4.0.0
depyf==0.19.0
detect-installer==0.2.1
dill==0.3.8
diskcache==5.6.3
dnspython==2.8.0
einops==0.8.2
email-validator==2.3.0
fastapi==0.141.1
fastapi-cli==0.0.32
fastapi-cloud-cli==0.26.0
fastar==0.12.0
filelock==3.32.3
frozendict==2.4.7
frozenlist==1.8.0
fsspec==2025.3.0
gguf==0.19.0
h11==0.16.0
hf-xet==1.6.0
httpcore==1.0.9
httpcore2==2.13.0
httptools==0.8.0
httpx==0.28.1
httpx2==2.13.0
huggingface-hub==0.35.3
idna==3.19
interegular==0.3.3
Jinja2==3.1.6
jiter==0.17.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
lark==1.2.2
llguidance==0.7.30
llvmlite==0.44.0
lm-format-enforcer==0.11.3
markdown-it-py==4.2.0
MarkupSafe==3.0.3
mdurl==0.1.2
mistral_common==1.11.7
mpmath==1.3.0
msgpack==1.2.2
msgspec==0.21.1
multidict==6.8.0
multiprocess==0.70.16
networkx==3.6.1
ninja==1.13.2
numba==0.61.2
numpy==2.2.6
nvidia-cublas-cu12==12.8.4.1
nvidia-cuda-cupti-cu12==12.8.90
nvidia-cuda-nvrtc-cu12==12.8.93
nvidia-cuda-runtime-cu12==12.8.90
nvidia-cudnn-cu12==9.10.2.21
nvidia-cufft-cu12==11.3.3.83
nvidia-cufile-cu12==1.13.1.3
nvidia-curand-cu12==10.3.9.90
nvidia-cusolver-cu12==11.7.3.90
nvidia-cusparse-cu12==12.5.8.93
nvidia-cusparselt-cu12==0.7.1
nvidia-nccl-cu12==2.27.3
nvidia-nvjitlink-cu12==12.8.93
nvidia-nvtx-cu12==12.8.90
openai==3.13.0
openai-harmony==0.0.8
opencv-python-headless==5.0.0.93
outlines_core==0.2.11
packaging==26.3
pandas==3.0.5
partial-json-parser==0.2.1.1.post7
pillow==11.3.0
prometheus-fastapi-instrumentator==8.1.0
prometheus_client==0.26.0
propcache==0.5.2
protobuf==7.36.1
psutil==7.2.2
py-cpuinfo==9.0.0
pyarrow==25.0.1
pybase64==1.5.0
pycountry==26.2.16
pycparser==3.0
pydantic==2.13.5
pydantic-extra-types==2.11.1
pydantic-settings==2.15.0
pydantic_core==2.46.5
Pygments==2.21.0
python-dateutil==2.9.0.post0
python-dotenv==1.2.3
python-json-logger==4.2.0
python-multipart==0.0.32
PyYAML==6.0.3
pyzmq==27.2.0
ray==2.58.0
referencing==0.37.0
regex==2026.9.10
requests==2.34.2
rich==15.0.0
rich-toolkit==0.20.5
rignore==0.8.1
rpds-py==2026.6.3
safetensors==0.6.2
scipy==1.18.1
sentencepiece==0.2.2
sentry-sdk==2.69.1
setproctitle==1.3.7
setuptools==79.0.1
shellingham==1.5.4
six==1.17.0
sniffio==1.3.1
soundfile==0.14.0
soxr==1.1.0
starlette==1.6.0
sympy==1.14.0
tiktoken==0.14.0
tokenizers==0.22.2
torch==2.8.0+cu128
torchaudio==2.8.0+cu128
torchvision==0.23.0+cu128
tqdm==4.70.1
transformers==4.57.1
triton==3.4.0
truststore==0.10.4
typer==0.27.2
typing-inspection==0.4.4
typing_extensions==4.16.0
urllib3==2.7.0
uvicorn==0.53.0
uvloop==0.22.1
vllm==0.11.0
watchfiles==1.2.0
websockets==17.1
wheel==0.48.0
xformers==0.0.32.post1
xgrammar==0.1.25
xxhash==4.0.1
yarl==1.24.5
```

</details>

### 6. 모델 및 데이터셋 (리비전 고정)

| 항목 | 값 |
| --- | --- |
| 모델 repo_id | Qwen/Qwen3-VL-4B-Instruct |
| 모델 리비전 (커밋 SHA) | ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| 모델 로컬 경로 | /workspace/.cache/huggingface/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| dtype | bfloat16 |
| attn_implementation | vllm 내부 백엔드 (transformers attn_implementation 미적용) |
| 데이터셋 | MMMU/MMMU |
| 데이터셋 리비전 (커밋 SHA) | 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 |
| split | validation |
| 샘플 수 | 30 |

> model.revision 과 dataset.revision 은 'main' 같은 가변 포인터가 아니라 해석된 40자 커밋 SHA 여야 합니다(FACTS 6). MMMU/MMMU 의 데이터 파일은 공개 점수 67.4 가 발표된 이후에도 2026-02-12, 2026-04-21, 2026-07-10 에 변경되었으므로 'MMMU/MMMU' 라는 이름만으로는 재현이 불가능합니다. vLLM 을 쓸 때는 tokenizer_revision 도 따로 고정해야 합니다(기본값 None 이면 main 을 따라갑니다).

- 모델 리비전 해석: 요청 'ebb281ec70b05090aa6165b016eac8ec08e71b17' -> 확정 'ebb281ec70b05090aa6165b016eac8ec08e71b17' (해석 경로: 인자로 받은 값이 이미 커밋 SHA)

- 데이터셋 리비전 해석: 요청 '98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68' -> 확정 '98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68' (해석 경로: 인자로 받은 값이 이미 커밋 SHA)

### 7. 실행 설정 (run_config)

| 설정 | 값 |
| --- | --- |
| aggregation | micro / sample-weighted |
| backend | vllm |
| context | `max_model_len` = 9048<br>`max_new_tokens` = 2048<br>`limit_mm_per_prompt` = `image` = 5<br>`video` = 0<br>`allow_output_squeeze` = 아니오 |
| data_path | MMMU/MMMU |
| determinism | `seed` = 3407<br>`parser_seed` = 42<br>`sample_order` = load_mmmu 의 (SUBJECTS 인덱스, id 의 문항 번호) 정렬<br>`vllm_enable_v1_multiprocessing` = 0<br>`full_determinism` = 아니오<br>`note` = FACTS 7: enable_full_determinism() 은 CUDA_LAUNCH_BLOCKING=1 을 켜서 소요 시간 측정을 무의미하게 만들므로 사용하지 않았습니다. |
| engine | `gpu_memory_utilization` = 0.9<br>`max_num_seqs` = 32<br>`enforce_eager` = 아니오<br>`attn_implementation` = vllm 내부 선택 |
| limit | 30 |
| metrics_accuracy_scale | fraction_0_1 (백분율로 쓰려면 100을 곱하십시오) |
| out_dir | /workspace/MMDL/outputs/smoke-anchored-limit30 |
| pixel_budget | `min_pixels_spec` = 1280*28*28<br>`max_pixels_spec` = 5120*28*28<br>`min_pixels` = 1003520<br>`max_pixels` = 4014080<br>`min_vision_tokens_per_image` = 980<br>`max_vision_tokens_per_image` = 3920<br>`smart_resize_factor` = 32<br>`pixels_per_vision_token` = 1024<br>`processor_size_requested` = `shortest_edge` = 1003520<br>`longest_edge` = 4014080<br>`processor_size_resolved` = `shortest_edge` = 1003520<br>`longest_edge` = 4014080<br>`processor_size_forced` = 아니오<br>`precount_min_pixels` = 1003520<br>`precount_max_pixels` = 4014080<br>`note` = Qwen3-VL 은 patch_size 16 * spatial_merge_size 2 = 32 그리드이므로 visual token 1개가 32x32=1024 px 를 덮습니다. 교수님 슬라이드의 '*28*28' 은 Qwen2.5-VL 관례이며 Qwen3-VL 에서는 토큰 수를 뜻하지 않습니다. |
| presence_penalty_mechanism | `requested` = 1.5<br>`applied` = 예<br>`mechanism` = vllm.SamplingParams.presence_penalty (네이티브, 가산형)<br>`note` = vLLM 공식 구현. logits -= penalty * (생성된 토큰 여부), prompt 제외, 횟수 무시. |
| sampling | `temperature` = 0.7<br>`top_p` = 0.8<br>`top_k` = 20<br>`repetition_penalty` = 1.0<br>`presence_penalty` = 1.5<br>`max_new_tokens` = 2048<br>`seed` = 3407<br>`note` = temperature>0 이므로 표본 추출이 확률적입니다. FACTS 7: n=900, p=0.674 에서 서로 독립인 두 실행의 차이에 대한 95% 구간은 ±4.33pp 이므로 팀원 간 1~2pp 차이는 잡음입니다. |
| split | validation |
| subjects_filter | — |
| template | anchored |
| timing_note | total_wall_s 는 이번 프로세스 wall clock + 이어받은 추론 시간입니다. model_load_s 는 별도로 측정하여 알파벳순 첫 과목에 엔진 시작 비용이 섞이지 않게 했습니다. |

### 8. Git 상태

| 항목 | 값 |
| --- | --- |
| 커밋 | — |
| 브랜치 | — |
| 변경 사항 있음(dirty) | — |

### 9. 팀 비교 시 알아야 할 점

> temperature=0.7 / top_p=0.8 / top_k=20 은 확률적 샘플링이므로 실행은 비트 단위로 재현되지 않고 팀원 4명의 점수는 서로 다릅니다(FACTS 7). n=900, p=0.674 에서 한 문제는 0.111pp, 표준오차는 1.56pp, 독립 실행 두 번의 차이에 대한 95% 구간은 ±4.33pp 입니다. 즉 1~2pp 차이는 버그가 아니라 노이즈입니다. 원인을 확인하려면 예측을 diff 하십시오(샘플링 노이즈는 원문 차이가 많고 라벨 변화가 적으며, 파서/정답키 버그는 원문 차이가 적은데 점수 차이가 큽니다). 또한 타이밍 표를 위해 transformers.enable_full_determinism() 은 쓰지 마십시오(CUDA_LAUNCH_BLOCKING=1 때문에 경과 시간이 무의미해집니다).

> RunPod 의 머신은 호스트마다 NVIDIA 드라이버가 다릅니다(FACTS 8). 파드를 고를 때 UI 의 Filters > CUDA version(또는 GraphQL 의 allowedCudaVersions)으로 드라이버 CUDA 를 고정해 팀원 4명이 같은 드라이버를 받도록 하십시오. 드라이버가 다르면 커널 경로가 달라져 설명할 수 없는 정확도 차이가 생깁니다.

팀원끼리 스택이 같은지 확인하려면 서로의 `env.json` 을 주고받아 다음을 실행하십시오: `python -m src.capture_env --check <상대방_env.json>`

### 10. 경고

- /workspace/MMDL 가 git 저장소가 아니어서 커밋을 기록할 수 없습니다. 제출용 실행은 반드시 커밋된 상태에서 해야 합니다(FACTS 12).

### 11. 수집하지 못한 항목과 이유

값이 null 인 항목은 모두 아래에 이유가 남습니다. (nvcc 처럼 없는 것이 정상인 항목도 포함됩니다.)

| 항목 | 이유 |
| --- | --- |
| git.repo | 탐지에 실패했습니다 (RuntimeError: `git rev-parse --is-inside-work-tree` 가 종료 코드 128 로 실패했습니다: fatal: not a git repository (or any parent up to mount point /) Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).) |
| os.container.image_digest | FACTS 8: 컨테이너 안에서는 자신의 이미지 다이제스트를 읽을 수 없습니다(RepoDigests 는 Docker 데몬 메타데이터이고 로컬 image ID 는 다른 해시입니다). 구조적으로 null 입니다. |
| os.container.image_tag | 컨테이너 이미지 태그를 알려 주는 환경 변수가 없습니다. RunPod 템플릿의 환경 변수에 RUNPOD_IMAGE_NAME 을 추가하면 자동으로 기록됩니다(FACTS 8). |
| packages.flash-attn | 설치되어 있지 않습니다. FACTS 5 기준으로 이는 정상이며 의도된 상태입니다(flash-attn 은 sdist 전용이라 긴 컴파일이 필요하고, Qwen3VL 은 _supports_sdpa=True 이므로 attn_implementation="sdpa" 로 충분합니다). |
| packages.qwen-vl-utils | 설치되어 있지 않습니다. FACTS 5 기준으로 이미지 전용 MMMU 베이스라인에는 필요하지 않은 선택 패키지입니다. |

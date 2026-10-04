# Baseline seed robustness (추가 실험) — v2, 중복 제거판

> **상태: 과제 제출 이후의 추가 실험. `main`에는 병합하지 않는다.** 제안발표(10/6~7)에서 "추가 실험"으로 언급하는 용도.
> 질문: **제출 baseline 66.67% (600/900, sampling seed 3407)는 운 좋은 한 번의 추출이었나?**

모든 파일은 **신규 파일**이다. 기존 파일(`code/`, `results/mmmu_team_baseline/`, `assignment/`)은 수정하지 않으며,
`run_all.sh`는 실행 전에 `code/` 해시를 검사해 생성 코드가 baseline과 같음을 강제한다.

| 파일 | 역할 |
|---|---|
| `make_seed_config.py` | `code/config.yaml`에서 **seed 두 줄만** 바꾼 config 생성 + 변경 키가 seed뿐임을 diff로 검증 |
| `run_all.sh` | **GPU Pod 전용, 생성만 수행.** arm 순차 실행, arm별 소요시간·ETA 출력. 이어받기 금지 |
| `score_runs.sh` | **Pod 밖(CPU)에서 채점.** arm마다 독립 실행, 기존 3개 실행 재채점 옵션 포함 |
| `retry_failed_judge.py` | Judge 일시 오류 후 미해결 요청만 정리하는 복구 도구 (dry-run 기본, 백업·기록 남김) |
| `pack_runs.py` | raw(≈15MB)를 gzip(≈3MB)하고 문항별 결과만 추려 커밋 가능한 크기로 축소 |
| `analyze.py` | 의존성 없는 집계·검정, 사전 등록된 trigger 판정 → `REPORT.md`, `summary.json` |
| `CODE_FREEZE.sha256` | `code/`(tests 제외) 해시. 기준 main 커밋 `016b3cf` |

---

## 1. 브랜치 분리 (main 보호)

```bash
git checkout main && git pull --ff-only
git tag pre-seed-robustness                    # 로컬 태그만. 분기 지점 표시용 (push 금지)
git checkout -b exp/baseline-seed-robustness   # README Branch Naming 규칙: <type>/<short-description>
```

이 브랜치에서 추가되는 경로는 아래 세 곳뿐이다. 그 밖의 변경이 보이면 실수다.

```
experiments/baseline_seed_robustness/      # 스크립트·문서 (이 폴더)
results/baseline_seed_robustness/          # 실행 결과 (arm별 하위 폴더 + analysis/)
reports/baseline_seed_robustness.md        # 발표용 정리 (분석 후 작성)
```

커밋 메시지: 스크립트 `exp(seed): ...`, 결과 `eval(seed): ...`.

**main push 차단 훅 (로컬, 커밋되지 않음)**

```bash
cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env bash
while read -r local_ref local_sha remote_ref remote_sha; do
  if [[ "$remote_ref" == "refs/heads/main" ]]; then echo "BLOCKED: push to main is disabled for the seed-robustness work." >&2; exit 1; fi
done
EOF
chmod +x .git/hooks/pre-push
```

RunPod에서 이 브랜치를 clone해야 하므로 실행 전에 `git push -u origin exp/baseline-seed-robustness`를 한 번 한다.
합칠 때는 `main`에 직접 병합하지 말고 PR로 올려 diff가 위 세 경로뿐인지 확인한다(기존 파일 수정이 없어 충돌 없음).

---

## 2. 현재 설정된 seed 전수 조사

| # | seed | 값 | 위치 | 역할 | 재현성 영향 |
|---|---|---|---|---|---|
| 1 | SamplingParams seed | 3407 | `sampling.seed` → `SamplingParams(seed=…)` | 900개 요청 각각의 난수 생성기 시작점 (temperature 0.7 샘플링) | **직접·핵심** |
| 2 | LLM(engine) seed | 3407 | `sampling.engine_seed` → `LLM(seed=…)` | 엔진 전역 RNG 초기화 | 영향 없을 것으로 **추정(미검증)**. 요청마다 seed가 있으면 전역 RNG를 거의 쓰지 않는다는 추론 |
| 3 | Judge seed | 3407 | `scoring.judge.seed` (gpt-4.1-mini, temp 0) | 규칙으로 답을 못 뽑은 약 345문항 판정 | 생성과 무관한 **채점 잡음**. API seed는 best-effort |
| 4 | MMMU 파서 `random.seed(42)` | 42 | `code/scoring/frozen/vendor/mmmu_eval.py` | 파싱 실패 시 무작위 선택 | **사용되지 않음** (`parsers.py`가 `random.choice` 차단) |
| – | (seed 아님) 배치·호스트·드라이버·라이브러리 | – | `chunk_size 150`, `first_chunk_size 16`, `max_num_seqs 256`, vLLM 0.11.0 등 | bf16 연산 순서가 배치 모양·환경에 따라 달라질 수 있음 | **같은 seed여도 bit 단위 재현은 보장되지 않음** |

`sampling.seed`는 config 주석상 "team addition"이고, 3407은 Qwen README의 Instruct 평가 seed(`engine_seed`)를 따른 값이다.
draft 단계에서 seed를 바꿔 본 적이 있다면 발표에서 함께 밝힌다.

---

## 3. 고정 / 실험 / 제외

| 구분 | 항목 | 값 |
|---|---|---|
| **고정** | Judge seed·모델·설정, `engine_seed`, 파서 seed, 모델·데이터 revision, 프롬프트, temperature/top_p/top_k/penalty, `max_new_tokens 8192`, `max_model_len 16384`, 이미지 해상도, 엔진·배치 설정, GPU 종류, 라이브러리 | baseline 그대로 (`code/` 해시 검사 + `make_seed_config.py` diff 검증) |
| **변경(실험 변수)** | `sampling.seed` **하나만** | 아래 arm |

### 3.1 선행 증거 (이 증거 때문에 일부 실험을 뺐다)

| 증거 | 내용 | 한계 |
|---|---|---|
| 같은 seed(3407/3407)로 8192 전량 실행 **3회** (draft, new_output, final) | 설정·프롬프트·입력 토큰 수 동일. length 종료 108/114/128. 규칙 단독 정확도 450/461/452 (sd≈0.65pp). 생성 텍스트가 완전히 같은 문항은 12~14%뿐, 처음 갈라지는 토큰 위치 중앙값 ≈80 | 호스트·드라이버·코드 커밋이 서로 다름. 규칙 단독 점수라 제출 hybrid 점수와 직접 비교 불가. 원인 미규명 |
| `assignment/archive/hakyung/experiments/expF_seed_repro` | seed 42/3407/1234, **max_new_tokens 2048**, 정확도 417/415/423 (sd≈0.4pp), 쌍별 McNemar 전부 비유의 | 예산·파서·채점 다름. **engine_seed와 sampling seed를 함께** 변경. archive "참조 금지". 효과 크기의 사전 참고치로만 사용 |

### 3.2 arm 구성

| Tier | arm | sampling.seed | engine_seed | 실행 조건 |
|---|---|---|---|---|
| **1 (필수)** | `seed_42` | 42 | 3407 | 항상 |
| **1 (필수)** | `seed_1234` | 1234 | 3407 | 항상 (예전 expF에서 쓴 값. 순위가 8192에서도 유지되는지가 부수 정보) |
| **1 (필수)** | `seed_2026` | 2026 | 3407 | 항상 (새 값) |
| 2 (조건부) | `seed_777`, `seed_31337` | 777, 31337 | 3407 | §4의 Tier-2 trigger 발동 시 |
| 3 (조건부) | `ctrl_repeat` | 3407 | 3407 | §4의 Tier-3 trigger 발동 시 (이 Pod와 같은 환경의 반복) |
| GPU 없음 | `rep_draft`, `rep_new_output` | – | – | 기존 두 실행을 Judge로 hybrid 채점 (arm당 약 $0.5, 약 9분). 제출 점수와 같은 척도의 반복 편차 |
| GPU 없음 | `rescore_baseline` | – | – | 제출 raw를 새 Judge 호출로 재채점 (약 $0.5, 약 9분) → Judge 잡음 크기 |

**제거한 실험과 이유**
- **`ctrl_engine`(engine_seed만 변경)**: 같은 설정 반복에서도 출력이 이미 대부분 달라진다(위 증거). 이 상태에서는 engine seed 효과를 탐지할 수 없다. 탐지하려면 같은 seed 두 번이 bit까지 일치하는 환경이 먼저 필요하다. expF도 두 seed를 함께 바꿨기 때문에 대체 증거가 아니다. → README에서는 "추정(미검증)"으로만 기록.
- **`VLLM_BATCH_INVARIANT` 보조 arm**: 목적(통계적 재현성)에 불필요하고, vLLM 0.11.0·멀티모달 지원이 확인되지 않음.
- **기본 `ctrl_repeat`**: 같은 seed 반복이 이미 2회 더 있다. 호스트 효과를 분리해야 할 때만(Tier 3) 실행.
- **Pod 위 Judge 채점**: Judge 호출이 순차(문항당 1회, 약 345회)라 GPU가 놀면서 과금된다. 채점은 Pod를 끈 뒤 로컬에서 한다. API 키도 Pod에 둘 필요가 없다.

---

## 4. 사전 판정 기준 (결과를 보기 전에 확정)

예측구간(PI)은 **다른 seed들만으로** 계산한다 (`analyze.py` 구현 그대로). k는 seed arm 수.

| 판정 | 조건 |
|---|---|
| **Tier 2 실행** (k<5일 때) | 다음 중 하나라도 만족: ① baseline이 95% PI 밖 ② \|z\| > 1.5 ③ seed 간 sd > 1.0pp |
| **Tier 3 실행** | baseline이 95% PI 밖이고 `ctrl_repeat`가 아직 없음 (seed 효과와 호스트 효과를 분리하기 위함) |
| 운이 좋은 쪽이었다고 보고 | baseline이 PI 밖이면서 다른 seed 전부보다 높음 |

임계값(1.5, 1.0pp)은 expF(sd≈0.4~0.5pp)와 8192 반복(sd≈0.65pp)을 근거로 잡은 값이며, 다른 설정(2048, 자체 파서)에서 가져온 값이므로 참고치다. 실행 후에 바꾸지 않는다.

**해석 규칙**
1. McNemar p는 보조 지표다. 맞힘/틀림이 양방향으로 상쇄되면 문항이 많이 뒤집혀도 p는 유의하지 않게 나온다. **"유의하지 않다"는 "같다"의 증거가 아니므로** 쌍체 차이의 95% CI 폭을 함께 읽는다.
2. seed arm의 평균 flip%와 same-seed repeat의 flip%를 비교한다. 비슷하면 "seed 변경은 같은 걸 다시 돌리는 것보다 특별히 더 큰 변동을 만들지 않는다 → 수치 잡음이 지배적"이다.
3. `rescore_baseline`의 flip은 Judge 잡음이다. 600이 아니면 그 차이가 Judge 비결정성의 크기이며, seed 효과 해석에서 그만큼 빼고 본다.
4. `rep_*`의 호스트·드라이버가 다르므로 "환경 통제 반복"이 아니다. 환경 통제는 Tier 3의 `ctrl_repeat`만 해당.

---

## 5. 소요시간 (GPU 과금 시간)

**근거**: 같은 설정의 기존 3회 생성 시간이 3,351 / 4,896 / 6,026초(호스트에 따라 최대 1.8배). arm당 오버헤드는 생성 코드 내부(모델 로드·vLLM 초기화) **실측 2~3분(118/183/142초)** + 환경 게이트 **미측정(1~2분으로 가정)** → 표에서는 3분을 썼고 ±2분 오차가 있다. 최초 1회 설치(pip + 모델 약 9GB + 데이터셋)는 **15~30분으로 가정(미측정)**, Pod에 이미 있으면 0. Judge 채점은 Pod 밖이므로 GPU 시간에 포함하지 않는다.

| 호스트 속도 | arm당 | **Tier 1 (3 arm, 필수)** | +Tier 2 (2 arm) | +Tier 3 (1 arm) | 전부 (6 arm) | (참고) 이전 계획 7 arm* |
|---|---|---|---|---|---|---|
| 빠름 (56분) | 59분 | **3.0시간** | +2.0시간 | +1.0시간 | 5.9시간 | 8.1시간 |
| 중간 (82분) | 85분 | **4.2시간** | +2.8시간 | +1.4시간 | 8.5시간 | 11.1시간 |
| 느림 (100분) | 103분 | **5.2시간** | +3.4시간 | +1.7시간 | 10.3시간 | 13.2시간 |

\* 이전 계획 = 7 arm + Pod 위 Judge 채점(arm당 10분으로 가정).
최초 설치 시간(0.25~0.5시간)은 위 표에 포함되지 않았다.
**일반적인 경우(Tier 1만)의 절감은 약 5~8시간**이다.

**비용** = 위 시간 × 그 Pod의 시간당 요금 (요금은 RunPod 콘솔에서 확인).
**Pod 밖 로컬 채점 (실측 기반)**: 기존 baseline Judge 기록에서 363회 호출이 556초(호출당 약 1.5초, 순차)였고 입력 138만 토큰, 레포의 추정 비용은 gpt-4.1-mini 기준 **$0.55**였다. 따라서 arm당 **약 9분, 약 $0.5**(응답 길이에 따라 달라짐). 기본 6건(기존 3 + Tier 1의 3) ≈ **$3, 순차 약 54분**, GPU 비용은 없다. 기존 3건은 Pod 생성 시간과 겹쳐서 미리 끝낼 수 있다.

**첫 arm이 끝나면 `run_all.sh`가 출력하는 `arm=… min | ETA …`로 위 표의 어느 행인지 확정**한다. 그 값이 예산을 넘으면 그 시점에서 멈춘다(이어받기 없는 설계라 완료된 arm은 유효).

---

## 6. RunPod 실행 — `git clone` 직후부터 (생성만, 요금 최소화)

**원칙**
- 요금은 Pod를 stop/terminate할 때까지 계속 나간다. GPU가 필요한 일은 **생성뿐**이다. 채점·분석·커밋은 전부 로컬에서 한다.
- **Pod에는 OpenAI API 키를 두지 않는다.** 필요 없다 (§7).
- 템플릿은 **Ubuntu 24.04 기반**, **On-Demand**(Spot은 중간에 회수될 수 있음)로 만든다.

### A. 사전 점검 (1~2분, 하나라도 실패하면 바로 교체/종료)

```bash
cd /workspace/MMDL
git rev-parse --abbrev-ref HEAD                 # exp/baseline-seed-robustness
git status --short | head -3                    # 비어 있어야 함
python --version                                # 정확히 Python 3.12.3
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader   # RTX 4090 / 24GB급 / 드라이버 570 이상
df -h /workspace | tail -1                      # 여유 40GB 이상 (게이트 하한 20GB)
command -v tmux runpodctl; echo "POD_ID=${RUNPOD_POD_ID:-unset}"
python experiments/baseline_seed_robustness/make_seed_config.py --out /tmp/c.yaml --sampling-seed 42 --engine-seed 3407 && cat /tmp/c.diff.json
```

| 결과 | 조치 |
|---|---|
| Python이 3.12.3이 아님 | 환경 게이트(`expected_version`)가 치명 실패로 처리해 설치 후에 중단된다. **지금 Pod를 종료**하고 Ubuntu 24.04 계열 템플릿으로 다시 만든다 (baseline은 glibc 2.39 환경). 게이트 우회 옵션은 코드에 "local rehearsal only"로 적혀 있으니 쓰지 않는다. |
| 드라이버 < 570 | CUDA 12.8 패키지 요건(`min_driver_major: 570`) 미달. 다른 호스트로 교체. |
| GPU가 RTX 4090이 아님 | baseline과 비교성이 깨진다. 교체. |
| `tmux` 없음 | `apt-get update && apt-get install -y tmux` (수십 초) |
| `runpodctl`/`POD_ID` 없음 | 자동 정지 안전망을 못 쓴다. 완료 예상 시각에 알람을 맞추고 콘솔에서 직접 정지. |
| `c.diff.json`의 changed에 `sampling.seed` 외 항목이 있음 | 중단하고 알려 주세요. |

### B. 시작 (한 줄, 이후 자리를 비워도 된다)

```bash
tmux new -s seed
export HF_HOME=/workspace/.cache/huggingface
chmod +x experiments/baseline_seed_robustness/*.sh
bash experiments/baseline_seed_robustness/run_all.sh --tier 1 --install --stop_grace_min 30
```

- `--install`: pip 설치 + 모델·데이터셋 다운로드 (**첫 실행에만**).
- `--stop_grace_min 30`: **마지막 arm이 끝나고 30분 뒤 Pod를 자동 정지**하는 안전망이다. 그 전에 끝나면 직접 먼저 정지한다. `runpodctl`이 없으면 "POD WILL NOT STOP" 경고가 크게 출력된다.
- arm 3개가 쉬지 않고 연달아 돈다. 각 arm이 끝나면 즉시 `/workspace/seedexp/pack/`에 묶인다.
- tmux 빠져나오기 `Ctrl+b` → `d`, 다시 붙기 `tmux attach -t seed`.

### C. 처음 15~30분(설치 구간)에 보이는 것

| 단계 | 로그 | 정상 신호 |
|---|---|---|
| pip 설치 | `/workspace/seedexp/seed_42/logs/01_install.log` | 에러 없이 종료 |
| 환경 게이트 | `02_env_check.log` | `Environment gate passed`. `FAIL: packages.expected_version` 등이 나오면 중단 |
| 모델·데이터 다운로드 | `du -sh /workspace/.cache/huggingface` | 용량이 늘어남 |
| 생성 | `03_generate.log` | `chunk 1/7 done=16 seconds=… output_tokens/s=…` |

### D. 속도 판정 (arm 시작 후 10~15분, `chunk 2/7` 이후)

`output_tokens/s`로 arm 소요시간을 예측한다: **시간(분) ≈ 1.8M ÷ (tok/s) ÷ 60**.
기존 3회의 arm 평균 처리량은 약 **540 / 360 / 290 tok/s**(→ 56 / 83 / 103분)였다. chunk 값은 평균보다 흔들린다. chunk 1(16문항)은 작아서 대표값이 아니다.

- 예산 안이면 그대로 둔다.
- 처리량이 ≈320 tok/s 미만이고 예산이 빠듯하면 Pod 교체를 고려할 수 있다. 다만 속도 차이의 원인을 모르고, 새 호스트가 더 빠르다는 보장이 없으며, 재설치 15~30분이 다시 든다.

### E. 로컬 병행 작업 (Pod가 도는 동안, GPU 비용 0) — §7 참조

### F. arm이 끝날 때마다 (선택이지만 권장)

`[packed] … is ready to download`가 보이면 그 arm을 바로 내려받아 로컬에서 채점을 시작한다. 마지막 arm이 끝났을 때 남는 채점은 1건(약 9분)뿐이다.

```bash
tar czf /workspace/pack.tgz -C /workspace/seedexp/pack . && ls -la /workspace/pack.tgz     # 약 10MB 이하
```

내려받기 방법: ① 템플릿에 JupyterLab이 있으면 파일 브라우저에서 `pack.tgz` 우클릭 → Download (가장 간단) ② `runpodctl send /workspace/pack.tgz` 후 로컬에서 출력된 코드로 `runpodctl receive <code>` ③ SSH가 열려 있으면 `scp`.

### G. 마지막 arm 종료 → 판정 → 정지

1. `ALL ARMS FINISHED`가 보이면 마지막 `pack.tgz`를 내려받는다 (약 1분).
2. 로컬에서 마지막 arm만 채점(약 9분) → `analyze.py` → 마지막 줄의 **Pre-registered triggers** 확인.
3. **둘 다 "not needed"** → 즉시 Pod를 **Terminate**한다 (Stop은 디스크 요금이 계속 나갈 수 있음. 요금은 콘솔에서 확인).
4. **Tier 2가 "RUN"** → 같은 tmux에서 `Ctrl+C`로 안전망 타이머를 끊고 곧바로 `bash experiments/baseline_seed_robustness/run_all.sh --tier 2 --stop_grace_min 30` (**재설치 없음**). Tier 3이면 `--tier 3`.
5. 30분 안에 판정을 못 하면 Pod가 자동 정지된다. Tier 2/3이 필요해지면 새로 시작해야 하며(설치 포함 15~30분 재발생 가능, 정지된 Pod가 같은 GPU를 다시 잡는다는 보장도 없음, container 디스크의 pip 패키지가 유지되는지도 미확인) `--install`을 다시 붙인다.

### H. 문제가 생겼을 때

| 증상 | 조치 |
|---|---|
| 게이트 FAIL | 위 A 표. 재시도하지 말고 로그의 `FAIL:` 줄을 알려 주세요 |
| vLLM 초기화 오류·OOM | `tail -20 /workspace/seedexp/<arm>/logs/03_generate.log`와 `logs/FAILED`를 알려 주세요. 맹목적 재시도는 비용만 든다 |
| 터미널 연결 끊김 | tmux라 계속 돈다. `tmux attach -t seed` |
| Pod가 재시작/회수됨 | `python -c "import vllm"`로 설치 확인 후 같은 명령을 다시 실행 (없으면 `--install`). 끝난 arm은 건너뛰고 중단된 arm은 `<arm>.partial.<시각>`으로 치우고 처음부터 다시 돈다 |
| 시작 직후 `ABORT: code/ differs` | `code/`가 baseline과 달라졌다는 뜻. 원인 확인 전에는 진행하지 않는다 |

## 7. 로컬 채점·분석 (GPU 불필요) — API 키는 여기에만

**API 키를 넣는 곳**: **로컬 PC에서 `score_runs.sh`를 실행하는 터미널의 환경변수 `OPENAI_API_KEY`**. Pod, 파일(`.env`, 스크립트, README), git에는 넣지 않는다. 터미널을 새로 열면(병렬 채점 포함) 터미널마다 다시 설정한다.

```bash
# 키 입력 (붙여넣고 Enter. 화면에 안 보이고 히스토리에도 남지 않음)
read -rs OPENAI_API_KEY; export OPENAI_API_KEY
# 키와 모델 접근 확인 (비용 없음). 200이면 정상
curl -s -o /dev/null -w "%{http_code}\n" https://api.openai.com/v1/models/gpt-4.1-mini-2025-04-14 -H "Authorization: Bearer $OPENAI_API_KEY"
```

- `score_runs.sh`는 bash 스크립트다. Windows는 **WSL 또는 Git Bash**에서, **같은 터미널 안에서** `export`한다 (PowerShell 환경변수는 WSL로 넘어가지 않는다).
- 로컬에는 `python3`와 PyYAML이 필요하다 (`pip install pyyaml`).
- `evaluate.py`는 Authorization 헤더를 저장하지 않도록 코드에 명시돼 있고, `pack_runs.py`는 요약 파일만 복사하므로 키가 결과 폴더에 남지 않는다. 그래도 커밋 전에 `git diff --cached | grep -c "sk-"`가 0인지 확인한다.

**로컬 작업 순서 (Pod 대기 시간과 겹쳐서 진행)**

```bash
git checkout exp/baseline-seed-robustness        # 로컬 clone, 레포 루트에서

# (1) Pod 시작 직후: 기존 3건 채점. GPU와 무관하므로 Pod 생성 대기 중에도 돌릴 수 있고,
#     Judge 경로(키·API)가 실제로 동작하는지도 미리 검증된다. 약 27분, 약 $1.5
bash experiments/baseline_seed_robustness/score_runs.sh --include_existing --dest results/baseline_seed_robustness

# (2) arm이 내려올 때마다 (pack.tgz를 풀어서 그 폴더를 --src로). 이미 채점된 arm은 건너뛴다
mkdir -p /tmp/pack_dl && tar xzf pack.tgz -C /tmp/pack_dl
bash experiments/baseline_seed_robustness/score_runs.sh --src /tmp/pack_dl --dest results/baseline_seed_robustness

# (3) 분석 (마지막 줄이 Tier 2/3 판정)
python experiments/baseline_seed_robustness/analyze.py

# (4) 커밋·push (main이 아닌 브랜치)
git add results/baseline_seed_robustness experiments/baseline_seed_robustness
git commit -m "eval(seed): baseline seed robustness runs and analysis"
git push -u origin exp/baseline-seed-robustness
```

- 키 없이 파일 검증만 하려면 `--no_judge`를 붙인다 (오프라인, MMMU 규칙 점수만).
- 실측 기준: Judge 호출은 한 번에 하나씩, 호출당 약 1.5초, arm당 약 345회 ≈ **9분, 약 $0.5**. 터미널을 나눠 병렬로 돌리면 시간이 줄지만 API rate limit은 확인하지 못했다.
- **Judge 호출이 한 번 실패하면 자동 재시도가 없다.** 약 345회 순차 호출 중 한 번만 타임아웃·429·5xx가 나도 `evaluate.py`가 "unresolved attempt"로 막는다. `score_runs.sh`는 실패한 arm만 건너뛰고 나머지를 계속 채점하며, 로그(`<stage>/<arm>/score.log`)를 남기고 복구 명령을 출력한다. 채점 stage 기본 위치는 `~/.cache/seed_scoring_stage`다(`/tmp`는 재부팅 시 지워져 유료 Judge 응답이 사라질 수 있어 쓰지 않는다. `STAGE_DIR`로 변경 가능).
- **복구 (일시적 오류일 때만)**: `python experiments/<이 폴더>/retry_failed_judge.py --scoring_dir <stage>/<arm>/scoring`(dry-run, 미해결 요청 id와 오류 종류만 표시) → 일시적 오류로 판단되면 `--apply`(백업 후 해당 요청의 started/failed 기록만 삭제, `RECOVERY_LOG.txt`에 기록) → `score_runs.sh`를 다시 실행하면 캐시된 응답은 재사용하고 그 요청만 다시 보낸다. 이것은 채점 코드의 "inspect first" 규칙에서 **의도적으로 벗어나는 절차**이므로 보고서에 "일시적 API 오류 N건을 재시도했다"고 적는다. 401/403(키 문제)이나 400(요청 문제)이면 `--apply`하지 말고 원인부터 해결한다.
- 채점되지 않은 항목이 남은 arm은 `analyze.py`가 자동 제외하고 경고한다. 같은 명령을 다시 실행하면 완료된 arm은 건너뛰고 중단된 arm은 `run`부터 이어간다 (캐시된 응답 재사용).

---

## 8. 발표용 문구 가이드

| 관찰 | 말할 수 있는 것 | 말하면 안 되는 것 |
|---|---|---|
| baseline이 PI 안, 평균과 가까움 | "66.67은 우리 설정에서 seed 평균과 일치. seed 변동은 ±x pp" | "seed가 무관하다" (정확도가 같아도 개별 문항은 뒤집힘) |
| baseline이 PI 밖의 최고값 | "운이 좋은 쪽이었다. 이후 비교에는 seed 평균 y%를 baseline으로 쓴다" | – |
| seed flip% ≈ repeat flip% | "seed를 바꾸나 다시 돌리나 문항 단위 변동은 비슷. 수치 잡음이 지배적" | "seed 고정으로 재현된다" |
| `rescore_baseline`이 600이 아님 | "Judge 비결정성이 ±n문항" | – |

**다른 팀 62%와의 비교**: 이 실험이 답하는 것은 "우리 설정에서 seed가 만드는 변동폭"이다. 62%와의 차이가 그 변동폭보다 크면 원인은 seed가 아니라 설정 차이(`max_new_tokens`, `max_model_len`, 프롬프트, 파서·채점 정책, 이미지 해상도)일 가능성이 높다. 다른 팀 설정을 모르면 원인을 확정할 수 없다.

**fine-tuning 이후 평가 규칙(제안)**: baseline과 fine-tuned 모델을 **같은 seed 집합**으로 평가하고 같은 seed끼리 쌍체 비교한다. 개선폭이 seed 간 sd와 쌍체 차이 CI보다 충분히 클 때만 "개선"이라고 말한다. 보고서에는 "bit 단위 재현은 보장되지 않으며 통계적 재현만 가능"이라고 쓴다(기존 보고서의 "배치 구성이 달라지면"은 기록된 배치 설정이 같으므로 원인 미규명으로 정정 권장).

**한계**
- seed당 1회 실행이므로 k가 작으면 PI가 넓다 (k=3이면 t≈4.30, k=5이면 t≈2.78).
- 하나의 설정(`max_new_tokens 8192`)에 대한 결과다. 일반화하지 않는다.
- 문항이 900개 고정이라 단일 run의 이항 표준오차(≈1.6pp)가 seed 변동과 별개로 존재한다.
- 호스트 효과: seed arm은 같은 Pod에서 돌고 baseline은 다른 Pod에서 돌았다. 둘이 다르면 seed 효과와 호스트 효과가 섞인다(그래서 Tier 3).

# Baseline seed robustness (추가 실험)

> **상태: 과제 제출 이후의 추가 실험.** `main`에는 병합하지 않는다. 제안발표(10/6~7)에서 "추가 실험"으로 언급하는 용도.
> 질문: **제출 baseline 66.67% (600/900, sampling seed 3407)는 운 좋은 한 번의 추출이었나?**

이 폴더의 파일은 전부 **신규 파일**이다. 기존 파일(`code/`, `results/mmmu_team_baseline/`, `assignment/`)은 한 글자도 수정하지 않는다.
그래서 병합 시 충돌이 없고, `run_all.sh`가 실행 전 `code/` 해시를 검사해 생성·채점 코드가 baseline과 동일함을 강제한다.

| 파일 | 역할 |
|---|---|
| `make_seed_config.py` | `code/config.yaml`에서 **seed 두 줄만** 바꾼 config 생성 + 변경 키가 seed뿐임을 diff로 검증 |
| `run_all.sh` | RunPod에서 arm들을 순차 실행(생성 → 채점 → 묶기). 중단 시 이어받기 금지(배치 구성이 바뀌므로) |
| `pack_runs.py` | raw(15MB)를 gzip(≈3MB)하고 문항별 결과만 추려 커밋 가능한 크기로 축소 |
| `analyze.py` | 의존성 없는 집계·검정 스크립트 → `REPORT.md`, `summary.json` |
| `CODE_FREEZE.sha256` | 현재 `code/`(tests 제외)의 해시. 브랜치 생성 시점 main(`016b3cf`) 기준 |

---

## 1. 브랜치 분리 (main 보호)

```bash
git checkout main && git pull --ff-only
git tag pre-seed-robustness            # 로컬 태그만. 분기 지점 표시용(push 하지 않음)
git checkout -b exp/baseline-seed-robustness   # README의 Branch Naming 규칙: <type>/<short-description>
```

이 브랜치에서 추가되는 경로는 아래 세 곳뿐이다. 이 세 경로 밖의 변경이 보이면 실수다.

```
experiments/baseline_seed_robustness/      # 스크립트·문서 (이 폴더)
results/baseline_seed_robustness/          # 실행 결과 (arm별 하위 폴더 + analysis/)
reports/baseline_seed_robustness.md        # 발표용 정리 (분석 후 작성)
```

커밋 메시지는 레포 규칙대로 `exp(seed): ...`, 결과 파일은 `eval(seed): ...`.

**실수 방지: main push 차단 훅 (로컬, 커밋되지 않음)**

```bash
cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env bash
while read -r local_ref local_sha remote_ref remote_sha; do
  if [[ "$remote_ref" == "refs/heads/main" ]]; then
    echo "BLOCKED: push to main is disabled for the seed-robustness work." >&2; exit 1
  fi
done
EOF
chmod +x .git/hooks/pre-push
```

브랜치 push(`git push -u origin exp/baseline-seed-robustness`)는 이 훅을 통과한다. RunPod에서 이 브랜치를 clone해야 하므로 실행 전에 한 번 push한다.

**나중에 합칠 때**: 결과가 필요 없으면 브랜치를 그대로 두거나 삭제하면 된다. 합칠 때는 `main`에 직접 병합하지 말고 PR로 올려 diff가 위 세 경로뿐인지 확인한 뒤 병합한다(기존 파일 수정이 없으므로 충돌 없음).

---

## 2. 현재 설정된 seed 전수 조사

레포 코드(`code/config.yaml`, `code/vllm_engine.py`, `code/scoring/`)를 직접 읽어 확인한 결과다.

| # | seed | 값 | 위치 | 무엇에 쓰이나 | 재현성 영향 |
|---|---|---|---|---|---|
| 1 | **SamplingParams seed** | 3407 | `sampling.seed` → `vllm_engine.sampling_kwargs()` → `SamplingParams(seed=…)` | 900개 요청 **모두에 같은 값**이 per-request seed로 들어간다. temperature 0.7 샘플링의 난수열을 결정 | **직접·핵심.** 이 값이 바뀌면 같은 문항도 다른 토큰열을 생성 |
| 2 | **LLM(engine) seed** | 3407 | `sampling.engine_seed` → `llm_kwargs()` → `LLM(seed=…)` | vLLM 워커의 전역 RNG 초기화 | **아마 영향 없음(가설).** 모든 요청이 자기 seed를 갖고 있으면 샘플러는 요청별 generator를 쓰므로 전역 RNG를 거의 쓰지 않는다. 확인 전까지는 가설이므로 `ctrl_engine` arm으로 실측한다 |
| 3 | **Judge seed** | 3407 | `scoring.judge.seed` (gpt-4.1-mini, temperature 0) | 규칙 추출 실패·충돌 문항(약 345개)을 OpenAI API로 판정 | 생성과 무관한 **채점 잡음**. API의 seed는 best-effort라 완전 결정적이라고 보장되지 않음 |
| 4 | MMMU 공식 파서 `random.seed(42)` | 42 | `code/scoring/frozen/vendor/mmmu_eval.py:6` | 파싱 실패 시 무작위 선택지 | **사용되지 않음.** `parsers.py`가 `random.choice`를 차단해 실패는 오답 처리 |
| – | (seed 아님) 배치 구성·GPU·라이브러리 | – | `chunk_size 150`, `first_chunk_size 16`, `max_num_seqs 256`, GPU, vLLM 0.11.0 | bf16 연산의 수치 순서가 배치 모양에 따라 달라짐 | **같은 seed여도 bit 단위 재현이 안 될 수 있음.** `config.yaml`의 `reproducibility_note`가 이미 명시 |

`config.yaml` 주석에 따르면 3407은 Qwen README의 Instruct 평가 seed를 따른 값이다(`engine_seed`). `sampling.seed`는 "team addition"이다. 즉 3407을 결과를 보고 고른 근거는 문서상 없다. 다만 draft 단계에서 seed를 바꿔 본 적이 있다면 발표에서 숨기지 말고 함께 밝히는 편이 안전하다.

---

## 3. 고정할 seed / 실험할 seed

원칙은 수업 슬라이드의 "change one thing at a time"이다.

| 구분 | 항목 | 값 | 이유 |
|---|---|---|---|
| **고정** | Judge seed·모델·설정 | 3407 / gpt-4.1-mini-2025-04-14 / temp 0 | 채점 정책이 같아야 점수가 비교됨(`evaluate.py compare`도 이를 강제). 채점 잡음은 §5-7에서 따로 측정 |
| **고정** | MMMU 파서 seed 42 | 42 | 코드 경로가 막혀 있어 영향 없음 |
| **고정** | `engine_seed` | 3407 | seed arm에서는 한 번에 하나만 바꾸기 위해 유지. 별도 통제 arm에서만 변경 |
| **고정** | 모델·데이터 revision, 프롬프트, temperature/top_p/top_k/penalty, `max_new_tokens 8192`, `max_model_len 16384`, 이미지 해상도, 엔진·배치 설정, GPU 종류, 라이브러리 버전 | baseline 그대로 | `code/` 해시 검사 + `make_seed_config.py`의 diff 검증으로 강제 |
| **변경 (실험 변수)** | **`sampling.seed`** | 아래 arm 표 | 결과를 보기 전에 확정한 목록. 결과를 본 뒤 추가·삭제하지 않는다 |
| **통제** | 동일 설정 재실행 | seed 3407/3407 | seed와 무관한 하드웨어·배치 잡음의 크기 |
| **통제** | `engine_seed`만 변경 | 3407/**1** | §2의 가설(영향 없음) 확인 |

### 실험 arm

| Tier | arm | sampling.seed | engine_seed | 목적 |
|---|---|---|---|---|
| 1 | `ctrl_repeat` | 3407 | 3407 | baseline과 **완전히 같은 설정**의 재실행. 비결정성 하한 |
| 1 | `seed_42` | 42 | 3407 | 독립 seed |
| 1 | `seed_1234` | 1234 | 3407 | 독립 seed |
| 1 | `seed_2026` | 2026 | 3407 | 독립 seed |
| 2 | `seed_777` | 777 | 3407 | 독립 seed (표본 수 확대) |
| 2 | `seed_31337` | 31337 | 3407 | 독립 seed (표본 수 확대) |
| 2 | `ctrl_engine` | 3407 | 1 | engine_seed 영향 확인 |

**Tier를 나눈 이유**: 비교 대상이 baseline 1개 + 다른 seed k개일 때, "baseline이 새 seed의 분포 안에 있는가"를 보는 95% 예측구간은 t 분포를 쓴다. k=3이면 t≈4.30, k=5이면 t≈2.78이라 구간 폭이 크게 달라진다. Tier 1(k=3)만으로도 큰 이탈은 잡히지만 "문제없다"는 결론의 힘은 약하다. 가능하면 Tier 2까지 한다.

**시간·비용**: baseline은 2026-09-21 14:31–15:29 UTC, 약 58분이 걸렸다(모델 로드 포함). arm당 약 1시간으로 잡으면 Tier 1은 약 4시간, 전체는 약 7시간이다. 비용은 `시간 × 그 시점 RunPod 4090 시간당 요금`으로 계산한다. 팀 기준은 run당 ≤ $2였다. Judge 호출은 arm당 약 345건이며 gpt-4.1-mini라 금액은 작다.

---

## 4. 사전 판정 기준 (실행 전에 확정)

실행 후에 기준을 바꾸지 않기 위해 미리 적어 둔다. 임계값은 팀이 정하되, **결과를 보기 전에** 정한다.

1. **운 좋은 결과였는가**: baseline이 다른 seed들의 95% 예측구간 안에 있고, 다른 seed 중 baseline 이상인 것이 있는가. baseline이 단독 최고이면서 구간 밖이면 "운이 좋은 쪽"으로 보고한다.
2. **차이의 크기**: seed 간 평균 차이와 sd를 pp로 보고한다. McNemar p는 보조 지표다. seed가 바뀌면 일부 문항이 뒤집히는데(과거 2048 설정 실험에서는 900문항 중 약 190~200개, 약 21%) 맞힘/틀림이 양방향으로 상쇄돼 net 차이가 작으면 p값은 쉽게 유의하지 않게 나온다. **"유의하지 않다"는 "같다"의 증거가 아니므로**, 쌍체 차이의 95% CI 폭을 함께 읽는다.
3. **통제 arm**: `ctrl_repeat`가 baseline과 문항 단위로 거의 같으면 하드웨어 잡음은 작고 seed가 주된 변동 요인이다. 많이 다르면 같은 seed여도 재현 한계가 있다는 뜻이며, 이 경우 발표에서 "bit 단위 재현은 보장되지 않고 통계적 재현만 가능"이라고 서술한다.
4. **`ctrl_engine`**: `ctrl_repeat`와 비슷한 수준의 차이라면 engine_seed는 영향이 없다고 결론낸다. 더 크게 다르면 §2의 가설이 틀린 것이므로 engine_seed도 변수로 취급한다.

---

## 5. RunPod 단계별 실행

baseline 환경(`results/mmmu_team_baseline/env.json`)은 RTX 4090 1장, Ubuntu 24.04 계열(커널 6.8, glibc 2.39), Python 3.12.3, 드라이버 580.159.04, vLLM 0.11.0, torch 2.8.0+cu128이었다. 같은 조건을 맞추면 된다. 환경 게이트(`check_env.py`)가 Python·패키지·드라이버 불일치를 막아 준다.

**Step 1. Pod 생성**
- GPU: RTX 4090 × 1 (baseline과 같은 종류. 물리적으로 다른 카드여도 상관없다)
- 템플릿: Python 3.12.3이 들어 있는 Ubuntu 24.04 계열 PyTorch 템플릿. 이름은 콘솔에서 확인
- 디스크: `/workspace`에 100GB 이상(모델 ≈ 9GB, 게이트 최소 여유 20GB, 7개 arm 결과 포함). Pod를 껐다 켜도 남도록 persistent volume 사용

**Step 2. 코드 받기** (브랜치를 미리 push해 둔 상태에서)
```bash
cd /workspace
git clone --branch exp/baseline-seed-robustness --single-branch https://github.com/fijitlwkr/MMDL.git
cd MMDL && git log -1 --oneline        # 분기 시점 main(016b3cf) 위에 이 브랜치 커밋만 있어야 함
```

**Step 3. 환경변수**
```bash
export HF_HOME=/workspace/.cache/huggingface
export OPENAI_API_KEY=sk-...           # 채점까지 Pod에서 할 때만. 없으면 생성만 하고 나중에 채점
tmux new -s seed                       # 연결이 끊겨도 계속 돌도록
```

**Step 4. 사전 점검** (GPU 비용을 쓰기 전에 오프라인으로)
```bash
python experiments/baseline_seed_robustness/make_seed_config.py --out /tmp/c.yaml --sampling-seed 42 --engine-seed 3407
cat /tmp/c.diff.json                   # "changed"에 sampling.seed만 있어야 함
```

**Step 5. 실행** — 첫 실행에만 `--install`
```bash
bash experiments/baseline_seed_robustness/run_all.sh --tier 1 --install
# Tier 1 완료 후, 시간·예산이 되면
bash experiments/baseline_seed_robustness/run_all.sh --tier 2
```
- arm마다 `/workspace/seedexp/<arm>/`에 raw.jsonl, run_metadata.json, env.json, logs/, scoring/ 이 생긴다.
- `DONE`이 있는 arm은 건너뛴다. 중단된 arm은 `<arm>.partial.<시각>`으로 옮겨 두고 **처음부터 다시** 돌린다.
- 맨 끝에 `--stop_pod_at_end`를 붙이면 `runpodctl stop pod`를 시도하지만, 이 명령 문법은 레포에서도 미검증이라고 표시돼 있다. `runpodctl --help`로 확인하거나, 끝나면 콘솔에서 직접 끄는 편이 확실하다.

**Step 6. API 키 없이 생성만 했다면 채점**
```bash
export OPENAI_API_KEY=sk-...
for d in /workspace/seedexp/*/; do
  [[ -f "$d/GENERATED_NOT_SCORED" ]] || continue
  python code/scoring/evaluate.py run --out "$d/scoring" && python code/scoring/evaluate.py summarize --out "$d/scoring" \
    && rm "$d/GENERATED_NOT_SCORED" && touch "$d/DONE"
done
python experiments/baseline_seed_robustness/pack_runs.py --work /workspace/seedexp --dest /workspace/seedexp/pack
```

**Step 7. (선택, 몇 센트) 채점 잡음 분리** — baseline raw를 새 Judge 호출로 다시 채점
```bash
python code/scoring/evaluate.py prepare --raw results/mmmu_team_baseline/raw.jsonl --config code/config.yaml --out /workspace/seedexp/rescore_baseline
python code/scoring/evaluate.py run --out /workspace/seedexp/rescore_baseline
python code/scoring/evaluate.py summarize --out /workspace/seedexp/rescore_baseline
```
제출본의 600/900이 캐시된 Judge 응답으로 계산된 값이므로, 같은 생성물을 새로 채점해도 600이 나오는지 확인한다. 달라지면 그 차이가 Judge 비결정성의 크기다. 이 arm은 `seed_*` 분석에 넣지 않는다.

**Step 8. 결과 내려받기** — `/workspace/seedexp/pack/` 폴더를 Jupyter 파일 브라우저, `runpodctl send`, `scp` 중 편한 방법으로 받는다. Pod에서 GitHub에 직접 push하지 않아도 된다(자격 증명 노출 방지).

**Step 9. 로컬에서 분석** (레포 루트)
```bash
cp -r <받은 pack>/* results/baseline_seed_robustness/
python experiments/baseline_seed_robustness/analyze.py
git add results/baseline_seed_robustness experiments/baseline_seed_robustness
git commit -m "eval(seed): baseline seed robustness runs and analysis"
git push -u origin exp/baseline-seed-robustness      # main이 아닌 브랜치
```

---

## 6. 결과 해석과 발표 문구 가이드

`analyze.py`가 만드는 `results/baseline_seed_robustness/analysis/REPORT.md`에 다음이 나온다: arm별 정확도·MC/주관식·길이 종료 수, baseline 대비 쌍체 비교(이득/손실/뒤집힌 문항 수, 차이 CI, McNemar), 다른 seed 분포 대비 baseline 위치(평균, sd, z, 예측구간, 순위), 문항 단위 일관성, 과목별 seed sd.

| 관찰 | 말할 수 있는 것 | 말하면 안 되는 것 |
|---|---|---|
| baseline이 예측구간 안, 평균과 가까움 | "66.67은 우리 설정에서 seed 평균과 일치한다. seed 변동은 ±x pp" | "seed가 무관하다" (정확도가 같아도 개별 문항은 seed마다 뒤집힐 수 있음. 실제 비율은 `item_consistency`로 확인) |
| baseline이 구간 밖의 최고값 | "운이 좋은 쪽이었다. 이후 비교에는 seed 평균 y%를 baseline으로 쓴다" | – |
| `ctrl_repeat`가 baseline과 다름 | "같은 seed여도 하드웨어·배치로 인해 bit 재현은 안 된다. 통계적 재현만 가능" | "재현에 실패했다" |

**다른 팀 62%와의 비교에 대한 주의**: 이 실험이 답하는 것은 "우리 설정에서 seed가 만드는 변동폭"이다. 다른 팀과 점수 차이가 그 변동폭보다 훨씬 크다면, 원인은 seed가 아니라 설정 차이(`max_new_tokens`·`max_model_len`, 프롬프트, 파서·채점 정책, 이미지 해상도 등)일 가능성이 높다. 반대로 변동폭이 비슷하다면 팀 간 차이를 설정 때문이라고 단정할 수 없다. 어느 쪽이든 다른 팀의 설정을 모른 채 원인을 확정할 수는 없다.

**fine-tuning 이후 평가에 쓰는 공정성 규칙(제안)**: baseline과 fine-tuned 모델을 **같은 seed 집합**으로 평가하고, 같은 seed끼리 쌍체로 비교한다. 개선폭이 seed 간 sd와 쌍체 차이 CI보다 충분히 클 때만 "개선"이라고 말한다. 단일 seed끼리의 비교는 운에 취약하다.

**이 실험의 한계**
- 각 arm은 1회 실행이므로 seed 하나당 표본이 1개다. k가 작으면 예측구간이 넓어 작은 이탈은 검출하지 못한다.
- 하나의 설정(`max_new_tokens 8192`, 길이 종료 128건)에 대한 결과다. 다른 설정으로 일반화하지 않는다.
- 문항은 900개로 고정이므로 "문항 표본 추출 변동"(단일 run의 이항 표준오차 약 1.6 pp)은 seed 변동과 별개로 존재한다.
- 과목별 sd는 과목당 30문항이라 매우 거칠다. 과목 단위 결론에는 쓰지 않는다.
- 과거 `assignment/archive/hakyung/experiments/expF_seed_repro`에 seed 3종(42/3407/1234) 실험이 있으나, `max_new_tokens 2048`·`max_model_len 9048` 설정(정확도 약 46%)이고 archive는 "참조 금지"로 표시돼 있다. 설계 참고만 하고 발표 근거로는 쓰지 않는다.

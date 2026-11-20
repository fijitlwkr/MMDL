# 가설 A 평가 (E1~E3 × 시드 3개)

하경님이 학습한 모델 3개를 baseline(E0)과 같은 코드·설정·시드로 MMMU val 900문항에 추론한다. 채점은 파드를 끈 뒤 맥에서 한다(GPT 판정 호출이 순차라 파드에서 하면 GPU가 놀면서 과금된다).

| 이름 | 모델 (HF) | revision |
|---|---|---|
| e1 | MMDL-team4/hypA-e1-matched-2k | 8a13d9e67dd5ff16c5407dd756962ecff725eabe |
| e2 | MMDL-team4/hypA-e2-control-2k | 7d4a8a58c427fdcbb6e9b0382e6176630770c57f |
| e3 | MMDL-team4/hypA-e3-general-2k | e591371e742f8e5cd4e7859d892305789c3b8516 |

- 시드: sampling seed 42 / 1234 / 2026, engine seed 3407. E0 는 `exp/baseline-seed-robustness` 브랜치의 `results/baseline_seed_robustness/seed_{42,1234,2026}` 을 그대로 쓴다.
- E0 와 같은 조건인지 확인한 것
  - 현재 main 의 `code/` 해시가 E0 를 돌릴 때와 같다(`run_eval.sh` 가 실행 전에 다시 검사한다).
  - `make_seed_config.py` 로 만든 시드 42 config 가 E0 seed_42 의 `config_used.yaml` 과 한 글자도 다르지 않다.
  - 학습된 모델의 대화 템플릿은 원래 모델과 같고, 토크나이저의 단어 사전·병합 규칙·특수 토큰도 같다(파일 저장 형식만 새 버전).
- `make_seed_config.py` 는 시드 실험 브랜치의 파일을 그대로 가져왔다.

## 순서 (RunPod)

1. 파드를 켠다. RTX 4090, 템플릿 PyTorch 2.8.0 / CUDA 12.8.1, **Container Disk 80GB** (모델 9GB × 3 + 패키지).
2. Jupyter 터미널에서 이 브랜치(`exp/hypA-eval`)로 레포를 받는다.
   ```bash
   cd /workspace && git clone -b exp/hypA-eval https://github.com/fijitlwkr/MMDL.git && cd MMDL
   ```
3. 팀 고정 버전으로 설치한다(약 5분). vLLM 만 따로 깔면 transformers 최신 버전이 같이 깔려 에러가 나므로 꼭 이 파일로 설치한다.
   ```bash
   pip install -r code/requirements.txt
   ```
4. HF 에 로그인한다(쓰기 토큰). 비공개 모델을 받고 결과를 올리는 데 쓴다. 스크립트가 HF 캐시를 `/workspace/.cache/huggingface` 에 두므로 토큰도 같은 곳에 저장해야 한다. "Add token as git credential?" 에는 n.
   ```bash
   HF_HOME=/workspace/.cache/huggingface huggingface-cli login
   ```
   스크립트는 시작하자마자 모델에 접근되는지 확인하고, 안 되면 GPU 를 쓰기 전에 멈춘다.
5. E1 시드 42 하나만 먼저 돌린다. `nohup` 으로 돌려서 브라우저를 닫아도 멈추지 않게 한다. `tail` 은 Ctrl+C 로 빠져나와도 실행은 계속된다.
   ```bash
   nohup bash experiments/hypA-eval/run_eval.sh --arms e1:42 > /workspace/eval_e1_42.log 2>&1 &
   tail -f /workspace/eval_e1_42.log
   ```
6. 로그 끝에 `END e1_seed_42  NN min` 과 `[uploaded] MMDL-team4/hypA-eval-raw/e1_seed_42` 가 나오면 끝이다. 걸린 시간을 하경님께 공유한다.
7. 나머지는 같은 파드에서 이어서 돌린다(파드를 멈췄다 켜면 다른 서버로 옮겨져 설치를 다시 해야 할 수 있다).
   ```bash
   nohup bash experiments/hypA-eval/run_eval.sh --arms e1:1234,e1:2026,e2:42,e2:1234,e2:2026,e3:42,e3:1234,e3:2026 > /workspace/eval_rest.log 2>&1 &
   ```
8. 모두 업로드된 것을 확인하고 파드를 Terminate 한다.

## 시간·비용 (E0 실측 기준)

- arm 1개(모델 1개 × 시드 1개): 생성 56~100분 + 모델 로드 약 3분. 첫 설치·모델 다운로드는 별도(15~30분).
- 9개: GPU 9~15시간. RTX 4090 시간당 약 $0.89 기준 8~14달러.
- 채점(맥에서): arm 당 약 9분, 약 $0.5 (gpt-4.1-mini 판정 약 345문항). 9개 약 4.5달러.

## 결과

- HF 비공개 데이터셋 `MMDL-team4/hypA-eval-raw` 의 `<이름>_seed_<시드>/` 에 arm 이 끝날 때마다 올라간다: `raw.jsonl`, `run_metadata.json`, `env.json`, `env_check.json`, `config_used.yaml`, `logs/`, `arm_minutes.txt`.
- 끊긴 arm 은 이어받지 않고 `.partial.<시각>` 으로 옮긴 뒤 처음부터 다시 돌린다. 이미 `DONE` 인 arm 은 건너뛴다.

## 채점과 분석 (맥)

1. 채점. HF 에서 답안을 받아 규칙 채점 + judge 까지 한다. OpenAI 키는 시작할 때 한 번 묻는다(화면·파일에 남지 않음). 작업 폴더는 재부팅에 지워지지 않는 곳에 둔다.
   ```bash
   bash experiments/hypA-eval/score_all.sh --work <작업 폴더>
   ```
2. 커밋용 묶음. baseline 시드 실험과 같은 방식(`raw.jsonl.gz` + 문항별 채점 `item_results.jsonl` + 채점 요약)이다.
   ```bash
   python experiments/hypA-eval/pack_runs.py --work <작업 폴더> --dest results/hypA_eval
   ```
3. 분석. E0 는 `exp/baseline-seed-robustness` 브랜치의 `results/baseline_seed_robustness/seed_{42,1234,2026}` 을 받아 둔 폴더를 넘긴다.
   ```bash
   python experiments/hypA-eval/analyze.py --runs results/hypA_eval --e0 <E0 시드 폴더> --out results/hypA_eval/analysis
   ```

`pack_runs.py` 는 시드 실험 브랜치의 파일을 그대로 가져왔다.

## 실측 (2026-11-02)

- 생성: arm 당 33~50분, 9개 합계 약 6시간 30분. 에러 0건. 학습된 모델은 답이 짧아서 E0(97~106분)보다 빨랐다.
- 채점: judge 대상은 arm 당 125~255문항, 9개 합계 1,669문항. 약 35분, $1.57.
- 결과 요약: `results/hypA_eval/analysis/REPORT.md`. 의료 문항 답변을 직접 읽은 기록: `results/hypA_eval/analysis/MEDICAL_REVIEW.md`.

## GRPO 체크포인트 평가 (2026-11-17 하경님 요청)

hypA RL(GRPO) 30스텝 학습의 LoRA 어댑터(`MMDL-team4/hypA-grpo-pilot30-ckpt` 의 `step10/`·`step20/`·`step30/`)를 E1~E3 와 같은 방식으로 평가한다. 이름은 `g10`·`g20`·`g30`, 시드는 E0·E1~E3 와 같은 42/1234/2026(engine seed 3407).

- 병합본이 없어서 `run_eval.sh` 가 arm 을 돌리기 전에 `merge_adapter.py` 로 베이스(`code/config.yaml` 의 고정 revision)에 병합한다. 어댑터 설정 파일에 적힌 베이스 경로(학습 서버 로컬 경로)는 쓰지 않는다.
- 병합본 폴더(`/workspace/hypA_eval/merged/g30` 등)의 config·토크나이저·프로세서·대화 템플릿은 베이스 파일을 그대로 복사하고 가중치만 병합본이다. 평가 코드(`code/`)·config·프롬프트·채점·생성 상한 8192 는 그대로다(`code/` 해시 검사 그대로).
- `merge_adapter.py` 가 확인하는 것: 어댑터가 LoRA 키만 있고 비전 키가 없는지, 어댑터 텐서가 모델에 빠짐없이 값 그대로 올라갔는지, 병합 뒤 바뀐 가중치가 LoRA 대상 언어모델 선형층뿐인지(비전·임베딩 등은 비트 단위로 같음). 하나라도 어긋나면 GPU 평가 전에 멈춘다.
- 병합본은 bf16 이라 LoRA 변화가 아주 작으면 반올림으로 일부가 사라진다. 층마다 계산상 변화(scaling × B·A)와 실제로 더해진 변화의 차이를 `merge_info.json` 의 `bf16_merge` 에 기록한다(로그에도 한 줄). 각 arm 결과 폴더에도 `merge_info.json` 이 복사되어 HF 에 같이 올라간다.
- 어댑터 저장소는 첫 실행 때 commit sha 로 고정해 `/workspace/hypA_eval/adapter_rev_pilot30.txt` 에 저장하고 `--revision` 으로 기록한다. 같은 파드의 이후 실행(step10·20)도 이 sha 를 쓴다(`ADAPTER_REV=<sha>` 로 직접 지정 가능).
- 학습 시작 모델 확인: 어댑터와 같이 저장된 swift `args.json` 의 모델이 이 베이스(이름·snapshot revision)가 아니면 멈춘다(원본이 아닌 모델에서 학습했는데 원본에 병합하는 실수 방지). 경로 이름만 다르고 원본이 맞다고 확인되면 `SKIP_BASE_CHECK=1` 로 건너뛴다.
- 병합본 bf16 경고: 값이 바뀐 원소가 절반 미만이거나 반올림 오차 중앙값이 0.5 를 넘으면 로그에 `경고(bf16)` 가 찍힌다. 이때는 결과 보고에 `merge_info.json` 의 `bf16_merge` 숫자를 같이 적는다(학습 변화가 병합 과정에서 줄어든 상태로 평가된 것일 수 있음).

### 순서 (RunPod)

1. 파드: RTX 4090, 템플릿 PyTorch 2.8.0 / CUDA 12.8.1, **Container Disk 100GB**(베이스 9GB + 병합본 9GB × 최대 3 + 패키지). 켠 뒤 `df -h /workspace` 로 여유가 70GB 이상인지 본다(모델·병합본·결과가 /workspace 에 쌓인다).
2. 받기·설치·로그인(위 "순서" 2~4 와 같다). 그다음 병합용 peft 를 팀 고정 버전을 바꾸지 못하게 제약을 걸어 설치한다(학습 때와 같은 0.20.0).
   ```bash
   cd /workspace && git clone -b exp/hypA-eval https://github.com/fijitlwkr/MMDL.git && cd MMDL
   pip install -r code/requirements.txt
   pip freeze | grep -v -E '^(-e |.* @ )' > /workspace/constraints.txt && pip install peft==0.20.0 -c /workspace/constraints.txt
   HF_HOME=/workspace/.cache/huggingface huggingface-cli login
   ```
3. step30 의 시드 3개. 병합(약 10분) 뒤 arm 마다 생성하고 끝날 때마다 HF(`MMDL-team4/hypA-eval-raw/g30_seed_<시드>/`)에 올린다.
   ```bash
   nohup bash experiments/hypA-eval/run_eval.sh --arms g30:42,g30:1234,g30:2026 > /workspace/eval_g30.log 2>&1 &
   grep -E "adapter repo|어댑터 텐서|가중치 비교|LoRA 변화|MERGE_OK|ABORT|START|END|uploaded" /workspace/eval_g30.log
   ```
4. 여유가 있으면 step10·20 도 같은 파드에서 이어서 돈다(이미 끝난 arm·병합은 건너뛴다).
   ```bash
   nohup bash experiments/hypA-eval/run_eval.sh --arms g10:42,g10:1234,g10:2026,g20:42,g20:1234,g20:2026 > /workspace/eval_g1020.log 2>&1 &
   ```

### step100 재학습 체크포인트 (2026-11-20 추가)

lr 1e-4 로 100스텝 다시 학습한 어댑터(`MMDL-team4/hypA-grpo-step100-ckpt` 의 `step25/`·`step50/`·`step75/`·`step100/`)를 같은 방식으로 평가한다. 이름은 `g25`·`g50`·`g75`·`g100`. 파드·설치는 위 1~2 와 같다. 병합본이 4개(9GB씩)라 `/workspace` 여유가 70GB 이상인지 꼭 본다.

```bash
ADAPTER_REV=7af4bebfd1e2dfe1252cad05dff6a8ce98b31d77 nohup bash experiments/hypA-eval/run_eval.sh --arms g100:42,g50:42,g25:42,g75:42 > /workspace/eval_step100.log 2>&1 &
grep -E "adapter repo|LoRA 변화|경고|MERGE_OK|ABORT|START|END|uploaded" /workspace/eval_step100.log
```

- 어댑터 저장소는 arm 이름으로 정해진다(g10~g30 = 파일럿, g25~g100 = step100). 한 번 실행에 두 저장소를 섞으면 멈춘다. 고정 sha 는 `/workspace/hypA_eval/adapter_rev_step100.txt` 에 저장된다.
- 병합 4개를 먼저 하고(약 10분씩) 생성은 적은 순서대로 한다. 끝난 arm 부터 HF 에 올라가므로 중간에 멈춰도 앞 arm 결과는 남는다.
- 학습 조건 차이: 학습 GPU 가 L40S 라 micro batch 2 × grad accum 64 로 돌렸다(파일럿은 RTX 6000 Ada 에서 4 × 32). 스텝당 응답 수 128 은 같다.

### 채점·분석 (맥)

```bash
bash experiments/hypA-eval/score_all.sh --work <작업 폴더> --arms g30_seed_42,g30_seed_1234,g30_seed_2026
python experiments/hypA-eval/pack_runs.py --work <작업 폴더> --dest results/hypA_grpo_eval
python experiments/hypA-eval/analyze.py --runs results/hypA_grpo_eval --e0 <E0 시드 폴더> --arms g30 --title "GRPO 체크포인트 평가" --out results/hypA_grpo_eval/analysis
```

`analyze.py` 는 조건마다 있는 시드만 쓰고, E0 대비 값은 같은 시드의 E0 평균과 비교한다. 하경님 기준: 전체 정확도 차이가 표준오차(약 1.7pt)보다 작으면 "차이 없음".

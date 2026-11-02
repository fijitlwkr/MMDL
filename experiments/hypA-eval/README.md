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

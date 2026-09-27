# mmmu_team_baseline

Qwen3-VL-4B-Instruct의 MMMU validation 900문항 baseline 결과다. 이후 fine-tuning 결과는 이 폴더와 같은 방식으로 평가해 비교한다.

| 항목 | 값 |
|---|---|
| 점수 | **600/900 (66.67%)**, 객관식 560/847, 주관식 40/53 |
| 채점 정책 | `hybrid100_mc_qwen_ab_open_no_length_gate_v2`, Judge `gpt-4.1-mini-2025-04-14` |
| raw SHA-256 | `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313` |
| 종료 사유 | stop 772, length 128 (ok 900, skip/error 0) |
| 실행 | 2026-09-21 14:31–15:29 UTC, RTX 4090 1장, code commit `a19f7b8` |

`INFERENCE_OUTPUT_SPEC.md` §4가 인용하는 `cd1c4ff…`(stop 792, length 108)는 이 run이 아니라 `assignment/runs/draft`다.

## 파일

| 파일 | 내용 |
|---|---|
| `raw.jsonl`, `run_metadata.json`, `env.json`, `env_check.json` | 추론 원본. 바이트 그대로 보존하며 수정하지 않는다 |
| `run_metadata.supplement.json` | 원본에 없는 실행 사실 보완: 실제 바깥 명령, 폴더 이동 이력, 현재 config와의 차이 |
| `judge_cache/gpt-4.1-mini.jsonl` | 채점에 쓴 Judge 응답 363건 |
| `scores/` | 과목별·문항별 결과. [30과목 표](scores/subject_scores.md), [집계](scores/scores.json) |

`run_metadata.json`의 `run_id`가 `max_new_tokens8192_hakyung`인 것은 폴더 이름을 바꾸기 전 기록이기 때문이다.

## 재현

생성부터 채점까지 한 커맨드로 실행한다. Judge 호출에는 `OPENAI_API_KEY`가 필요하다.

```bash
bash code/run_mmmu_eval.sh --install --out <OUT_DIR> --data_root <HF_DATASETS_DIR>
```

API 없이 이 폴더의 점수만 재계산하고 제출본과 바이트 대조하려면 다음을 실행한다(저장소 루트, Python 3.10+).

```bash
python -m pip install -r code/scoring/requirements.txt
python assignment/experiments/submission/reproduce.py \
  --evaluator code/scoring/evaluate.py \
  --input results/mmmu_team_baseline/raw.jsonl \
  --metadata results/mmmu_team_baseline/run_metadata.json \
  --judge-cache results/mmmu_team_baseline/judge_cache/gpt-4.1-mini.jsonl \
  --out /tmp/mmmu_replay \
  --expected results/mmmu_team_baseline/scores
```

`reproduce.py`는 채점 결과에 자기 해시가 기록되어 있어 수정하지 않았다. 그래서 기본 경로 대신 위 인자들을 명시해야 한다.

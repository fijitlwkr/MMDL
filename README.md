## Project Overview

본 프로젝트는 Qwen3-VL-4B-Instruct 을 파인튜닝하여 MMMU&MMMU-Pro 에서의 성능을 개선하는 것을 목표로 한다.

---

## 결과와 실험 자료

- [과제 제출 보고서](reports/mmmu_baseline.md) 
- [확정 baseline 결과](results/mmmu_team_baseline/README.md)
- [실험 결과·근거 목차](assignment/experiments/README.md)

## Directory Structure

```
.
├── code/                     # [공통] 평가 파이프라인. baseline·fine-tuning 모델 모두 이 코드로 평가
│   ├── run_mmmu_eval.sh      # 생성 → 검증 → 채점 한 커맨드
│   ├── run_generate.sh, generate.py, config.yaml(평가 설정), requirements.txt, tests/
│   └── scoring/              # 채점기(evaluate.py + frozen 파서). 내용 수정 금지(해시 고정)
├── results/
│   └── mmmu_team_baseline/   # [baseline] 승인된 기준 결과 (raw, metadata, judge_cache, scores)
├── reports/
│   └── mmmu_baseline.md      # [baseline] 과제 보고서 (과제 가이드 경로)
├── assignment/               # [baseline 전용·동결] 과제 근거 자료. fine-tuning 작업 추가 금지
│   ├── experiments/          # 채점·격차 분석 실험과 제출 근거 (보존)
│   ├── runs/                 # 최종본이 아닌 과거 추론 run (보존)
│   └── archive/              # 팀원 개인 작업 공간 원형 보관 (참조 금지)
├── LICENSE
└── README.md
```

## 재현

```bash
HF_HOME=<HF_CACHE_DIR> bash code/run_mmmu_eval.sh --install --out <OUT_DIR> --data_root <HF_DATASETS_DIR> [--model_path <체크포인트>]
```

Judge 채점에는 `OPENAI_API_KEY`가 필요하다. 키 없이 baseline 점수만 재계산하는 방법은 [results/mmmu_team_baseline/README.md](results/mmmu_team_baseline/README.md)에 있다.

## 규칙

1. **경로는 인자로 받는다.** 코드 안에 `assignment`, `results` 같은 경로를 넣지 않는다.
2. **값은 `code/config.yaml`에만 쓴다.**
3. **`results/*/raw.jsonl`과 `run_metadata.json`은 수정하지 않는다.** 보완할 사실은 `run_metadata.supplement.json`에 적는다.
4. **`code/`는 `assignment/` 아래 어떤 것도 import하지 않는다.**
5. **`code/scoring/evaluate.py`와 `frozen/`은 수정하지 않는다.** 채점 결과에 해시가 기록되어 있어, 바꾸면 baseline과 비교할 수 없다. 채점 방식을 바꿔야 하면 새 버전으로 추가하고 baseline을 다시 채점한다.
6. **fine-tuning 결과는 `results/<이름>/`에 baseline과 같은 파일 구성으로 둔다.**

## 이름 규칙

| 구분 | 위치·이름 | 의미 |
|---|---|---|
| baseline 전용 | `assignment/`, `results/mmmu_team_baseline/`, `reports/mmmu_baseline.md` | 과제 제출본. 동결 |
| 공통 | `code/` (`config.yaml`은 평가 설정) | 모든 체크포인트를 같은 조건으로 평가 |
| fine-tuning 결과 | `results/mmmu_<체크포인트 이름>/` | 예: `results/mmmu_lora_r16/` |
| fine-tuning 보고서 | `reports/<단계 이름>.md` | baseline 보고서와 파일을 분리 |

학습 코드와 학습 설정은 평가 설정(`code/config.yaml`)과 섞이지 않도록 별도 폴더·파일(예: `code/train/`, `train_config.yaml`)로 둔다.

---

## Commit Convention

commit은 수동으로 해도 되고, agent에게 시켜도 됩니다.

```
<type>(<scope>): <subject>

예: exp(lora): rank 16 -> 32 비교 실험 추가
```

| Type | 설명 |
| :--- | :--- |
| `data` | 데이터셋 수집, 전처리, 클리닝 관련 변경 |
| `exp` | 실험 설정 추가/변경 (하이퍼파라미터, 학습 전략 등) |
| `train` | 학습 스크립트/파이프라인 변경 |
| `eval` | 평가 스크립트, 벤치마크 실행 관련 변경 |
| `model` | 모델 구조, 체크포인트 관련 변경 |
| `docs` | 문서(README, 발표자료 설명 등) 변경 |
| `fix` | 버그 수정 |
| `refactor` | 코드 구조 개선 (기능 변화 없음) |
| `chore` | 의존성, 설정 파일 등 기타 변경 |

**Scope**는 세부 대상(예: `preprocess`, `lora`, `mmmu`, `qwen3vl`)을 자유롭게 명시.

---

## Branch Naming

```
<type>/<short-description>
예: exp/lora-rank-search, eval/mmmu-baseline
```

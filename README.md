## Project Overview

본 프로젝트는 오픈소스 MLLM(예: Qwen3-VL-4B-Instruct)을 파인튜닝하여 target benchmark(MMMU)에서의 성능을 개선하는 것을 목표로 한다.

---

## Directory Structure

```
.
├── assignment/               # 과제 작업장. 승인 전 모든 작업은 여기서
│   ├── DECISIONS.md          # 결정 로그 (유일하게 계속 갱신하는 문서)
│   ├── src/                  # 추론 + 채점 코드          → 승격 시 code/
│   ├── runs/                 # 추론 결과 (draft, A, B)   → 승격 시 results/
│   ├── experiments/          # 실험팀 스크립트, 라벨, 후보 출력 (승격 안 함)
│   └── <name>/               # 개인 scratch
├── reports/
│   └── mmmu_baseline.md      # 제출 보고서. 이 위치에서 바로 작성
├── code/                     # (승격 후) 확정된 코드. 이후 fine-tuning도 여기에
├── results/                  # (승격 후) 확정된 결과
├── LICENSE
└── README.md
```

`code/`와 `results/`는 baseline이 승인되기 전에는 **존재하지 않습니다.** 승격하는 순간 생깁니다.

### 담당

| 경로 | 담당 | 비고 |
| :--- | :--- | :--- |
| `assignment/src/`, `assignment/runs/` | 추론팀 | |
| `assignment/experiments/` | 실험팀 | |
| `assignment/DECISIONS.md` | 양 팀 | 자기 팀이 내린 결정만 수정 |
| `reports/mmmu_baseline.md` | 추론팀: 1, 2, 3, 5, 6절 / 실험팀: 4, 7, 8절 | 자기 절만 수정, 수정 전 pull |
| `assignment/<name>/` | 본인 | scratch. 어디서도 import/참조 금지 |

### 규칙

1. **경로는 인자로 받습니다.** 코드 안에 `assignment`, `results` 같은 문자열을 넣지 않습니다.
2. **값은 `src/config.yaml`에만 씁니다.** `DECISIONS.md`에는 결정과 근거만 적고 값은 복사하지 않습니다.
3. **`runs/*/raw.jsonl`은 수정하지 않습니다.** 고치려면 재추론입니다. 채점 결과(`scores.json`)는 언제든 raw에서 다시 만들 수 있습니다.
4. **`src/`는 `experiments/`와 개인 폴더를 import하지 않습니다.** 실험팀이 채택한 파서/judge는 승격 직전에 `src/`로 복사합니다.
5. **실험 채택 규칙은 결과를 보기 전에 커밋합니다.** git 시간이 사전 확정의 증거입니다.

---

## Baseline 승격 절차

baseline이 `approved`(9/22 밤 회의)되면 아래 순서로 실행합니다.

```bash
# 1. 채택된 파서/judge를 assignment/src/ 로 복사하고 src/run_mmmu_eval.sh 작성 (generate + evaluate 두 줄)
# 2. 이동 (복사가 아님)
git mv assignment/src code
git mv assignment/runs results
# 3. 새 위치에서 채점을 다시 실행해 scores 재생성
# 4. 새 clone에서 한 커맨드로 재현되는지 확인
# 5. DECISIONS.md 상단을 baseline: runs/A (또는 B), 상태: approved 로 갱신
git commit -m "chore(promote): assignment -> code/results"
```

> `git mv assignment/src code`는 `code/`가 **없을 때만** 폴더 이름을 바꿉니다. `code/`가 이미 있으면 `code/src/`로 들어가 버리므로, 승격 전에 `code/`, `results/`를 만들지 마세요.

### 이렇게 하는 이유

| 규칙 | 이유 |
| :--- | :--- |
| 승인 전에는 `code/`, `results/`를 비워 둠 | 이 두 폴더에 있다는 것은 "승인된 baseline"이라는 신호. 미확정 결과가 fine-tuning 비교 기준으로 쓰이는 것을 막는다 |
| 복사가 아니라 `git mv` | 사본이 둘이면 어느 쪽이 최신인지 헷갈린다 |
| 경로를 인자로 받음 | 폴더를 옮겨도 코드를 고칠 필요가 없다 |
| `experiments/`는 승격 안 함 | 1회성 코드다. 결정의 근거로 `assignment/`에 남기고, 채택된 것만 `src/`로 가져온다 |
| 보고서는 `reports/`에서 바로 작성 | 제출 위치가 정해져 있고 이동할 이유가 없다 |
| 새 위치에서 채점을 다시 실행 | 옮긴 뒤 경로 문제를 이 단계에서 잡는다 |

재추론이 필요한 경우(프롬프트, sampling, 이미지 처리, max tokens, 컨텍스트 초과 처리 규칙 변경 등)는 `assignment/DECISIONS.md` 3절을 참고합니다.

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

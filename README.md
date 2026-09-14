## Project Overview

본 프로젝트는 오픈소스 MLLM(예: Qwen3-VL-4B-Instruct)을 파인튜닝하여 target benchmark(MMMU)에서의 성능을 개선하는 것을 목표로 한다.

### Directory Structure

```
.
├── assignment/   # assignment1.md
├── code/         # fine-tuning, 평가 등 실행 코드
├── results/      # 평가 결과
├── LICENSE
└── README.md
```

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

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

### Branch Naming

```
<type>/<short-description>
예: exp/lora-rank-search, eval/mmmu-baseline
```

---

## PR Convention

- **제목**: 커밋 타입과 동일한 규칙 사용 (예: `exp: LoRA rank 탐색 실험`)
- **본문에 포함할 내용**:
  1. 목적 (무엇을, 왜)
  2. 변경 사항 요약
  3. 실험 결과 (있다면 벤치마크 점수, 비교 표/그래프)
  4. 재현 방법 (config, seed, 실행 커맨드)
- **체크리스트**:
  - [ ] `results/`에 실험 결과 기록 여부
  - [ ] config/seed 고정 및 기록 여부
  - [ ] 불필요한 대용량 파일(체크포인트 등) 포함 여부 확인
  - [ ] requirements/환경 변경 시 관련 파일 업데이트 여부

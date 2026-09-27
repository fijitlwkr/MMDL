# MMMU Parser 개선

MMMU Benchmark 평가를 위해 Answer Parser와 Evaluation Logic을 개선했습니다.

## 주요 변경 사항

### `code/src/parser.py`

- Multiple-Choice 답안 추출 로직 개선
- `\boxed{A}`, `\boxed{(B)}`, `\boxed{\text{C}}` 지원
- `final answer`, `correct answer`, `option`, `choice` 등의 패턴 지원
- 긴 CoT에서 최종 답안을 우선적으로 추출
- Open-ended 문항 지원
- 숫자, 분수, 퍼센트, 통화 및 텍스트 답안 정규화
- `math.isclose`를 이용한 수치 비교

### `code/src/evaluate_vllm.py`

- `seed=42` 고정으로 재현성 향상
- `question_type` 및 `options` Metadata를 Parser에 전달
- Multiple-Choice와 Open-ended 문항을 구분하여 평가

## 검증 결과

- `py_compile` 문법 검사 통과
- 기존 Raw Prediction을 사용하여 Parser 재평가

| Metric   | Before |  After |
| -------- | -----: | -----: |
| Correct  |    459 |    478 |
| Accuracy | 51.00% | 53.11% |

**+19 correct answers / +2.11%p**

> 모델 자체를 변경한 것이 아니라 Parser 및 Evaluation Logic을 개선하여 기존 결과를 더 정확하게 평가한 결과입니다.

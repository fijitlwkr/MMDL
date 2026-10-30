# MMFR 데이터 선별 (가설 B)

가설 B 학습 데이터를 MMFineReason-1.8M(`OpenDataArena/MMFineReason-1.8M-Qwen3-VL-235B-Thinking`, rev `7c93f724`)에서 골랐다. 만든 데이터는 레포에 두지 않고 HF 데이터셋 `MMDL-team4/hypB-train-data`(v1.1)에 올렸다.

## 선별 기준

| 기준 | 규칙 | 근거 |
|---|---|---|
| 후보 범위 | 비STEM 분야는 후보 전체, Science는 5,000건 표본, Tech는 표본 5,000건 + 순서도가 아닌 후보 전체 | `rules/allocation.md` |
| 정답 | 교사 풀이의 최종 답이 데이터 정답과 일치 (완전 일치 → 수식 동치 → 보기 동치) | |
| 풀이 형식 | 긴 추론 뒤 정리 풀이만 사용, 8,192토큰 이내 | |
| 분야 | 어느 과목 수업·시험에 나올 문제인가 | `rules/domain_rubric.md` (직접 판정) |
| 풀이 필요 | 계산·비교·조건 적용이 필요한 문항 (Art 예외) | `rules/reasoning_rule.md` (직접 판정) |
| 구성 비율 | MMMU 6분야 비율 기준, 부족 분야는 재배분 | `rules/allocation.md` |
| 난이도·편중 | 통과율 1 문항은 후순위(Health ≤ 200), 순서도 실행 문항 ≤ 300 | `rules/allocation.md` |
| 품질 | 풀이 반복·이미지 이상·길이 초과·보기 형식 문제 없음 | |
| MMMU 중복 | MMMU dev/validation/test, MMMU-Pro standard(10 options)와 질문 n-gram·이미지 pHash 대조, 중복 0건 | `scripts/contamination/` |

학습 형식: 평가 프롬프트와 같은 E1(정리 풀이 + `Final Answer`)·E2(`Final Answer`만), ms-swift 형식 (`scripts/convert/`).

## 결과

| 분야 | 학습 | 비율 |
|---|---:|---:|
| Science | 824 | 27.5% |
| Business | 796 | 26.5% |
| Health & Medicine | 547 | 18.2% |
| Tech & Engineering | 489 | 16.3% |
| Humanities & Social Science | 229 | 7.6% |
| Art & Design | 115 | 3.8% |
| 합계 | 3,000 | |

holdout 299건(학습과 겹치지 않음). 문항 목록과 해시는 `lists/`.

MMFR이 수학·과학 위주라 Art·Humanities·Tech는 기준을 통과한 문항이 모자랐고, 부족분은 Business·Science·Health로 재배분했다.
최종 목록은 선별 후 검수에서 문제가 발견된 일부 문항을 같은 기준을 통과한 다음 후보로 바꾼 결과다.

## 폴더

| 경로 | 내용 |
|---|---|
| `rules/` | 분야 판정 기준, 풀이 필요 기준, 배정·상한 규칙 |
| `scripts/contamination/` | MMMU·MMMU-Pro 대조. `image_text_check.py`: 질문 8-gram + 이미지 pHash, `check_contamination.py`: 질문 13-gram 일치 + 5-gram 유사도 + 이미지 pHash. 정답·해설 열은 읽지 않는다 |
| `scripts/convert/` | `stage47_prepare.py`: 팀 평가 코드의 프롬프트 함수(`_prompt_text`, `build_messages`)로 E1/E2 생성, `to_swift.py`: ms-swift 형식 변환 |
| `lists/` | 학습 3,000건·holdout 299건 목록(출처·ID·MMFR 행·분야·과목·통과율·순서도 여부), 파일 해시, HF 태그 |

## 참고

스크립트는 실행 당시 그대로 둔 기록이며, 경로와 내부 보조 모듈이 작업 환경에 맞춰져 있어 그대로 재실행되지는 않는다.
문항 원문·정답·풀이·이미지는 HF 데이터셋에만 있다.

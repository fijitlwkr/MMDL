# 채점 방식 선택과 격차 분석의 실험 근거

최신 raw 900문항에 **Qwen 규칙 + 객관식 Final Answer 100자 보완 + 미추출·충돌 Judge**를 적용한 결과는 **600/900(66.67%)**다. 과제 기준 67.4%와의 차이는 **−0.73%p**다.

최신 입력 SHA-256: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`

## 1. Qwen 기본 파서와 Final Answer 보완을 선택한 이유

| 결정 | 관측 결과 | 근거 |
|---|---|---|
| Qwen 규칙을 기본으로 사용 | H1의 파서 불일치 49건에서 검토 답과 Qwen 47건, MMMU 2건 일치 | [H1 보고서](../scoring_lab/legacy_pilot/h1/REPORT.md), [문항별 답 추출 비교](../scoring_lab/legacy_pilot/h1/parser_comparison.jsonl) |
| 객관식 Final Answer 100자 보완 | H2 고정 표본에서 검토 답과 100/100 일치. Qwen 미추출을 보완한 59건도 59/59 일치 | [H2 보고서](../scoring_lab/legacy_pilot/h2/REPORT.md), [문항별 비교](../scoring_lab/legacy_pilot/h2/parser_comparison.jsonl). 정상 종료 객관식의 보완 자동 채택군에 대한 검토 |
| 두 규칙이 충돌하면 Judge로 이동 | 보완 규칙이 답을 제시해도 Qwen과 다른 경우 자동으로 덮어쓰지 않음 | [실제 처리 코드](../raw_evaluation/evaluate.py). 미추출도 Judge로 이동 |

H1·H2는 **과거 899문항 pilot**(생성 seed 42, cap 9048)의 표본 검토다. 검토자 1명이 H1 49건과 H2 100건을 확인했으며, 중복 10건을 제외한 고유 문항은 **139건**이다. H2 표본 선정 seed는 3407이다.

최신 raw에서 주관식·length 정책을 고정한 보완 규칙 비교 실험에서는 Judge 대상이 **543건→363건**으로 줄었다. 추가 자동 처리 184건, 충돌에 따른 Judge 이동 4건으로 **순감소 180건(33.15%)**이다. [비교 결과](results/comparisons.json)

## 2. 처리 경로 비교

| 동일 raw 내 정책 비교 | 게이트 적용 | 게이트 제거 | 변화 |
|---|---:|---:|---:|
| 최신 수신 raw | 594/900 (66.00%) | 600/900 (66.67%) | +6문항 |
| 이전 9/21 raw | 609/900 (67.67%) | 608/900 (67.56%) | −1문항 |

현재 정책은 **추출 성공·충돌 여부로 처리 경로를 정한다.** 최신 raw에서는 18건이 Judge에서 자동 처리로 바뀌었고 정답 증가 8건·감소 2건이었다. 규칙 미추출·충돌은 Judge로 보내며 유효 답을 얻지 못하면 오답 처리한다. [변경 문항](results/changed_items.jsonl), [비교 집계](results/comparisons.json), [이전 raw 검증 기록](../raw_evaluation/VALIDATION.md)

## 3. Judge 모델 비교

동일 최신 raw에서 자동 처리 537건·Judge 대상 363건, 프롬프트와 생성 설정을 고정하고 Judge 모델만 바꿨다. 이 비교 실험에서는 length 응답을 모두 Judge로 처리했다.

| 집단 | GPT-4.1-mini | GPT-4o-mini |
|---|---:|---:|
| 전체 | 594/900 (66.00%) | 567/900 (63.00%) |
| 객관식 | 556/847 | 542/847 |
| 주관식 | 38/53 | 25/53 |
| 추론 length | 40/128 | 21/128 |
| 추론 stop | 554/772 | 546/772 |

모델 버전은 각각 `gpt-4.1-mini-2025-04-14`, `gpt-4o-mini-2024-07-18`이다. temperature 0, top_p 1, seed 3407, max_tokens 8을 동일하게 사용했다. 답은 83건에서 달랐고, 4o-mini 기준 정답 증가 5건·감소 32건으로 전체 점수가 3.00%p 낮아졌다. [비교 집계](results/comparisons.json)와 [900문항의 정책별 판정](results/policy_comparison.jsonl)에서 확인할 수 있다.

동일한 추론 출력에서 Judge 모델에 따라 **27문항·3.00%p**의 채점 차이가 발생했다.

## 4. MMMU 규칙 단독과 최종 하이브리드의 차이

최신 raw에서 MMMU 규칙 단독은 **452/900(50.22%)**, 최종 하이브리드는 **600/900(66.67%)**로 **148문항·16.44%p** 차이가 났다. 두 설정은 객관식 파서, Final Answer 보완, 주관식 처리, Judge 사용 여부가 다르다. MMMU 비교에서는 파싱 실패 시 무작위 선택을 끄고 실패를 오답 처리했다. [집계](results/scores.json), [문항별 비교](results/policy_comparison.jsonl)

객관식 Judge에는 선택지와 모델 응답을 제공하며 gold는 별도로 전달하지 않는다. 주관식은 Qwen 방식인 `A=참조답, B=Other Answers`를 사용한 **참조답 동치 판정**이다. [평가 도구 설명](../raw_evaluation/README.md)

## 5. 핵심 결과

- 최신 900문항의 정확도는 **66.67%**이며 과제 기준 67.4%보다 **0.73%p 낮다**.
- H1 불일치 49건에서 Qwen은 검토 답과 **47건 일치**했고, H2의 Final Answer 보완 표본은 **100/100건 일치**했다.
- Final Answer 보완으로 비교 실험의 Judge 대상이 **180건(33.15%) 감소**했다.
- 동일 응답의 Judge 모델 비교에서는 **27문항·3.00%p**, MMMU 규칙 단독과 하이브리드 설정 비교에서는 **148문항·16.44%p** 차이가 났다.

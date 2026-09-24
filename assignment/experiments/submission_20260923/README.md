# 최신 900문항 채점 결과와 실험 근거

`max_new_tokens8192_hakyung`의 900문항을 **v2 + GPT-4.1-mini**로 채점한 결과다. **600/900(66.67%)**, 객관식 **560/847**, 주관식 **40/53**이다.

- [과제 보고서](../../../reports/mmmu_baseline.md): 4절 채점 방식, 5·6절 점수, 7절 격차 분석, 8절 검증 범위.
- [파서 선택과 격차 분석의 실험 근거](#채점-선택-실험): 주장별 실험 조건·관측값·근거 파일.
- [30과목 결과표](results/subject_scores.md), [집계 JSON](results/scores.json), [900문항별 정오](results/item_results.jsonl).
- [정책 비교 집계](results/comparisons.json), [length 경로 변경 문항](results/changed_items.jsonl).
- [900문항 반복 전수 분석](../repetition_20260924/README.md): 반복 비율·시작 위치와 정답률·종료 사유·추출 실패의 관계.
- [60문항 실패 유형 1차 분석](../failure_review_20260924/returned_20260924/results/REPORT.md): 과목별 2건의 챗 검토 라벨을 이용한 원인 분류·가중 집계·개선 방향.
- [문항 검토 자료](../failure_review_20260924/README.md): 원본 이미지·응답 전문·라벨 양식과 검토자용 ZIP.

## 채점 선택 실험

### Qwen 기본 파서와 Final Answer 보완

| 결정 | 관측 결과 | 근거 |
|---|---|---|
| Qwen 규칙을 기본으로 사용 | H1의 파서 불일치 49건에서 검토 답과 Qwen 47건, MMMU 2건 일치 | [H1 보고서](../scoring_lab/legacy_pilot/h1/REPORT.md), [문항별 답 추출 비교](../scoring_lab/legacy_pilot/h1/parser_comparison.jsonl) |
| 객관식 Final Answer 100자 보완 | H2 고정 표본에서 검토 답과 100/100 일치. Qwen 미추출을 보완한 59건도 59/59 일치 | [H2 보고서](../scoring_lab/legacy_pilot/h2/REPORT.md), [문항별 비교](../scoring_lab/legacy_pilot/h2/parser_comparison.jsonl). 정상 종료 객관식의 보완 자동 채택군에 대한 검토 |
| 두 규칙이 충돌하면 Judge로 이동 | 보완 규칙이 답을 제시해도 Qwen과 다른 경우 자동으로 덮어쓰지 않음 | [실제 처리 코드](../raw_evaluation/evaluate.py). 미추출도 Judge로 이동 |

H1·H2는 **과거 899문항 pilot**(생성 seed 42, cap 9048)의 표본 검토다. 검토자 1명이 H1 49건과 H2 100건을 확인했으며, 중복 10건을 제외한 고유 문항은 **139건**이다. H2 표본 선정 seed는 3407이다.

최신 raw에서 주관식·length 정책을 고정한 보완 규칙 비교 실험에서는 Judge 대상이 **543건→363건**으로 줄었다. 추가 자동 처리 184건, 충돌에 따른 Judge 이동 4건으로 **순감소 180건(33.15%)**이다. [비교 결과](results/comparisons.json)

### 처리 경로 비교

| 동일 raw 내 정책 비교 | 게이트 적용 | 게이트 제거 | 변화 |
|---|---:|---:|---:|
| 최신 수신 raw | 594/900 (66.00%) | 600/900 (66.67%) | +6문항 |
| 이전 9/21 raw | 609/900 (67.67%) | 608/900 (67.56%) | −1문항 |

현재 정책은 **추출 성공·충돌 여부로 처리 경로를 정한다.** 최신 raw에서는 18건이 Judge에서 자동 처리로 바뀌었고 정답 증가 8건·감소 2건이었다. 규칙 미추출·충돌은 Judge로 보내며 유효 답을 얻지 못하면 오답 처리한다. [변경 문항](results/changed_items.jsonl), [비교 집계](results/comparisons.json), [이전 raw 검증 기록](../raw_evaluation/README.md#검증-결과)

### Judge 모델 비교

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

### MMMU 규칙 단독과 최종 하이브리드의 차이

최신 raw에서 MMMU 규칙 단독은 **452/900(50.22%)**, 최종 하이브리드는 **600/900(66.67%)**로 **148문항·16.44%p** 차이가 났다. 두 설정은 객관식 파서, Final Answer 보완, 주관식 처리, Judge 사용 여부가 다르다. MMMU 비교에서는 파싱 실패 시 무작위 선택을 끄고 실패를 오답 처리했다. [집계](results/scores.json), [문항별 비교](results/policy_comparison.jsonl)

객관식 Judge에는 선택지와 모델 응답을 제공하며 gold는 별도로 전달하지 않는다. 주관식은 Qwen 방식인 `A=참조답, B=Other Answers`를 사용한 **참조답 동치 판정**이다. [평가 도구 설명](../raw_evaluation/README.md)

## 저장 결과 재현

저장소 루트, Python 3.10 이상에서 평가 도구의 의존성을 설치한다.

```bash
python -m pip install -r assignment/experiments/raw_evaluation/requirements.txt
```

아래 **한 명령**으로 원본·캐시를 검증하고 900문항 채점, 과목별 표, 비교 실험을 재계산해 제출 결과와 대조한다. 출력 폴더는 새 빈 경로를 사용한다.

```bash
python assignment/experiments/submission_20260923/reproduce.py --out assignment/experiments/raw_evaluation/outputs/submission_check --expected assignment/experiments/submission_20260923/results
```

이 명령은 저장된 raw와 해당 raw에 대응하는 Judge 캐시를 검증하고 채점 결과를 재계산한다.

## 입력과 판정의 연결

| 파일 | 용도 |
|---|---|
| `input/raw.jsonl` | 실제 추론 900문항 원본. 문제 ID·prompt·선택지·gold·생성 텍스트·토큰·종료 사유 포함 |
| `input/run_metadata.json` | 수신 당시 모델·데이터 revision, 생성·이미지·환경 설정 및 raw 해시 |
| `input/scoring_config.yaml` | 이번 채점에 고정한 v2 정책과 Judge 모델·파라미터. 과거 추론 설정의 증거는 run_metadata를 사용 |
| `judge/gpt-4.1-mini.jsonl` | 같은 raw의 기존 Judge 응답 363개. v2에서 345개를 사용하고 나머지 18개는 게이트 비교에 사용 |
| `judge/gpt-4o-mini.jsonl` | 같은 raw·게이트 적용 정책의 비교 Judge 응답 363개 |
| `results/` | 재계산 가능한 과목별·문항별 결과와 통제 비교 |
| `reproduce.py` | 기존 평가 도구를 사용해 원본과 요청 해시를 검증하고 저장 응답으로 재집계 |

Raw SHA-256: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`.

입력과 메타데이터는 수신본을 바이트 그대로 보존했다. 추론팀 브랜치 `eval/mmmu-baseline-infer`의 `assignment/runs/max_new_tokens8192_hakyung/`에 있는 동명 파일과도 바이트가 같다. 기존 `assignment/runs/draft/raw.jsonl`과는 다른 실행이다. 그 이전 raw의 v2 점수 **608/900(67.56%)**를 이번 결과와 섞지 않는다.

객관식 `predicted`는 선택지 문자다. 주관식은 `A=참조답 원문`, `B=Other Answers`로 변환한 동치 판정값이다. 최종 추출 실패 36건은 오답 300건에 포함한다.

## 비교 실험을 읽는 방법

- 같은 raw에서 게이트 적용 4.1-mini **594/900**, 제거 **600/900**: 채점 경로만 바꾼 비교.
- 같은 raw·게이트 적용 정책에서 4.1-mini **594/900**, 4o-mini **567/900**: Judge 모델만 바꾼 비교.
- MMMU 규칙 단독 **452/900**과 v2 **600/900**: 파서·주관식 처리·Judge 사용이 함께 다른 파이프라인 비교.
- 기존 H1/H2 사람 검토는 [공개된 과거 실험](../scoring_lab/SUMMARY.md)에 있다. 현재 raw의 전량 추출 정확도 검증으로 해석하지 않는다.

원본 `run_metadata.json`에 기록된 실행 명령은 경로 중복이 있어 그대로 실행 가능한 명령으로 인용하지 않는다. 생성 설정·환경 수치는 원기록으로 보존하되 추론팀의 통합 실행 안내로 보완해야 한다. 보고서 1~3절 초안 역시 추론팀 브랜치에서 별도로 진행 중이다.

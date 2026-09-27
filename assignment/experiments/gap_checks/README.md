# 격차 분석·소요 시간 보조 계산 (baseline 과제)

보고서 1절 분야별 소요 시간 추정과 7절 격차 분석의 수치 근거다. 모두 저장된 결과만 읽으며, 추론이나 Judge 호출을 하지 않는다. 각 결과 JSON에는 입력 파일의 SHA-256이 함께 기록된다. 저장소 루트에서 실행한다.

## 무작위 fallback 기대값

Qwen3-VL 공식 채점 코드([`qwen_eval_utils.py`](../../../code/scoring/frozen/vendor/qwen_eval_utils.py), commit `96588727`)는 규칙 추출이 실패하면 Judge에 최대 25회 재시도를 요청하고, 그래도 답을 얻지 못하면 `선택지 + Z` 중 하나를 무작위로 고른다. 우리 정책은 최종 추출 실패 문항을 오답으로 처리한다. 이 차이가 점수에 주는 영향을 기대값으로 계산했다.

| 항목 | 값 |
|---|---|
| 현재 점수 | 600/900 (66.67%) |
| 추출 실패 | 36건 (4지선다 21, 3지선다 3, 주관식 12) |
| 기대 추가 정답 | 21/5 + 3/4 + 12/3 = 8.95건 |
| 기대 점수 | 67.66% (+0.99%p) |

선택지가 n개인 객관식은 Z를 포함한 n+1개 후보 중 하나이므로 정답 확률이 `1/(n+1)`이다. 주관식은 `A=참조답, B=Other Answers, Z` 중 하나이므로 `1/3`이다. 기대값이므로 실제 한 번의 채점에서는 이보다 크거나 작을 수 있다.

```bash
python assignment/experiments/gap_checks/random_fallback.py --out /tmp/random_fallback.json
```

결과: [`random_fallback.json`](random_fallback.json)

## 분야·과목별 추정 시간

생성은 과목이 섞인 묶음을 vLLM으로 동시에 처리해 과목별 실측 시간이 없다. 기록된 생성 구간(`env.json`의 `invocations[].generate_seconds` = 3,351.217초)을 출력 토큰 비중으로 배분했다. 이미지·텍스트 입력 처리(prefill) 시간은 반영하지 않았다.

| Category | 출력 토큰 | 비중 | 추정 초 |
|---|--:|--:|--:|
| Art & Design | 179,329 | 9.9% | 331 |
| Business | 255,768 | 14.1% | 473 |
| Science | 297,574 | 16.4% | 550 |
| Health & Medicine | 137,503 | 7.6% | 254 |
| Humanities & Social Science | 50,806 | 2.8% | 94 |
| Tech & Engineering | 892,275 | 49.2% | 1,649 |

<details>
<summary>과목 30개 단위 추정</summary>

| Subject | Category | 출력 토큰 | 비중 | 추정 초 |
|---|---|--:|--:|--:|
| Accounting | Business | 88,467 | 4.9% | 164 |
| Agriculture | Tech & Engineering | 4,986 | 0.3% | 9 |
| Architecture_and_Engineering | Tech & Engineering | 188,090 | 10.4% | 348 |
| Art | Art & Design | 21,213 | 1.2% | 39 |
| Art_Theory | Art & Design | 17,004 | 0.9% | 31 |
| Basic_Medical_Science | Health & Medicine | 16,630 | 0.9% | 31 |
| Biology | Science | 40,853 | 2.3% | 76 |
| Chemistry | Science | 87,228 | 4.8% | 161 |
| Clinical_Medicine | Health & Medicine | 16,110 | 0.9% | 30 |
| Computer_Science | Tech & Engineering | 64,824 | 3.6% | 120 |
| Design | Art & Design | 5,607 | 0.3% | 10 |
| Diagnostics_and_Laboratory_Medicine | Health & Medicine | 32,720 | 1.8% | 60 |
| Economics | Business | 23,985 | 1.3% | 44 |
| Electronics | Tech & Engineering | 138,388 | 7.6% | 256 |
| Energy_and_Power | Tech & Engineering | 171,037 | 9.4% | 316 |
| Finance | Business | 74,432 | 4.1% | 138 |
| Geography | Science | 41,091 | 2.3% | 76 |
| History | Humanities & Social Science | 20,137 | 1.1% | 37 |
| Literature | Humanities & Social Science | 5,416 | 0.3% | 10 |
| Manage | Business | 36,851 | 2.0% | 68 |
| Marketing | Business | 32,033 | 1.8% | 59 |
| Materials | Tech & Engineering | 156,461 | 8.6% | 289 |
| Math | Science | 83,446 | 4.6% | 154 |
| Mechanical_Engineering | Tech & Engineering | 168,489 | 9.3% | 311 |
| Music | Art & Design | 135,505 | 7.5% | 250 |
| Pharmacy | Health & Medicine | 38,336 | 2.1% | 71 |
| Physics | Science | 44,956 | 2.5% | 83 |
| Psychology | Humanities & Social Science | 16,224 | 0.9% | 30 |
| Public_Health | Health & Medicine | 33,707 | 1.9% | 62 |
| Sociology | Humanities & Social Science | 9,029 | 0.5% | 17 |

</details>

```bash
python assignment/experiments/gap_checks/time_estimate.py --out /tmp/time_estimate.json
```

결과: [`time_estimate.json`](time_estimate.json)

## 두 8192 실행 비교

재추론하면 무엇이 바뀌는지 보기 위해, 같은 config로 생성한 두 전량 실행(a: [`assignment/runs/draft`](../../runs/draft), b: [`results/mmmu_team_baseline`](../../../results/mmmu_team_baseline/README.md))을 Judge 없는 같은 MMMU 규칙으로 채점해 비교했다.

| 항목 | 값 |
|---|---|
| 전체 정답 (규칙 단독) | a 450 / b 452 |
| 점수가 바뀐 과목 | 25/30 (최대 5문항) |
| 정오가 바뀐 문항 | 164/900 |
| 분야별 토큰 비중의 최대 차이 | 1.4%p |
| 생성 시간 | a 6,026.256초 / b 3,351.217초 |

| Category | 규칙 정확도 a | 규칙 정확도 b | 토큰 비중 a | 토큰 비중 b |
|---|--:|--:|--:|--:|
| Art & Design | 43.3% | 43.3% | 8.8% | 9.9% |
| Business | 70.0% | 69.3% | 14.2% | 14.1% |
| Science | 48.7% | 48.7% | 16.4% | 16.4% |
| Health & Medicine | 54.0% | 52.7% | 8.3% | 7.6% |
| Humanities & Social Science | 50.0% | 55.0% | 4.2% | 2.8% |
| Tech & Engineering | 37.6% | 37.1% | 48.1% | 49.2% |

전체 점수와 분야별 토큰 비중은 안정적이지만, 과목·문항 단위 결과는 크게 바뀐다. 따라서 재추론하면 보고서의 과목별 수치와 분석을 다시 써야 한다. 반면 토큰 비중 기반 시간 추정은 어느 실행을 기준으로 해도 거의 같다. 두 실행은 드라이버·커널이 다른 호스트에서 돌았고, 비슷한 출력량(a 1,737,889 / b 1,813,255토큰)에도 생성 시간이 약 1.8배 달랐다. 원인은 기록으로 확인하지 못했다.

```bash
python -m pip install -r code/scoring/requirements.txt
python assignment/experiments/gap_checks/run_comparison.py --out /tmp/run_comparison.json
```

결과: [`run_comparison.json`](run_comparison.json)

# MMMU parser comparison

**요약: (a)와 (b)는 검증 결과 동일 규칙의 서로 다른 구현으로 확인됨(문항별 diff 0/900) — 이후 비교는 '규칙 기반 파서(a=b)' vs '규칙 기반+GPT-judge fallback(c)'의 2-way 비교로 해석할 것.**

All conditions use the same 900 stored `raw_text` values. Random fallback is forbidden.

| Condition | Correct / 900 | Accuracy | Parse failures | Failure rate |
|---|---:|---:|---:|---:|
| a_custom | 410 / 900 | 45.56% | 86 / 900 | 9.56% |
| b_official_no_random | 410 / 900 | 45.56% | 86 / 900 | 9.56% |
| c_official_then_gpt_judge | — | — | — | — |

| No. | Subject | N | (a) Acc / Fail | (b) Acc / Fail | (c) Acc / Fail |
|---:|---|---:|---:|---:|---:|
| 1 | Accounting | 30 | 50.00% / 1 | 50.00% / 1 | — |
| 2 | Agriculture | 30 | 33.33% / 9 | 33.33% / 9 | — |
| 3 | Architecture_and_Engineering | 30 | 40.00% / 5 | 40.00% / 5 | — |
| 4 | Art | 30 | 43.33% / 5 | 43.33% / 5 | — |
| 5 | Art_Theory | 30 | 60.00% / 3 | 60.00% / 3 | — |
| 6 | Basic_Medical_Science | 30 | 46.67% / 2 | 46.67% / 2 | — |
| 7 | Biology | 30 | 36.67% / 2 | 36.67% / 2 | — |
| 8 | Chemistry | 30 | 30.00% / 6 | 30.00% / 6 | — |
| 9 | Clinical_Medicine | 30 | 43.33% / 0 | 43.33% / 0 | — |
| 10 | Computer_Science | 30 | 40.00% / 2 | 40.00% / 2 | — |
| 11 | Design | 30 | 60.00% / 1 | 60.00% / 1 | — |
| 12 | Diagnostics_and_Laboratory_Medicine | 30 | 20.00% / 1 | 20.00% / 1 | — |
| 13 | Economics | 30 | 60.00% / 2 | 60.00% / 2 | — |
| 14 | Electronics | 30 | 33.33% / 5 | 33.33% / 5 | — |
| 15 | Energy_and_Power | 30 | 30.00% / 10 | 30.00% / 10 | — |
| 16 | Finance | 30 | 63.33% / 3 | 63.33% / 3 | — |
| 17 | Geography | 30 | 36.67% / 1 | 36.67% / 1 | — |
| 18 | History | 30 | 60.00% / 0 | 60.00% / 0 | — |
| 19 | Literature | 30 | 63.33% / 1 | 63.33% / 1 | — |
| 20 | Manage | 30 | 50.00% / 0 | 50.00% / 0 | — |
| 21 | Marketing | 30 | 86.67% / 1 | 86.67% / 1 | — |
| 22 | Materials | 30 | 26.67% / 2 | 26.67% / 2 | — |
| 23 | Math | 30 | 36.67% / 8 | 36.67% / 8 | — |
| 24 | Mechanical_Engineering | 30 | 20.00% / 7 | 20.00% / 7 | — |
| 25 | Music | 30 | 13.33% / 4 | 13.33% / 4 | — |
| 26 | Pharmacy | 30 | 63.33% / 0 | 63.33% / 0 | — |
| 27 | Physics | 30 | 50.00% / 2 | 50.00% / 2 | — |
| 28 | Psychology | 30 | 56.67% / 1 | 56.67% / 1 | — |
| 29 | Public_Health | 30 | 63.33% / 1 | 63.33% / 1 | — |
| 30 | Sociology | 30 | 50.00% / 1 | 50.00% / 1 | — |

## GPT judge

Not run. Set `OPENAI_API_KEY` and run without `--skip-judge`.

## 검증 노트

- (a) 호출 경로: `mmmu_pipeline.scoring.score_generation`
- (b) 호출 경로: `__main__.score_official`
- 서로 다른 함수 객체: `True`
- 코드 판정: 두 함수는 별도 객체이지만 괄호 선택지 → 독립 알파벳 → 선택지 본문 → 마지막 등장 위치, 실패 시 `None`, open 응답 정규화까지 같은 공식 MMMU 규칙의 의미상 동등한 복제본이다. 따라서 독립적인 두 파서 비교가 아니다.
- 문항별 parsed value diff: 0 / 900
- 문항별 정오답·실패 상태 diff: 0 / 900
- 추출 경로 분포: `{"bracketed_choice": 50, "open": 53, "option_text": 437, "parse_failure": 86, "standalone_choice": 274}`
- 결론: 900문항 일치는 raw 응답이 단순해서 생긴 우연이 아니라 두 구현의 알고리즘이 같기 때문이다.
- 따라서 최종 결론은 (a)/(b)를 별도 성능 조건으로 해석하지 않고, `규칙 기반 파서(a=b)`와 `규칙 기반+GPT-judge fallback(c)`의 2-way 비교로 해석한다.

### Raw-text examples

- `option_text` / `Accounting__validation_Accounting_1` → `A`: …ad**, not per unit? But the table says “Average Cost per Unit”, so it’s per unit.  Yes — the table says “Average Cost per Unit”, so the $6 is per unit — but that’s only true if the volume is fixed. But in reality, **fixed costs per unit decrease as volume increases**.  So, the key point: **when the question gives you “
- `standalone_choice` / `Accounting__validation_Accounting_3` → `B`: …NPV_B ≈ -24,000 + 12,260.87 + 7,410.53 + 4,996.68 = -24,000 + 24,668.08 = \boxed{668.08} \]  ---  ## **Comparison:**  - NPV of Project A ≈ **-$141.77** - NPV of Project B ≈ **$668.08**  Since **Project B has a higher NPV**, it is the better choice according to the **NPV rule**.  ---  ## ✅ Final Answer: **B. Project B**
- `parse_failure` / `Accounting__validation_Accounting_15` → `None`: …2,500   +965,000 → 13,027,500   +1,747,500 → 14,775,000   +82,500 → 14,857,500   +952,500 → 15,810,000   -217,500 → 15,592,500   +1,897,500 → **17,490,000**  Σ(x-x̄)^2 =   16M + 0 + 49M + 1M + 9M + 4M + 9M + 1M + 9M + 1M + 0 + 9M   = 16 + 49 + 1 + 9 + 4 + 9 + 1 + 9 + 1 + 9 = let’s add:  16 + 49 = 65   +1 = 66   +9 = 75
- `bracketed_choice` / `Architecture_and_Engineering__validation_Architecture_and_Engineering_9` → `D`: …   A4 = 41.44   A5 = 39.69    Compute:  Sum = 31.24 + 4×24.84 + 2×20.25 + 4×41.44 + 39.69  Calculate step by step:  - 4×24.84 = 99.36 - 2×20.25 = 40.50 - 4×41.44 = 165.76  Total = 31.24 + 99.36 + 40.50 + 165.76 + 39.69  Add:  31.24 + 99.36 = 130.60   130.60 + 40.50 = 171.10   171.10 + 165.76 = 336.86   336.86 + 39.69 =

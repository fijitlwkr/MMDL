# GPT-judge retry analysis

기존 GPU/API 실행 결과를 다시 호출하지 않고 `judge_calls.jsonl`, `judge_summary.json`, `predictions.jsonl`만 읽어 분석했다.

## 무결성 검증

- judge 대상: 로그 86/86, summary 완료 86/86
- API 시도: 로그 139회, summary 139회
- 최종 실패: 마지막 시도 기준 26개, summary 26개, `final_fallback_incorrect` 이벤트 26개 (ID까지 모두 일치)

### 실제 로그 필드 해석

- API 시도 레코드는 `question_id`, `attempt`, `status`, `prompt_tokens`, `completion_tokens`, `call_cost_usd`, `cumulative_cost_usd` 등을 가진다.
- 별도 성공 boolean이나 `error_type` 키는 없고, 성공/실패는 `status`로 판별한다. 이번 API 시도 status는 `success`와 `invalid_response`뿐이다.
- 재시도 이벤트는 `status=retry_scheduled`, `next_attempt`, `reason`으로 기록된다.

## 재시도 사유 분포

| 기록된 reason | 재시도 이벤트 | 비율 |
|---|---|---|
| judge returned an invalid choice | 53 | 100.00% |

이번 실행에서 timeout, HTTP error, rate limit 레코드는 없었다. 기록된 재시도 53회는 모두 judge가 허용 선택지를 내지 않은 `invalid_response`였으며, 해당 API 응답의 `judge_output`은 전부 `INVALID`, 기록된 reason은 `judge returned an invalid choice`였다.

### 문항당 시도 횟수

| 시도 횟수 | 문항 수 | 86문항 중 비율 |
|---|---|---|
| 1 | 59 | 68.60% |
| 2 | 1 | 1.16% |
| 3 | 26 | 30.23% |

## 재시도 집중 조건

| 그룹 | 문항 | 평균 prompt tok | 중앙값 | p90 | 최대 |
|---|---|---|---|---|---|
| 1회 시도 | 59 | 976.2 | 444 | 2339.2 | 2523 |
| 재시도 발생 | 27 | 2190.5 | 2252 | 2450.8 | 2504 |

- 입력 토큰 최장 25%(22문항)의 재시도율은 54.55%(12/22)이고, 나머지 64문항은 23.44%(15/64)였다.
- 재시도군의 평균/중앙 입력 토큰은 2190.5/2252, 단일 시도군은 976.2/444였다.
- 관찰: 최장 25%의 재시도율은 나머지 문항의 2.33배여서, 이번 표본에서는 재시도가 긴 입력에 뚜렷하게 집중됐다. 이는 관찰적 연관이며 입력 길이가 원인임을 단독으로 입증하지는 않는다.

### 재시도가 발생한 과목

| 과목 | judge 문항 | 재시도 문항 | 재시도율 | 추가 호출 |
|---|---|---|---|---|
| Energy_and_Power | 10 | 6 | 60.00% | 12 |
| Mechanical_Engineering | 7 | 4 | 57.14% | 8 |
| Math | 8 | 4 | 50.00% | 7 |
| Finance | 3 | 3 | 100.00% | 6 |
| Chemistry | 6 | 2 | 33.33% | 4 |
| Materials | 2 | 2 | 100.00% | 4 |
| Accounting | 1 | 1 | 100.00% | 2 |
| Agriculture | 9 | 1 | 11.11% | 2 |
| Biology | 2 | 1 | 50.00% | 2 |
| Computer_Science | 2 | 1 | 50.00% | 2 |
| Electronics | 5 | 1 | 20.00% | 2 |
| Marketing | 1 | 1 | 100.00% | 2 |

### 입력 토큰 상위 10문항

| question_id | 과목 | prompt tok | 시도 |
|---|---|---|---|
| Computer_Science__validation_Computer_Science_18 | Computer_Science | 2523 | 1 |
| Math__validation_Math_12 | Math | 2504 | 3 |
| Mechanical_Engineering__validation_Mechanical_Engineering_29 | Mechanical_Engineering | 2466 | 3 |
| Chemistry__validation_Chemistry_17 | Chemistry | 2455 | 3 |
| Mechanical_Engineering__validation_Mechanical_Engineering_6 | Mechanical_Engineering | 2448 | 3 |
| Electronics__validation_Electronics_9 | Electronics | 2420 | 3 |
| Electronics__validation_Electronics_14 | Electronics | 2419 | 1 |
| Biology__validation_Biology_14 | Biology | 2407 | 3 |
| Economics__validation_Economics_19 | Economics | 2402 | 1 |
| Mechanical_Engineering__validation_Mechanical_Engineering_9 | Mechanical_Engineering | 2393 | 1 |

과목별로는 `Energy_and_Power`가 6/10문항으로 재시도 문항 수가 가장 많았다. `Finance`(3/3), `Materials`(2/2), `Accounting`(1/1)은 비율이 100%지만 judge 대상 표본 수가 작다.

## 최종 실패 문항과 finish_reason

| finish_reason | 문항 수 | 최종 실패 중 비율 |
|---|---|---|
| length | 25 | 96.15% |
| stop | 1 | 3.85% |

| question_id | 과목 | finish_reason |
|---|---|---|
| Accounting__validation_Accounting_15 | Accounting | length |
| Agriculture__validation_Agriculture_16 | Agriculture | stop |
| Biology__validation_Biology_14 | Biology | length |
| Chemistry__validation_Chemistry_17 | Chemistry | length |
| Chemistry__validation_Chemistry_24 | Chemistry | length |
| Computer_Science__validation_Computer_Science_12 | Computer_Science | length |
| Electronics__validation_Electronics_9 | Electronics | length |
| Energy_and_Power__validation_Energy_and_Power_14 | Energy_and_Power | length |
| Energy_and_Power__validation_Energy_and_Power_16 | Energy_and_Power | length |
| Energy_and_Power__validation_Energy_and_Power_18 | Energy_and_Power | length |
| Energy_and_Power__validation_Energy_and_Power_19 | Energy_and_Power | length |
| Energy_and_Power__validation_Energy_and_Power_25 | Energy_and_Power | length |
| Energy_and_Power__validation_Energy_and_Power_26 | Energy_and_Power | length |
| Finance__validation_Finance_14 | Finance | length |
| Finance__validation_Finance_21 | Finance | length |
| Finance__validation_Finance_5 | Finance | length |
| Marketing__validation_Marketing_12 | Marketing | length |
| Materials__validation_Materials_25 | Materials | length |
| Materials__validation_Materials_27 | Materials | length |
| Math__validation_Math_12 | Math | length |
| Math__validation_Math_17 | Math | length |
| Math__validation_Math_20 | Math | length |
| Mechanical_Engineering__validation_Mechanical_Engineering_11 | Mechanical_Engineering | length |
| Mechanical_Engineering__validation_Mechanical_Engineering_29 | Mechanical_Engineering | length |
| Mechanical_Engineering__validation_Mechanical_Engineering_6 | Mechanical_Engineering | length |
| Mechanical_Engineering__validation_Mechanical_Engineering_8 | Mechanical_Engineering | length |

## 결론

GPT-judge로도 구제되지 않은 최종 실패 26개 중 생성 길이 초과(`finish_reason=length`)는 25개, 96.15%였다.

## 부록: 86문항별 API 시도

| question_id | 과목 | 시도 | 첫 prompt tok | 시도 status | 재시도 reason |
|---|---|---|---|---|---|
| Accounting__validation_Accounting_15 | Accounting | 3 | 1856 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Agriculture__validation_Agriculture_16 | Agriculture | 3 | 132 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Agriculture__validation_Agriculture_17 | Agriculture | 1 | 142 | success | — |
| Agriculture__validation_Agriculture_18 | Agriculture | 1 | 139 | success | — |
| Agriculture__validation_Agriculture_20 | Agriculture | 1 | 160 | success | — |
| Agriculture__validation_Agriculture_24 | Agriculture | 1 | 145 | success | — |
| Agriculture__validation_Agriculture_26 | Agriculture | 1 | 139 | success | — |
| Agriculture__validation_Agriculture_29 | Agriculture | 1 | 133 | success | — |
| Agriculture__validation_Agriculture_3 | Agriculture | 1 | 141 | success | — |
| Agriculture__validation_Agriculture_5 | Agriculture | 1 | 130 | success | — |
| Architecture_and_Engineering__validation_Architecture_and_Engineering_10 | Architecture_and_Engineering | 1 | 2265 | success | — |
| Architecture_and_Engineering__validation_Architecture_and_Engineering_16 | Architecture_and_Engineering | 1 | 2081 | success | — |
| Architecture_and_Engineering__validation_Architecture_and_Engineering_17 | Architecture_and_Engineering | 1 | 1944 | success | — |
| Architecture_and_Engineering__validation_Architecture_and_Engineering_2 | Architecture_and_Engineering | 1 | 1895 | success | — |
| Architecture_and_Engineering__validation_Architecture_and_Engineering_6 | Architecture_and_Engineering | 1 | 2213 | success | — |
| Art_Theory__validation_Art_Theory_11 | Art_Theory | 1 | 114 | success | — |
| Art_Theory__validation_Art_Theory_30 | Art_Theory | 1 | 127 | success | — |
| Art_Theory__validation_Art_Theory_4 | Art_Theory | 1 | 120 | success | — |
| Art__validation_Art_10 | Art | 1 | 127 | success | — |
| Art__validation_Art_16 | Art | 1 | 102 | success | — |
| Art__validation_Art_25 | Art | 1 | 124 | success | — |
| Art__validation_Art_4 | Art | 1 | 120 | success | — |
| Art__validation_Art_7 | Art | 1 | 102 | success | — |
| Basic_Medical_Science__validation_Basic_Medical_Science_13 | Basic_Medical_Science | 1 | 761 | success | — |
| Basic_Medical_Science__validation_Basic_Medical_Science_26 | Basic_Medical_Science | 1 | 101 | success | — |
| Biology__validation_Biology_14 | Biology | 3 | 2407 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Biology__validation_Biology_20 | Biology | 1 | 2323 | success | — |
| Chemistry__validation_Chemistry_10 | Chemistry | 1 | 756 | success | — |
| Chemistry__validation_Chemistry_15 | Chemistry | 1 | 975 | success | — |
| Chemistry__validation_Chemistry_17 | Chemistry | 3 | 2455 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Chemistry__validation_Chemistry_24 | Chemistry | 3 | 1944 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Chemistry__validation_Chemistry_26 | Chemistry | 1 | 2294 | success | — |
| Chemistry__validation_Chemistry_29 | Chemistry | 1 | 2389 | success | — |
| Computer_Science__validation_Computer_Science_12 | Computer_Science | 3 | 2241 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Computer_Science__validation_Computer_Science_18 | Computer_Science | 1 | 2523 | success | — |
| Design__validation_Design_23 | Design | 1 | 129 | success | — |
| Diagnostics_and_Laboratory_Medicine__validation_Diagnostics_and_Laboratory_Medicine_25 | Diagnostics_and_Laboratory_Medicine | 1 | 91 | success | — |
| Economics__validation_Economics_11 | Economics | 1 | 444 | success | — |
| Economics__validation_Economics_19 | Economics | 1 | 2402 | success | — |
| Electronics__validation_Electronics_13 | Electronics | 1 | 737 | success | — |
| Electronics__validation_Electronics_14 | Electronics | 1 | 2419 | success | — |
| Electronics__validation_Electronics_15 | Electronics | 1 | 681 | success | — |
| Electronics__validation_Electronics_8 | Electronics | 1 | 700 | success | — |
| Electronics__validation_Electronics_9 | Electronics | 3 | 2420 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_11 | Energy_and_Power | 1 | 1155 | success | — |
| Energy_and_Power__validation_Energy_and_Power_12 | Energy_and_Power | 1 | 2333 | success | — |
| Energy_and_Power__validation_Energy_and_Power_13 | Energy_and_Power | 1 | 2204 | success | — |
| Energy_and_Power__validation_Energy_and_Power_14 | Energy_and_Power | 3 | 2235 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_16 | Energy_and_Power | 3 | 2285 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_18 | Energy_and_Power | 3 | 2179 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_19 | Energy_and_Power | 3 | 2273 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_25 | Energy_and_Power | 3 | 2252 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_26 | Energy_and_Power | 3 | 2199 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Energy_and_Power__validation_Energy_and_Power_3 | Energy_and_Power | 1 | 2148 | success | — |
| Finance__validation_Finance_14 | Finance | 3 | 2345 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Finance__validation_Finance_21 | Finance | 3 | 2201 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Finance__validation_Finance_5 | Finance | 3 | 2240 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Geography__validation_Geography_7 | Geography | 1 | 313 | success | — |
| Literature__validation_Literature_5 | Literature | 1 | 122 | success | — |
| Marketing__validation_Marketing_12 | Marketing | 3 | 2238 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Materials__validation_Materials_25 | Materials | 3 | 2111 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Materials__validation_Materials_27 | Materials | 3 | 2317 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Math__validation_Math_12 | Math | 3 | 2504 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Math__validation_Math_17 | Math | 3 | 2371 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Math__validation_Math_2 | Math | 2 | 2325 | invalid_response, success | judge returned an invalid choice |
| Math__validation_Math_20 | Math | 3 | 2365 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Math__validation_Math_21 | Math | 1 | 2293 | success | — |
| Math__validation_Math_25 | Math | 1 | 1698 | success | — |
| Math__validation_Math_8 | Math | 1 | 2125 | success | — |
| Math__validation_Math_9 | Math | 1 | 91 | success | — |
| Mechanical_Engineering__validation_Mechanical_Engineering_11 | Mechanical_Engineering | 3 | 2161 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Mechanical_Engineering__validation_Mechanical_Engineering_20 | Mechanical_Engineering | 1 | 2223 | success | — |
| Mechanical_Engineering__validation_Mechanical_Engineering_22 | Mechanical_Engineering | 1 | 2364 | success | — |
| Mechanical_Engineering__validation_Mechanical_Engineering_29 | Mechanical_Engineering | 3 | 2466 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Mechanical_Engineering__validation_Mechanical_Engineering_6 | Mechanical_Engineering | 3 | 2448 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Mechanical_Engineering__validation_Mechanical_Engineering_8 | Mechanical_Engineering | 3 | 2173 | invalid_response, invalid_response, invalid_response | judge returned an invalid choice; judge returned an invalid choice |
| Mechanical_Engineering__validation_Mechanical_Engineering_9 | Mechanical_Engineering | 1 | 2393 | success | — |
| Music__validation_Music_12 | Music | 1 | 91 | success | — |
| Music__validation_Music_2 | Music | 1 | 91 | success | — |
| Music__validation_Music_29 | Music | 1 | 114 | success | — |
| Music__validation_Music_5 | Music | 1 | 91 | success | — |
| Physics__validation_Physics_28 | Physics | 1 | 471 | success | — |
| Physics__validation_Physics_29 | Physics | 1 | 397 | success | — |
| Psychology__validation_Psychology_1 | Psychology | 1 | 359 | success | — |
| Public_Health__validation_Public_Health_24 | Public_Health | 1 | 1952 | success | — |
| Sociology__validation_Sociology_6 | Sociology | 1 | 378 | success | — |

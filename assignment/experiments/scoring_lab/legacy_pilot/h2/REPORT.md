# H2 Final Answer 자동 채택 — 반환 라벨 분석

## 결과

고정된 H2 표본 100건의 사용자 반환 라벨을 검증하고 동일 파서를 재실행했다. **검토 답과 100/100개 일치**, 추출 불일치 0개다. 특히 기존 Qwen이 추출하지 못한 추가 채택군은 59/59개가 일치했다.

| 집단 | 검토 답과 일치 | 관측 추출 충실도 | Wilson 95% 구간 |
|---|---:|---:|---:|
| H2 전체 표본 | 100/100 | 100.00% | 96.30%–100.00% |
| Qwen 실패 → marker 추가 채택 | 59/59 | 100.00% | 93.89%–100.00% |
| 기존 Qwen도 성공 | 41/41 | 100.00% | 91.43%–100.00% |

이는 **원문에서 모델이 최종적으로 낸 답을 제대로 읽었는지**의 결과다. 실제 문제의 정답률, MMMU 점수 또는 Judge의 정확도가 아니다. 기존 10개 H1 라벨과 이번 90개 H2 라벨을 합친 고정 표본 100건이며, H1 49개 전체를 이 분모에 더하지 않았다.

## 검증과 출처

- 고유 ID 100개·분석 ID·번호·원문 SHA-256·유효 답·근거 문장의 원문 일치가 모두 확인됐다. 재사용한 H1 10개 판정은 그대로다.
- 기존 모집단 305개에서 seed 3407로 선정한 표본 목록을 재현했다. 표본을 바꾸거나 답을 고쳐 쓰지 않았다.
- 동일 파서를 다시 실행해 100개가 marker 자동 채택 조건을 만족하며 Qwen 추가 구제 59개/기존 성공 41개임을 확인했다. H1 당시 파서 소스 해시와 같다.
- 반환 파일은 전부 `human_confirmed`, 검토자 `yoonseok`, `adjudicated=false`다. 사용자 신고 검토 출처를 보존했으며 **단일 검토자 결과**다. 독립 2인 검증·조정 완료로 표현하지 않는다.
- 원본 반환 파일의 바이트를 별도 보존했다. 기존 파서·Judge·캐시는 변경하지 않았다. 신규 API 호출과 재추론은 0이다. Pod에는 이번 반환 자료를 동기화하지 않았다.

## 무엇을 판단할 수 있나

이 표본은 **Qwen 규칙 + 기존 Final Answer 100자 보완 규칙을 후보로 유지할 근거를 강화한다.** 기존 Qwen이 읽지 못한 59건의 추가 추출도 사용자 판정과 일치했다. H1의 Qwen 47/49, MMMU 2/49 결과와 함께 보면 파싱 실패율만 보고 MMMU로 교체하는 것보다 Qwen을 기본으로 보완하는 방향이 타당하다.

제안했던 99% 점 추정 목표와 관측치를 비교할 수는 있지만, 기준이 사전 확정되지 않았으므로 사전 등록된 가설 검증 완료라고 쓰지 않는다. 모집단이나 미래 응답의 추출 충실도가 99% 이상이라고 보장하지 않는다. 95% 구간은 계획한 일반 Wilson 방법이며 비복원 표본의 유한모집단 보정을 적용하지 않았다. 라벨러 오판·모델/환경 변화는 이 구간에 반영되지 않는다.

기존 899건 pilot에서 Judge 대상은 Qwen 503건 → hybrid100 327건으로 176건(34.99%) 줄었다. 이는 앞선 라우팅 집계이며 이번 100건에서 새로 측정한 비용 절감이나 전량 채점 완료 수치가 아니다.

## 남아 있는 한계와 후속

- H2는 **정상 종료 객관식 중 유효 marker와 자동 채택이 함께 있는 군**만 검토한다. marker가 없는 Qwen 자동 채택, open 응답, length 응답, Judge 출력 전체의 검증이 아니다.
- H1 `validation_Chemistry_18`에서는 여전히 hybrid가 D 대신 C를 잘못 자동 채택한다. `Correct Answer:` 형식이 기존 marker에 잡히지 않은 사례로, H2 모집단에 포함되지 않는다.
- 합성 반례 `Final Answer: A or B.`의 오독 가능성도 남아 있다. 표본에서 오류가 없었다고 이 반례가 해결된 것은 아니다. 규칙을 바꾼다면 새 버전 후보로 분리하고 별도 자료로 검증한다.
- `length`는 항상 Judge로 보내고 random fallback은 금지하는 기존 방침을 유지한다. 다음 분석은 H3의 length 진단이며 Judge 정확성 육안 검증은 사용자 범위 밖이다.
- 이 자료는 seed 42/cap 9048의 legacy-pilot이다. 최종 HF pinned revision/seed 3407 프로토콜의 검증을 대신하지 않는다.

## 산출물

`returned_review_original.json`(반환 원본), `human_labels_full.jsonl`(원문과 라벨), `parser_comparison.jsonl`(문항별 비교), `summary.json`(집계·검증·해시).

## 문항별 비교

| 표본 번호 | ID | 사용자 검토 답 | Qwen | hybrid100 | 비교 |
|---|---|---|---|---|---|
| 1 | `validation_Art_Theory_13` | B | B | B | 일치 |
| 2 | `validation_Math_23` | A | A | A | 일치 |
| 3 | `validation_Chemistry_9` | B | B | B | 일치 |
| 4 | `validation_Literature_21` | C | C | C | 일치 |
| 5 | `validation_Diagnostics_and_Laboratory_Medicine_5` | C | 추출 실패 | C | 일치 |
| 6 | `validation_Materials_5` | B | 추출 실패 | B | 일치 |
| 7 | `validation_History_2` | A | 추출 실패 | A | 일치 |
| 8 | `validation_Manage_6` | B | 추출 실패 | B | 일치 |
| 9 | `validation_Energy_and_Power_16` | B | B | B | 일치 |
| 10 | `validation_Pharmacy_15` | A | 추출 실패 | A | 일치 |
| 11 | `validation_Physics_28` | D | D | D | 일치 |
| 12 | `validation_Materials_8` | A | 추출 실패 | A | 일치 |
| 13 | `validation_Energy_and_Power_6` | C | 추출 실패 | C | 일치 |
| 14 | `validation_Finance_19` | C | C | C | 일치 |
| 15 | `validation_Economics_13` | A | 추출 실패 | A | 일치 |
| 16 | `validation_Biology_4` | B | B | B | 일치 |
| 17 | `validation_History_11` | D | 추출 실패 | D | 일치 |
| 18 | `validation_Design_29` | B | B | B | 일치 |
| 19 | `validation_History_9` | B | 추출 실패 | B | 일치 |
| 20 | `validation_Chemistry_1` | B | B | B | 일치 |
| 21 | `validation_Chemistry_26` | C | 추출 실패 | C | 일치 |
| 22 | `validation_Economics_11` | B | 추출 실패 | B | 일치 |
| 23 | `validation_Literature_25` | B | 추출 실패 | B | 일치 |
| 24 | `validation_Agriculture_9` | B | B | B | 일치 |
| 25 | `validation_Public_Health_27` | A | 추출 실패 | A | 일치 |
| 26 | `validation_Geography_12` | A | 추출 실패 | A | 일치 |
| 27 | `validation_Architecture_and_Engineering_25` | A | 추출 실패 | A | 일치 |
| 28 | `validation_Agriculture_25` | E | E | E | 일치 |
| 29 | `validation_Computer_Science_10` | D | D | D | 일치 |
| 30 | `validation_Electronics_20` | C | 추출 실패 | C | 일치 |
| 31 | `validation_Pharmacy_5` | D | 추출 실패 | D | 일치 |
| 32 | `validation_Geography_27` | A | 추출 실패 | A | 일치 |
| 33 | `validation_Clinical_Medicine_13` | C | 추출 실패 | C | 일치 |
| 34 | `validation_Diagnostics_and_Laboratory_Medicine_28` | D | 추출 실패 | D | 일치 |
| 35 | `validation_Physics_10` | A | 추출 실패 | A | 일치 |
| 36 | `validation_Music_18` | B | 추출 실패 | B | 일치 |
| 37 | `validation_Accounting_9` | C | 추출 실패 | C | 일치 |
| 38 | `validation_Materials_1` | A | 추출 실패 | A | 일치 |
| 39 | `validation_Pharmacy_13` | B | B | B | 일치 |
| 40 | `validation_Energy_and_Power_26` | B | B | B | 일치 |
| 41 | `validation_Literature_28` | D | 추출 실패 | D | 일치 |
| 42 | `validation_Basic_Medical_Science_3` | B | B | B | 일치 |
| 43 | `validation_Energy_and_Power_11` | B | B | B | 일치 |
| 44 | `validation_Math_2` | C | 추출 실패 | C | 일치 |
| 45 | `validation_Chemistry_27` | C | C | C | 일치 |
| 46 | `validation_Accounting_23` | B | 추출 실패 | B | 일치 |
| 47 | `validation_Sociology_21` | A | 추출 실패 | A | 일치 |
| 48 | `validation_Architecture_and_Engineering_10` | C | C | C | 일치 |
| 49 | `validation_Geography_8` | A | 추출 실패 | A | 일치 |
| 50 | `validation_Computer_Science_1` | D | D | D | 일치 |
| 51 | `validation_Basic_Medical_Science_4` | D | D | D | 일치 |
| 52 | `validation_History_21` | A | 추출 실패 | A | 일치 |
| 53 | `validation_Public_Health_26` | C | 추출 실패 | C | 일치 |
| 54 | `validation_Physics_7` | D | 추출 실패 | D | 일치 |
| 55 | `validation_Clinical_Medicine_11` | D | 추출 실패 | D | 일치 |
| 56 | `validation_Energy_and_Power_3` | C | C | C | 일치 |
| 57 | `validation_Accounting_7` | B | B | B | 일치 |
| 58 | `validation_Mechanical_Engineering_5` | A | A | A | 일치 |
| 59 | `validation_Mechanical_Engineering_30` | B | 추출 실패 | B | 일치 |
| 60 | `validation_Art_19` | A | 추출 실패 | A | 일치 |
| 61 | `validation_Geography_20` | C | C | C | 일치 |
| 62 | `validation_Marketing_9` | C | C | C | 일치 |
| 63 | `validation_Music_13` | C | 추출 실패 | C | 일치 |
| 64 | `validation_Accounting_1` | B | 추출 실패 | B | 일치 |
| 65 | `validation_Accounting_13` | C | C | C | 일치 |
| 66 | `validation_Architecture_and_Engineering_21` | A | A | A | 일치 |
| 67 | `validation_Electronics_1` | A | A | A | 일치 |
| 68 | `validation_Physics_15` | C | 추출 실패 | C | 일치 |
| 69 | `validation_Biology_26` | E | 추출 실패 | E | 일치 |
| 70 | `validation_Computer_Science_25` | D | 추출 실패 | D | 일치 |
| 71 | `validation_Diagnostics_and_Laboratory_Medicine_14` | B | 추출 실패 | B | 일치 |
| 72 | `validation_Basic_Medical_Science_15` | C | C | C | 일치 |
| 73 | `validation_Physics_12` | D | D | D | 일치 |
| 74 | `validation_Math_10` | C | 추출 실패 | C | 일치 |
| 75 | `validation_Psychology_30` | A | A | A | 일치 |
| 76 | `validation_Biology_12` | A | 추출 실패 | A | 일치 |
| 77 | `validation_Marketing_3` | D | 추출 실패 | D | 일치 |
| 78 | `validation_Design_1` | C | C | C | 일치 |
| 79 | `validation_Music_22` | B | 추출 실패 | B | 일치 |
| 80 | `validation_Marketing_19` | B | B | B | 일치 |
| 81 | `validation_Math_25` | C | C | C | 일치 |
| 82 | `validation_Art_3` | C | 추출 실패 | C | 일치 |
| 83 | `validation_Art_Theory_16` | A | 추출 실패 | A | 일치 |
| 84 | `validation_Design_8` | C | 추출 실패 | C | 일치 |
| 85 | `validation_Materials_7` | A | A | A | 일치 |
| 86 | `validation_Sociology_24` | A | 추출 실패 | A | 일치 |
| 87 | `validation_Architecture_and_Engineering_16` | A | 추출 실패 | A | 일치 |
| 88 | `validation_Music_5` | B | 추출 실패 | B | 일치 |
| 89 | `validation_Art_26` | D | D | D | 일치 |
| 90 | `validation_Diagnostics_and_Laboratory_Medicine_1` | E | E | E | 일치 |
| 91 | `validation_Math_7` | C | 추출 실패 | C | 일치 |
| 92 | `validation_Sociology_28` | A | 추출 실패 | A | 일치 |
| 93 | `validation_Biology_9` | A | 추출 실패 | A | 일치 |
| 94 | `validation_Math_29` | A | 추출 실패 | A | 일치 |
| 95 | `validation_Clinical_Medicine_22` | D | 추출 실패 | D | 일치 |
| 96 | `validation_Physics_19` | A | 추출 실패 | A | 일치 |
| 97 | `validation_Literature_3` | C | 추출 실패 | C | 일치 |
| 98 | `validation_Marketing_24` | C | C | C | 일치 |
| 99 | `validation_Literature_17` | B | B | B | 일치 |
| 100 | `validation_Economics_25` | C | C | C | 일치 |

# H1 반환 라벨 검증 및 파서 비교 — 2026-09-19

## 결과

사용자가 반환한 **49건의 사람 확인 라벨**을 원본과 대조하고 고정된 파서를 다시 실행했다. ID·분석 ID·원문 SHA-256·근거 문장·유효 선택지 모두 통과했다. 최초 2개 라벨도 그대로다. 라벨은 파일에 `human_confirmed`, 검토자 `yoonseok`으로 기록된 내용을 보존했다. **단일 검토자 결과이며 두 사람의 독립 검토·조정 결과는 아니다**(`adjudicated=false` 49건).

| 방식 | 검토 답과 일치 | 자동 추출 불일치 | Judge로 이동 |
|---|---:|---:|---:|
| Qwen 규칙 | 47/49 (95.92%) | 2 | 0 |
| MMMU 규칙 + 랜덤 폴백 제거 | 2/49 (4.08%) | 47 | 0 |
| 기존 hybrid100 | 47/49 | 1 | 1 |

모두 **두 파서가 서로 다른 답을 낸 49문항 안에서의 추출 비교**다. 문제의 GT 정답률이나 전체 MMMU 정확도가 아니다. Hybrid의 Judge 대상은 실제 호출하지 않았으며 성공으로 세지 않았다. 이번 처리의 신규 API 비용과 재추론은 0이다.

## 남은 두 사례

- `validation_Physics_8`: 검토 답 A, Qwen C, MMMU A. 기존 hybrid는 Final Answer의 A와 충돌해 Judge로 넘긴다.
- `validation_Chemistry_18`: 검토 답 D, Qwen C, MMMU D. 기존 hybrid도 C를 자동 채택한다. 원문은 `Correct Answer: D`인데 기존 Final Answer 규칙이 이 형식을 잡지 못한다. 이 사례는 현재 방식의 오독이 남아 있음을 보여준다.

## 해석과 다음 단계

이 불일치군에서는 **Qwen을 기본으로 두는 쪽을 지지**한다. MMMU의 낮은 파싱 실패율만으로 교체를 결정할 수 없다. 다만 Qwen만 성공한 군·MMMU만 성공한 군과 두 파서가 일치한 군의 추출 정확도는 이번에 검증하지 않았다.

기존 pilot에서 공동 추출 성공군 일치율은 267/316=84.49%였다. “대부분”의 임계값이 사전에 확정되지 않았으므로 이를 사전 등록된 95% 기준의 공식 기각 결과로 쓰지 않는다. 49건의 검토 결과는 앞선 AI 결론부 예비 검토 47:2와 같지만, 근거 파일과 검토 출처를 별도 보존한다.

**H2 Final Answer 자동 채택 표본 100건은 별도 검토가 남아 있다.** 이 H1 결과를 H2의 99% 추출 충실도나 최종 baseline 확정 근거로 대신하지 않는다. H1과 H2의 중복 10건은 선정 파일의 ID·해시를 대조한 뒤 재사용할 수 있다. 오류를 본 뒤 규칙을 수정한다면 새 후보로 분리하고 별도 표본 또는 최종 HF raw에서 검증한다.

자료는 당시 seed 42/cap 9048의 legacy-pilot이다. 팀 최종 HF/seed 3407 평가로 일반화하지 않는다. 기존 파서·Judge·캐시는 변경하지 않았고, 반환 파일은 로컬에 보존했다. Pod에는 아직 동기화하지 않았다.

## 산출물

- `returned_review_original.json`: 반환 파일 원본 바이트 보존.
- `human_labels_full.jsonl`: 원문·선택지와 반환 라벨을 결합한 49건. 사람 판정을 변경하지 않음.
- `parser_comparison.jsonl`: 동일 원문을 고정 파서로 재실행한 문항별 결과.
- `summary.json`: 검증 결과·집계·입력과 코드 해시.

## 49문항 대조표

| 번호 | ID | 검토 답 | Qwen | MMMU(no random) | 기존 hybrid100 |
|---|---|---|---|---|---|
| 1 | `validation_Physics_24` | C | C | A | C |
| 2 | `validation_Economics_15` | B | B | A | B |
| 3 | `validation_Design_11` | B | B | D | B |
| 4 | `validation_Public_Health_5` | C | C | B | C |
| 5 | `validation_Basic_Medical_Science_25` | A | A | C | A |
| 6 | `validation_Sociology_1` | C | C | B | C |
| 7 | `validation_Design_21` | D | D | A | D |
| 8 | `validation_Physics_12` | D | D | A | D |
| 9 | `validation_Literature_4` | D | D | C | D |
| 10 | `validation_Biology_13` | C | C | B | C |
| 11 | `validation_Psychology_30` | A | A | E | A |
| 12 | `validation_Computer_Science_13` | D | D | C | D |
| 13 | `validation_Design_13` | B | B | D | B |
| 14 | `validation_Physics_13` | B | B | C | B |
| 15 | `validation_Design_30` | C | C | D | C |
| 16 | `validation_History_26` | C | C | D | C |
| 17 | `validation_History_7` | B | B | D | B |
| 18 | `validation_Biology_3` | B | B | A | B |
| 19 | `validation_Architecture_and_Engineering_10` | C | C | A | C |
| 20 | `validation_Design_18` | C | C | D | C |
| 21 | `validation_Design_2` | A | A | D | A |
| 22 | `validation_Biology_30` | F | F | B | F |
| 23 | `validation_Basic_Medical_Science_4` | D | D | A | D |
| 24 | `validation_Energy_and_Power_27` | C | C | A | C |
| 25 | `validation_Architecture_and_Engineering_21` | A | A | C | A |
| 26 | `validation_Physics_8` | A | C | A | Judge |
| 27 | `validation_Art_22` | B | B | D | B |
| 28 | `validation_Psychology_1` | A | A | E | A |
| 29 | `validation_Physics_4` | D | D | A | D |
| 30 | `validation_Physics_20` | B | B | A | B |
| 31 | `validation_Design_1` | C | C | D | C |
| 32 | `validation_Design_29` | B | B | C | B |
| 33 | `validation_Economics_22` | B | B | A | B |
| 34 | `validation_Pharmacy_22` | A | A | B | A |
| 35 | `validation_Electronics_22` | C | C | B | C |
| 36 | `validation_Biology_4` | B | B | A | B |
| 37 | `validation_Energy_and_Power_3` | C | C | A | C |
| 38 | `validation_Clinical_Medicine_21` | B | B | A | B |
| 39 | `validation_Public_Health_18` | C | C | B | C |
| 40 | `validation_Chemistry_18` | D | C | D | C |
| 41 | `validation_Materials_15` | C | C | A | C |
| 42 | `validation_Music_26` | B | B | A | B |
| 43 | `validation_Art_8` | C | C | A | C |
| 44 | `validation_Sociology_3` | A | A | D | A |
| 45 | `validation_Materials_21` | A | A | D | A |
| 46 | `validation_Geography_25` | A | A | D | A |
| 47 | `validation_Chemistry_9` | B | B | A | B |
| 48 | `validation_Physics_2` | C | C | A | C |
| 49 | `validation_Chemistry_28` | A | A | B | A |

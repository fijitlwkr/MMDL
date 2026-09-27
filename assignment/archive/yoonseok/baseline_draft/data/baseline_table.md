# MMMU MC 파서 비교 결과

> 저장된 예측을 재채점한 분석용 결과입니다. Open 문항을 A=정답, B=Other Answers로 변환했습니다.
> 최종 MC+open 점수는 eval_val.json을 확인하세요.

- 입력 SHA-256: `703566880510a0b1e656e0256932a20d448a4b1b15f4f469a3401ccb29536153`
- 전체 validation 구성: `True`
- 데이터 오류 문항: 1개 (오답 처리, 예비 결과)
- 점수 단위: 아래 표는 %, JSON의 accuracy는 0~1

| Subject | Data Num | Acc (%) |
|---|---:|---:|
| Accounting | 30 | 63.33 |
| Agriculture | 30 | 33.33 |
| Architecture_and_Engineering | 30 | 30.00 |
| Art | 30 | 46.67 |
| Art_Theory | 30 | 43.33 |
| Basic_Medical_Science | 30 | 60.00 |
| Biology | 30 | 50.00 |
| Chemistry | 30 | 43.33 |
| Clinical_Medicine | 30 | 36.67 |
| Computer_Science | 30 | 56.67 |
| Design | 30 | 66.67 |
| Diagnostics_and_Laboratory_Medicine | 30 | 23.33 |
| Economics | 30 | 76.67 |
| Electronics | 30 | 60.00 |
| Energy_and_Power | 30 | 36.67 |
| Finance | 30 | 63.33 |
| Geography | 30 | 53.33 |
| History | 30 | 60.00 |
| Literature | 30 | 60.00 |
| Manage | 30 | 60.00 |
| Marketing | 30 | 80.00 |
| Materials | 30 | 43.33 |
| Math | 30 | 33.33 |
| Mechanical_Engineering | 30 | 16.67 |
| Music | 30 | 23.33 |
| Pharmacy | 30 | 56.67 |
| Physics | 30 | 43.33 |
| Psychology | 30 | 63.33 |
| Public_Health | 30 | 70.00 |
| Sociology | 30 | 46.67 |
| **Overall (macro)** | **900** | **50.00** |

MMMU fallback 127문항; 두 parser의 선택 불일치 767문항.

MMMU는 추출 실패 시 seeded random fallback을 포함합니다. VLMEvalKit은 규칙만 사용하며 실패는 오답 처리합니다.
이 점수는 GPT judge를 사용했던 기존 62.22%와 채점 조건이 다릅니다.

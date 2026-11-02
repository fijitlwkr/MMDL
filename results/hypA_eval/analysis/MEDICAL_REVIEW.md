# 의료 문항 답변 검토 기록 (E0 정답 → E1 오답)

- 날짜: 2026-11-03
- 대상: MMMU val 의료 5과목(Basic_Medical_Science, Clinical_Medicine, Diagnostics_and_Laboratory_Medicine, Pharmacy, Public_Health) 150문항 중, E0는 맞혔는데 E1(seed 42)은 틀린 21문항
  - E0: 팀 공식 baseline (`results/mmmu_team_baseline`, 66.67%). 이 검토만 이 실행을 기준으로 골랐다(`analysis/REPORT.md` 의 E0 는 시드 3개 평균)
  - E1: `MMDL-team4/hypA-e1-matched-2k`, sampling seed 42 (`results/hypA_eval/e1_seed_42`, 63.00%)
- 확인한 것: E1 답에 보기를 따져보는 풀이 과정이 있는가. 정답 여부가 아니라 풀이의 유무만 본다.
- 방법: 21문항 모두 E1 답 원문 전체와 E0 답 원문을 읽고 판정. 이미지는 보지 않았다(풀이 유무만 판단하므로).

## 요약

| E1 답 형식 | 문항 수 | 풀이 과정 |
|---|---|---|
| 짧은 형식 ("Observation: First, I examine ... / Final Answer: X") | 15 | **15문항 모두 없음** |
| 긴 풀이 | 6 | 6문항 모두 있음 (풀이했지만 틀림. 1문항은 채점 오류) |

- 짧은 형식 15문항은 모두 같은 모양이다. 이미지 묘사 한 단락을 쓰고 바로 답을 고른다. 보기 비교도 없고, 문제 본문의 임상 정보(발열, 혈압 290/160, 이전 임신 경과 등)도 쓰지 않는다.
- 같은 문항에서 E0는 문제 본문의 임상 정보와 의학 지식으로 보기를 하나씩 따져서 맞혔다.
- 짧은 형식 문항 중 다수는 이미지보다 지식이 핵심인 문제였다. 예: 4번(언어 영역 혈관 = 좌측 MCA), 10번(골절 이름 = Colles), 16번(약물 작용 기전). E1은 이런 문제도 이미지 묘사만으로 답했다.
- 긴 풀이 6문항은 대부분 계산 문제(Public_Health 표 해석, 산화수)였고, 풀이 과정에서 표를 잘못 읽거나 계산이 틀렸다.

## 문항별 판정

| # | 문항 | 정답 | E0 | E1 | E1 형식 (토큰) | E1 풀이 | 메모 |
|---|---|---|---|---|---|---|---|
| 1 | Basic_Medical_Science_15 | C | C | B | 짧음 (84) | 없음 | 지식 문제. 이미지 묘사 후 B |
| 2 | Basic_Medical_Science_16 | A | A | B | 긴 풀이 (294) | 있음 | 이미지 세포를 자율신경절로 해석해 false |
| 3 | Basic_Medical_Science_21 | B | B | C | 짧음 (74) | 없음 | |
| 4 | Basic_Medical_Science_30 | B | B | C | 짧음 (85) | 없음 | 좌반구 우세 지식 없이 "양쪽 혈관이 보인다"로 C |
| 5 | Clinical_Medicine_1 | A | A | B | 짧음 (61) | 없음 | 발열·유두부종 정보 미사용 |
| 6 | Clinical_Medicine_5 | A | A | C | 짧음 (73) | 없음 | |
| 7 | Clinical_Medicine_8 | C | C | B | 짧음 (97) | 없음 | 태아수종·황달·이전 임신 정보(Rh) 미사용 |
| 8 | Clinical_Medicine_22 | D | D | B | 짧음 (91) | 없음 | |
| 9 | Clinical_Medicine_25 | B | B | A | 짧음 (98) | 없음 | |
| 10 | Clinical_Medicine_26 | D | D | C | 짧음 (68) | 없음 | 골절 이름(지식) 문제 |
| 11 | Clinical_Medicine_28 | D | D | A | 짧음 (101) | 없음 | 혈압 290/160·크레아티닌 정보 미사용 |
| 12 | Diagnostics_and_Laboratory_Medicine_4 | D | D | B | 짧음 (76) | 없음 | |
| 13 | Diagnostics_and_Laboratory_Medicine_5 | B | B* | D | 짧음 (64) | 없음 | *E0 정답 판정 의심 (아래 참고) |
| 14 | Diagnostics_and_Laboratory_Medicine_15 | C | C | A | 짧음 (82) | 없음 | |
| 15 | Pharmacy_5 | D | D | C | 긴 풀이 (321) | 있음 | 산화수 계산에서 BH4의 H를 +1로 잘못 둠 |
| 16 | Pharmacy_24 | A | A* | D | 짧음 (116) | 없음 | 약물 기전(지식) 문제. *E0도 "A로 가겠다"며 찍음 |
| 17 | Pharmacy_28 | D | D | B | 짧음 (129) | 없음 | |
| 18 | Public_Health_9 | A | A | B | 긴 풀이 (2463) | 있음 | 특이도 계산, 표를 잘못 읽음 |
| 19 | Public_Health_16 | A | A | D | 긴 풀이 (5438) | 있음 | OR 신뢰구간 계산 중 혼란 |
| 20 | Public_Health_17 | D | D | A* | 긴 풀이 (408) | 있음 | *E1은 실제로 D라고 답함. 규칙 파서가 A로 뽑음 (채점 오류) |
| 21 | Public_Health_30 | A | A | B | 긴 풀이 (2780) | 있음 | 병렬검사 LR+ 계산, 정의를 잘못 씀 |

## 주의할 점

- **20번은 E1의 실제 오답이 아니다.** E1 답의 마지막 줄이 "the correct answer is: **D. (48.0-25.4)/48.0**"인데, 규칙 파서는 A를 뽑았다(route=auto, judge 안 거침). 본문에서 "Option A: 48.0 → ..."처럼 보기를 하나씩 설명한 부분을 답으로 잡은 것으로 보인다.
  - 같은 유형을 E0 시드 3개와 E1~E3 9개 실행 전체에서 간이 점검했다(`analysis/REPORT.md` 4절). E0 는 실행당 2~4문항, E1~E3 는 0~4문항으로 비슷해서 E0 와 비교하는 데는 영향이 없다.
- **13번은 E0 정답 판정이 의심스럽다.** E0 답은 8192토큰에서 잘렸고, 끝부분에서 "correct answer is C"를 수십 번 반복한다. 그런데 judge가 B로 판정해 정답 처리됐다.
- **16번은 E0도 확신 없이 찍었다** ("I think I have to go with A").
- 그래서 21문항 중 E1이 실제로 틀린 것으로 보기 확실한 건 18~20문항이다.
- E1의 이미지 묘사가 맞는지는 이미지를 보지 않아 판단하지 않았다.
- seed 42 한 번의 실행만 봤다.

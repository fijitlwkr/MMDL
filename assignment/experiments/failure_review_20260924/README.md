# 모델 실패 60건·게이트 변경 18건 검토 자료

최신 raw의 **검토 자료와 챗 검토 기반 1차 분류**다. v2 채점 점수는 600/900이다.

오답 300건에서 과목별 2건씩 뽑은 [60문항의 실패 유형을 집계](returned_20260924/results/REPORT.md)했다. 가중 추정 비율은 **지식 36.33%·이미지 해석 31.00%·계산 및 추론 14.50%**다. 원인이 불확실한 사례는 5건, 평가기 문제 후보는 1건이며, 입력 라벨과 검토 템플릿을 함께 제공한다.

| 검토 | 선정 | 구성 | 배치 |
|---|---|---|---|
| 모델 실패 유형 | 정책상 오답 300건 중 과목별 2건, 고정 seed 3407 | 60건: 객관식 58·주관식 2, length 20·stop 40 | 10건씩 6개 |
| 게이트 변경 답 판단 | length 게이트 제거로 처리 경로가 바뀐 18건 전부 | 객관식 15·주관식 3, 전부 length | 6건씩 3개 |

두 집합의 중복은 0건, 합계 78문항이다.

## 검토 자료

- [모델 실패 유형 60건](packets/failure60/README.md): 실제 이미지·프롬프트·응답 전문·참조 정답·빈 라벨·분류 기준.
- [게이트 변경 18건](packets/gate18/README.md): 실제 이미지·프롬프트·응답 전문·빈 라벨. 별도 gold·파서/Judge 결과·정오는 제외.

각 안내의 기준에 따라 `batch_*.md`를 읽고 `labels.jsonl`을 검토자별로 복사해 기록한다. 원본 빈 라벨은 보존하고, 서로의 라벨을 보기 전에 각자 판단한다. 배포용 ZIP은 아래 명령으로 생성한다.

취합 담당자만 [게이트 대조표](packets/coordinator/gate18_answer_key.jsonl), [60건 표본·가중치](packets/coordinator/failure60_selection_key.jsonl), [선정 manifest](packets/coordinator/manifest.json)를 확인한다. 블라인드 검토자는 답 판단을 고정하기 전 이 파일들과 기존 raw/채점 결과를 보지 않는다. ZIP에는 coordinator 파일을 포함하지 않았다. 이미 기존 결과를 본 검토자는 `prior_exposure`로 표시한다.

## 기록할 내용

18건의 답 상태는 **명시 답 / 문맥상 확정 가능 / 모호함 / 답 판단 근거 없음**으로 나눈다. Final Answer 표기나 정상 종료 여부 자체를 판정 기준으로 삼지 않는다. 응답에 없는 답을 새로 풀어 보충하지 않으며, 실제 답과 원문 인용을 기록한다. 주관식 3건은 평가용 A/B 대신 답 문자열 그대로 적는다.

60건은 **이미지 해석 / 지식 / 계산·추론 / 반복·미완결 / 평가기 판정 문제 / 불확실** 중 주된 유형을 고르고 근거를 남긴다. 동시에 나타난 현상은 보조 유형에 기록한다. 이미지 오류는 원본 이미지와 모델이 잘못 읽은 내용을 직접 대조해야 한다. 모델이 실제로 정답을 냈는데 평가기가 오답으로 처리한 사례는 모델 실패와 분리한다.

60건의 가중치는 과목별 오답 수/2이며, 전체 오답 300건에 대한 추정 비율과 표본 수·불확실 분류 수를 함께 기록한다. 18건은 경로 변경 사례의 전수 검토다.

## 원본과 이미지

원본 raw SHA-256: `ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313`.

문항별 정오는 [최신 제출 결과](../submission_20260923/results/item_results.jsonl), 18건 선정은 [게이트 변경 결과](../submission_20260923/results/changed_items.jsonl)를 사용한다. 원본 이미지 81개는 `MMMU/MMMU` validation, 고정 revision `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68`에서 받아 **raw.image_indices에 기록된 순서와 슬롯**을 연결했다. 이미지의 출처·파일 해시·크기는 [image_manifest.json](image_manifest.json)에 기록했다.

## 배포용 ZIP 생성·재현

Python 3.10 이상에서 저장소 루트를 기준으로 실행한다. 출력 폴더는 새 폴더를 지정한다.

```bash
python assignment/experiments/failure_review_20260924/prepare.py --self-test
python assignment/experiments/failure_review_20260924/prepare.py --out assignment/experiments/failure_review_20260924/packets_export
```

`packets_export/`에 검토 문서·빈 라벨과 `failure60_review.zip`, `gate18_review.zip`이 생성된다. 각 ZIP에는 해당 문항의 원본 이미지가 포함된다. 검토자는 ZIP을 풀고 첫 `README.md`부터 읽으면 된다.

출력 폴더는 이미지 상대경로를 유지하도록 이 실험 폴더의 바로 아래에 둔다. 이미지·raw·문항별 점수의 해시를 확인한 뒤 동일 자료를 재생성한다. 재현 비교에는 ZIP 내부 파일의 내용을 사용한다.

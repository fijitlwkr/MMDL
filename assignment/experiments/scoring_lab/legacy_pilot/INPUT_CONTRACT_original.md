# 추론팀 → 실험팀 전달 규격 v0.2

최종 확정 전 협의안. 현재 Pod 입력/환경 준비와 2문항 smoke는 완료 기록이 있지만, 최종 HF 900문항 raw는 아직 받지 않았다.

## 파일 묶음

- `predictions.jsonl`: 900개의 전체 응답. 원문 수정/공백 정리/끝부분 자르기 금지.
- `config.json`: 모델/데이터 repo와 revision, dtype, 양쪽 seed, 전체 sampling 값, 출력 cap와 context cap, 이미지 처리/배치/프롬프트 옵션.
- `input_validation.json`, `dataset_manifest.json`: HF 입력 일치 검증, 900 HF ID 목록, 질문·선택지·정답 및 이미지 순서/해시.
- 실제 rendered chat-template 프롬프트 또는 해당 값을 복원 가능한 메시지·template·processor 버전/코드 hash. “질문 문자열만”은 최종 프롬프트가 아니다.
- `environment.json`, `requirements.freeze.txt`, 실행 명령·코드 commit/해시.
- `inference_summary.json`: 총 문항 수, 누락/중복, 종료 사유 분포, 모델 로드/전처리/생성/전체 벽시계 시간, 실제 peak VRAM, GPU 단가와 과금 시간 근거.

## 한 행의 최소 필드

```json
{
  "id": "validation_Accounting_1",
  "question_type": "multiple-choice",
  "question": "실제 HF 질문",
  "options": {"A": "실제 선택지", "B": "실제 선택지"},
  "answer": "A",
  "raw_text": "수정하지 않은 모델 응답 전체",
  "input_tokens": 1000,
  "generated_tokens": 300,
  "finish_reason": "stop"
}
```

위 숫자와 내용은 형식 예시이며 실험 결과가 아니다. 기존 Pod의 `annotation.id/question/question_type/answer/A/B/...` + `result.gen_raw`(없으면 `result.gen`) 구조도 읽는다. `generated_tokens`의 별칭으로 `output_tokens`를 허용한다. `question_id`가 숫자이면 HF ID로 사용하지 않고 `annotation.id`를 쓴다.

- MC `options`는 A/B/... 딕셔너리 또는 리스트. 문자열 `"None"`은 지우지 않는다.
- open은 `question_type="open"`, `options={}`, `answer`에 원본 참조답 텍스트를 보존한다.
- 이미지 파일/순서/실제 이미지 수는 별도 manifest와 연결한다. 텍스트 marker 개수로 이미지 수를 대체하지 않는다.
- `finish_reason`이 없거나 알 수 없는 행은 먼저 추론팀에 확인한다. 출력 길이로 stop/length를 추정하지 않는다.
- cap 비교용 출력은 서로 다른 폴더에 보존하고 입력/환경/seed 차이를 명시한다. 재추론 없이 긴 응답을 자른 것은 독립 cap 실행과 동등하지 않다.

## H4: 생성 예산 비교용 추가 전달 조건

- 서로 다른 출력 cap **최소 2개**, 각각 같은 HF validation **전량 900문항**을 독립 실행한다. 8192는 확정값이 아니며 탐색 범위에서 cap을 사전에 정한다.
- HF ID·질문·선택지·이미지·이미지 순서·프롬프트를 동일하게 유지하고 입력 manifest/hash로 대조한다.
- 모델 revision·processor·이미지 전처리·GPU/드라이버/라이브러리·dtype·sampling·engine/sampling seed 3407·배치/동시성 설정을 고정한다. 가능한 한 같은 Pod에서 비교한다.
- **max_model_len은 고정하고 max_new_tokens만 변경**한다. context는 입력과 최대 출력 cap을 수용하도록 정한다. 다른 조건이 바뀌면 그 차이를 기록하고 cap 단독 효과로 해석하지 않는다.
- cap별 원본 응답·finish_reason·토큰 수·실행 시간·비용 근거를 각 폴더에 보존한다. 일부 문항 속도 시험이나 기존 TSV 결과는 이 비교를 대체하지 않는다.
- 실험팀은 같은 파서·공통 Judge 설정으로 비교한다. raw가 달라지면 Judge 요청도 새로 생성하며, 한 raw의 정책들 사이에서만 해당 Judge 결과를 공유한다.
- 조건을 만족하는 출력이 없으면 H4는 판정 보류다. 한 번씩의 실행만으로 실행 간 변동을 측정했다고 주장하지 않는다.

## config 최소 호환 키

`lab.py prepare --source-kind hf-final`은 다음 키를 검사한다.

```json
{
  "model_revision": "ebb281ec70b05090aa6165b016eac8ec08e71b17",
  "dataset_revision": "98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68",
  "engine_seed": 3407,
  "sampling_seed": 3407,
  "max_model_len": 16384,
  "max_new_tokens": 8192
}
```

**cap 두 값은 명세 예시다. 8192 확정이라는 뜻이 아니다.** 실행한 실제 값을 넘긴다. 다른 팀 코드의 키 이름이 다르면 원본 config를 보존하고 명시적인 adapter를 사용한다. 행에 `config_sha256`이 있으면 제출한 config의 바이트 해시와 같아야 한다.

## 수신 검증의 범위

도구는 HF ID 유일성, 30×30, 필수 필드, 모델/데이터 revision 및 seed 선언, token/context 범위, config hash를 검사한다. **이것만으로 HF 이미지·질문 내용까지 일치했다고 인증하지 않는다.** 입력 전수 검증 보고서와 이미지 manifest는 추론팀 전달 자료로 별도 확인한다.

원본·분석·Judge·라벨 파일에 동일 analysis ID/hash를 남긴다. 입력이나 규칙을 수정하면 새 결과 폴더를 만든다.

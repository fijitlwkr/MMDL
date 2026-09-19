# draft 수신과 현재 실험 도구의 입력

최종 raw 명세는 9/20 팀 합의가 기준입니다. 아래는 소량 샘플을 받을 때 점검할 항목입니다.

## 받을 자료

- 수정하지 않은 raw 900건: HF `id`, `subject`, `question_type`, `gold`, `options`, prompt 전문, `raw_text`, `output_token_ids`, `output_tokens`, `finish_reason`, skip/error.
- 실행 설정: 모델·데이터 revision, seed, sampling, `max_new_tokens`와 `max_model_len`, dtype, 이미지 전처리·배치.
- 입력 manifest: HF ID 목록, 이미지 수·순서·해시, 질문·선택지 검증. 실제 이미지 수와 텍스트 marker 수를 혼동하지 않음.
- 환경 snapshot, 코드 commit, 실행 명령, 입력 토큰 수, 시간·비용 근거.

생성 입력에 gold를 넣지 않습니다. MC Judge 요청에도 gold를 넣지 않습니다. raw의 gold는 평가 단계에서만 사용합니다. token/context 한도는 추론팀이 고정하며 현재 팀 출력 예산은 8192입니다.

## 보존된 lab.py의 호환 범위

현재 도구는 `answer`를 참조답으로 받고 `generated_tokens` 또는 `output_tokens`를 읽습니다. 입력에 별도 `question`이 필요합니다. `gold` 필드와 YAML 공통 설정을 최종 명세 그대로 읽는 어댑터는 아직 구현·확인하지 않았습니다. draft 수신 후 raw를 바꾸지 않고 별도 분석 입력과 원본 해시 연결을 생성해야 합니다.

```json
{
  "id": "validation_Accounting_1",
  "question_type": "multiple-choice",
  "question": "질문 원문",
  "options": {"A": "선택지 A", "B": "선택지 B"},
  "answer": "A",
  "raw_text": "모델 응답 원문",
  "input_tokens": 1000,
  "generated_tokens": 300,
  "finish_reason": "stop"
}
```

위는 형식 예시입니다. 현재 `prepare --source-kind hf-final`의 JSON 설정 검사는 `model_revision`, `dataset_revision`, `engine_seed`, `sampling_seed`, `max_model_len`, `max_new_tokens` 키를 사용합니다. 이 어댑터용 스냅샷은 실행 당시 공통 설정에서 변환하며 별도 튜닝값을 임의 지정하지 않습니다. [당시 도구 명세](legacy_pilot/INPUT_CONTRACT_original.md)를 함께 보존합니다.

## 수신 검증

900개 고유 HF ID·30과목×30문항, skip/error·누락·중복, 유효 선택지/참조답, stop/length, 토큰 수와 cap, 설정/입력 해시를 먼저 확인합니다. 문자열 `"None"`은 실제 선택지일 수 있으므로 결측값으로 지우지 않습니다. 모르는 finish_reason을 토큰 수로 추정하지 않습니다.

H4는 같은 HF 입력·모델·환경·seed·context cap을 유지하고 출력 cap만 다른 전량 결과가 최소 2개 있어야 합니다. 없으면 과목/문항유형/종료사유별 진단까지만 보고하고 cap 개선의 인과 효과는 판정 보류합니다.

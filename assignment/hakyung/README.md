# MMMU / Qwen3-VL-4B-Instruct baseline

고정된 30과목 × 과목당 30문항(총 900문항) validation 평가 파이프라인이다. 기존
`baseline_draft/`는 참고용 초안이며, 실제 재현 실행의 기준은
`experiments/exp0_baseline/config.json`과 루트의 공유 코드 `run_mmmu_eval.py`이다.

## 실행

```bash
python3 -m pip install -r requirements.txt
./experiments/exp0_baseline/run.sh
```

또는 동일하게 다음 한 줄로 실행할 수 있다.

```bash
python3 run_mmmu_eval.py --config experiments/exp0_baseline/config.json
```

스크립트는 `vLLM==0.11.0`, GPU/driver 존재, 고정 설정값, subject별 정확히 30문항을
검증한다. 하나라도 다르면 부분 결과를 최종 결과처럼 저장하지 않고 중단한다. Hugging Face
캐시 위치나 인증 토큰처럼 실험값이 아닌 운영 환경은 일반 환경 변수로 지정할 수 있다.

## 산출물

실험 0 출력 디렉터리는 `experiments/exp0_baseline/outputs/`이다. `output_dir` 같은 상대경로는
현재 CWD가 아니라 해당 `config.json`이 있는 디렉터리를 기준으로 해석된다.

- `predictions.jsonl`: `question_id`, `subject`, 원문 그대로의 `raw_text`,
  `finish_reason`, `input_tokens`, `output_tokens`, `parse_failure`와 재채점에 필요한 annotation
- `env.json`: CUDA, NVIDIA driver/GPU, torch, vLLM, Python, 실행 config hash
- `results.md`: 과목별 accuracy와 parse failure rate 및 overall macro average 표
- `results.json`: 문항별 파싱 결과와 정확한 집계값
- `dataset.jsonl`, `images/`: revision이 고정된 실행 입력과 참조 이미지

파싱 시에만 `</think>` 뒤쪽을 사용하며 `raw_text`는 절대 변경하지 않는다. 객관식 답을
추출하지 못하면 `parse_failure=true`와 오답으로 기록하고 random fallback은 사용하지 않는다.
open-ended 응답은 MMMU 공식 문자열/숫자 정규화 방식으로 채점하며, 빈 생성만 구조적인 파싱
실패로 센다.

저장된 raw 응답만 다시 파싱할 때는 모델이나 GPU를 로드하지 않는다.

```bash
python3 run_mmmu_eval.py --config experiments/exp0_baseline/config.json \
  --score-only experiments/exp0_baseline/outputs/predictions.jsonl
```

## 설정 재사용

후속 실험은 baseline JSON을 복사하고 `enforce_fixed_baseline`을 `false`로 바꾼 뒤 필요한 값과
`output_dir`만 변경한다. baseline config는 이 플래그가 `true`라 고정값 위반을 거부하므로,
baseline 결과가 다른 설정으로 실수로 덮이는 것을 막으면서 같은 코드를 A~F에도 재사용할 수 있다.
구체적인 생성 절차는 `experiments/README.md`를 따른다.

`results.md`는 제출 템플릿의 `No. / Subject / Data Num / Acc` 구조를 유지하면서 요구된
`Parse Failure Rate` 열을 별도로 추가한다.

## 기존 초안

`baseline_draft/`에는 이전 실험 코드와 결과가 남아 있다. 그 안의 `max_new_tokens=3200`,
범위 지정 vLLM 의존성, 이미지 마커 제거 등의 값은 이 baseline 실행에 사용되지 않는다.

# raw.jsonl 평가 및 8192·2048 비교

저장된 추론 결과를 동일한 규칙과 Judge 설정으로 평가한다. 모델 재추론은 하지 않는다. `prepare`, `summarize`, `compare`는 오프라인이며, `run`만 OpenAI API를 호출한다. 실행자는 본인 API 키를 사용한다.

저장소 루트에서 Python 3.10 이상으로 실행한다.

```bash
python -m pip install -r assignment/experiments/raw_evaluation/requirements.txt
```

## 1. 입력 검증 및 요청 준비 — API 호출 없음

```bash
python assignment/experiments/raw_evaluation/evaluate.py prepare --config assignment/src/config.yaml --raw assignment/runs/draft/raw.jsonl --out assignment/experiments/raw_evaluation/outputs/8192
python assignment/experiments/raw_evaluation/evaluate.py prepare --config assignment/src/config.yaml --raw assignment/runs/run_max_new_tokens2048/raw.jsonl --out assignment/experiments/raw_evaluation/outputs/2048
```

900개 고유 ID, 30과목 × 30문항, 객관식 847개·주관식 53개, 생성 상태와 토큰 개수를 검증한다. 누락·오류 입력은 유효 문항만 골라 점수를 내지 않고 중단한다. 입력은 결과 폴더의 `input/raw.jsonl`에 그대로 복사하고 해시를 기록한다. 원본 `runs/*/raw.jsonl`은 수정하지 않는다.

Judge 대상 수는 각 입력에서 다시 계산한다. 8192 실행의 대상 수를 2048 실행에 고정하지 않는다. `assignment/src/config.yaml`의 `scoring` 설정을 사용하며, 기존 `budget.max_new_tokens`를 현재 raw의 생성 한도로 덮어씌우지 않는다. 입력 검증은 이 과제의 고정 MMMU validation 900문항과 현재 24필드 raw 형식을 대상으로 한다.

## 2. 본인 키로 Judge 실행

```bash
python assignment/experiments/raw_evaluation/evaluate.py run --out assignment/experiments/raw_evaluation/outputs/8192 --ask-key
python assignment/experiments/raw_evaluation/evaluate.py run --out assignment/experiments/raw_evaluation/outputs/2048 --ask-key
```

터미널의 숨김 입력에 API 키를 붙여 넣는다. 숨김 입력을 지원하지 않는 환경에서는 입력을 받지 않고 중단하므로 대화형 터미널을 사용한다. 키는 프로세스 메모리에서만 사용하며 파일에 저장하지 않는다. 이미 `OPENAI_API_KEY` 환경 변수가 있으면 `--ask-key`를 생략할 수 있다. 키를 코드·JSON·채팅·Git에 넣지 않는다.

처음 소량만 확인하려면 `run`에 `--limit 3`을 추가한다. 이후 같은 명령에서 `--limit`을 빼면 저장된 응답을 재사용하고 남은 문항을 진행한다. 완료된 `Z`도 재호출하지 않는다. 네트워크 오류나 호출 도중 중단으로 처리 여부가 불명확한 요청은 자동 재시도하지 않고 중단한다. 이러한 실행의 잠금·호출 기록을 지워 강제로 재개하지 말고 먼저 기록을 확인한다.

## 3. 오프라인 재집계 및 비교

```bash
python assignment/experiments/raw_evaluation/evaluate.py summarize --out assignment/experiments/raw_evaluation/outputs/8192
python assignment/experiments/raw_evaluation/evaluate.py summarize --out assignment/experiments/raw_evaluation/outputs/2048
python assignment/experiments/raw_evaluation/evaluate.py compare --left assignment/experiments/raw_evaluation/outputs/8192 --right assignment/experiments/raw_evaluation/outputs/2048 --out assignment/experiments/raw_evaluation/outputs/comparison
```

전체·문항 유형·종료 사유·과목별 점수, 추출 실패, Judge 사용 토큰과 추정 비용을 집계한다. API 미완료 문항이 있으면 최종 정확도는 `null`이며 오답으로 합치지 않는다. MMMU 규칙 점수는 API와 독립적으로 확인할 수 있다.

비교 전 ID별 질문·정답·선택지·이미지 인덱스와 채점 설정이 같은지 확인한다. raw에는 모델 revision과 생성 설정 전체가 없으므로, 이 비교만으로 점수 차이의 원인이 오직 토큰 한도라고 확정할 수는 없다. 원인 분석에는 추론팀의 실제 실행 메타데이터를 함께 확인한다.

## 적용 정책

- 객관식: 고정 Qwen 규칙 + 사용자 정의 `Final Answer` 보완. 마지막 답 표기 뒤의 텍스트가 100자 이내이고 유효 표기들이 일치할 때만 보완한다. 생성 길이를 100자로 제한하는 규칙이 아니다.
- 모든 `finish_reason=length`, 답 미추출, Qwen과 보완 규칙의 충돌은 Judge로 보낸다. `length`를 토큰 수로 추정하지 않는다.
- 객관식 Judge 요청에는 gold를 별도 필드로 전달하지 않는다. 고정 질문 문맥과 선택지, 생성 응답 전체를 전달한다.
- 주관식: `A=참조답 원문`, `B=Other Answers`로 변환한 Qwen 방식이다. 참조답을 보는 동치 판정이며 `Final Answer` 문자 보완은 적용하지 않는다.
- Judge가 정상 종료(`stop`)했을 때만 응답에서 선택지를 추출한다. 완료된 `Z`, 유효 답 없음, 비정상 종료는 추출 실패·오답이다. API 오류/미응답은 미완료다.
- 별도 진단값은 **MMMU 규칙 + 랜덤 폴백 제거** 점수다. 여기에는 Judge와 length gate를 적용하지 않는다. 리스트 형태로 직렬화된 주관식 정답은 안전한 literal 변환으로 MMMU의 대체 정답 목록에 전달한다.

기존 실험과 비교하기 위해 Qwen 프롬프트를 보존했다. 그 프롬프트는 출력 설명에 A–D/Z를 열거하지만 실제 문항 선택지가 더 많으면 그 선택지들도 전달·허용한다. 이 도구를 Qwen/MMMU 공식 evaluator 전체의 완전 재현이라고 부르지 않는다. 높은 채점 점수만으로 Judge의 추출 정확도가 검증되는 것도 아니다. 고정 소스와 라이선스는 [frozen/THIRD_PARTY.md](frozen/THIRD_PARTY.md)에 있다.

설정이나 코드를 바꾸면 새 결과 폴더로 준비한다. 실행 결과는 `outputs/` 아래에 두면 Git에서 제외된다. 다른 실행자의 결과를 섞거나 기존 요청/응답을 수동 수정하지 않는다.

## 오프라인 검증

```bash
python -m unittest discover -s assignment/experiments/raw_evaluation/tests -v
```

테스트는 실제 API를 호출하지 않는다.

실제 두 raw의 준비 결과와 기존 세 Judge 응답의 재집계 확인은 [VALIDATION.md](VALIDATION.md)에 기록했다.

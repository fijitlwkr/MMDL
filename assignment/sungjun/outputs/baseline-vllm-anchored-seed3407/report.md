# MMMU validation 베이스라인 평가 결과 (Qwen3-VL-4B-Instruct)

본 문서는 `src/report.py` 가 실행 디렉터리의 `metrics.json` / `timing.json` / `env.json` / `predictions.jsonl` 을 읽어 자동 생성한 것입니다. 손으로 수정하지 마시고, 수치를 고칠 일이 생기면 평가를 다시 실행한 뒤 이 스크립트를 다시 돌리십시오.

## 1. 실행 개요

| 항목 | 값 |
| :--- | :--- |
| 실행 디렉터리 | /workspace/MMDL/outputs/baseline-vllm-anchored-seed3407 |
| 담당 팀원 | baseline-vllm-anchored-seed3407 |
| 모델 | Qwen/Qwen3-VL-4B-Instruct |
| 모델 리비전 | ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| 데이터셋 | MMMU/MMMU |
| 데이터셋 리비전 | 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 |
| 분할(split) | validation |
| 표본 수 | 900 |
| 추론 백엔드 | vllm |
| 프롬프트 템플릿 | anchored |
| 시드(seed) | N/A |
| 보고서 생성 시각 | 2026-09-14 17:06:08 UTC / 2026-09-15 02:06:08 KST |

## 2. 무결성 점검

> **점검 결과: 확인이 필요한 항목 2건.** 아래 표에서 '확인 필요' 행을 먼저 해결한 뒤 이 수치를 제출하십시오.

| 점검 항목 | 기대 | 관측 | 판정 | 근거/비고 |
| :--- | :--- | :--- | :--- | :--- |
| 전체 표본 수 | 900 | 900 | 정상 | FACTS 4: validation = 30문항 x 30과목 = 900 |
| 저장된 accuracy = correct / n | 일치 | 일치 | 정상 | overall / multiple_choice / open_ended 블록을 각각 재계산해 대조합니다. |
| 과목 수 | 30 | 30 | 정상 | FACTS 4: HF config 가 과목별로 1개씩 30개 |
| 과목별 n 합계 = 전체 n | 900 | 900 | 정상 | 어긋나면 집계 단계에서 문항이 누락되었습니다. |
| 카테고리별 n 합계 = 전체 n | 900 | 900 | 정상 | 어긋나면 과목→카테고리 매핑에 빠진 과목이 있습니다. |
| 객관식 + 단답형 = 전체 n | 900 | 900 | 정상 | question_type 분류 누락 점검 |
| 객관식 / 단답형 문항 수 | 847 / 53 | 847 / 53 | 정상 | FACTS 4: 847 multiple-choice + 53 open |
| 카테고리별 표본 수 | 120/150/150/150/120/210 | 일치 | 정상 | FACTS 4b |
| predictions.jsonl 줄 수 = 전체 n | 900 | 900 | 정상 | 응답 덤프 누락 점검 |
| 중복 id | 0 | 0 | 정상 | 같은 문항이 두 번 채점되면 정확도가 왜곡됩니다. |
| 이미지 2장 이상 문항 수 | 43 | 39 | 확인 필요 | FACTS 4: 2장 24 + 3장 5 + 4장 8 + 5장 6 = 43. 여기서 어긋나면 멀티 이미지 문항이 통째로 빠졌습니다. |
| 최대 이미지 장수 | 5 | 5 | 정상 | FACTS 4: validation 최대 5장(image_6/7 은 항상 null) |
| image_indices 길이 = n_images | 0 | 0 | 정상 | 어긋나면 `<image N>` 마커 매핑(FACTS 4a)이 깨졌습니다. |
| git 작업 트리 청결(dirty=false) | false | N/A | 해당 없음 | FACTS 12: dirty=true 인 실행은 커밋과 결과가 대응되지 않아 보고용으로 쓸 수 없습니다. |
| 미파싱(무작위 추측) 비율 | 객관식의 5 % 이하 | 48 / 847 = 5.67 % | 확인 필요 | FACTS 4c: 공식 파서는 실패 시 random.choice 로 추측하므로 비율이 높으면 점수 신뢰도가 떨어집니다. |

## 3. 전체 성능

| 항목 | 값 |
| :--- | :--- |
| 표본 수 (n) | 900 |
| 정답 수 (correct) | 534 |
| 정확도 (accuracy) | 59.33 % |
| 집계 방식 | micro / sample-weighted |
| 공개 보고 점수 (MMMU val) | 67.40 % |
| 차이 (본 실행 − 공개) | -8.07 pp |
| 관측값 기준 표준오차 sqrt(p(1−p)/n) | 1.64 pp |

집계는 **micro(표본 가중) 평균**입니다. 공식 MMMU 하네스도 표본 가중 방식을 쓰므로 카테고리 6개 정확도의 단순 평균(macro)과는 값이 다릅니다(FACTS 4b). 두 값은 다음 절에 나란히 제시합니다.

## 4. 카테고리별 성능

| 카테고리 | 과목 수 | n | 기대 n | 정답 | 정확도 | 비고 |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| Art and Design (예술·디자인) | 4 | 120 | 120 | 77 | 64.17 % | - |
| Business (경영·경제) | 5 | 150 | 150 | 104 | 69.33 % | - |
| Science (과학) | 5 | 150 | 150 | 74 | 49.33 % | - |
| Health and Medicine (보건·의학) | 5 | 150 | 150 | 101 | 67.33 % | - |
| Humanities and Social Science (인문·사회과학) | 4 | 120 | 120 | 88 | 73.33 % | - |
| Tech and Engineering (기술·공학) | 7 | 210 | 210 | 90 | 42.86 % | - |

### 4.1 micro vs macro

| 집계 방식 | 정의 | 값 |
| :--- | :--- | ---: |
| micro (표본 가중) — **공식 기준** | 전체 정답 수 / 전체 문항 수 | 59.33 % |
| macro (비가중) | 6개 카테고리 정확도의 단순 평균 | 61.06 % |
| 두 값의 차이 | macro − micro | +1.73 pp |

카테고리별 표본 수가 120/150/150/150/120/210 으로 고르지 않기 때문에 두 값은 원리적으로 일치하지 않습니다(FACTS 4b). 공식 MMMU 하네스와 공개 점수 67.4 는 **micro** 기준이므로, 보고·비교에는 반드시 micro 값을 쓰고 macro 는 카테고리 간 편차를 보는 보조 지표로만 쓰십시오.

## 5. 과목별 성능 (정확도 오름차순)

| 순위 | 과목 (HF config) | 과목(한글) | 카테고리 | n | 정답 | 정확도 |
| ---: | :--- | :--- | :--- | ---: | ---: | ---: |
| 1 | Chemistry | 화학 | Science (과학) | 30 | 7 | 23.33 % |
| 2 | Electronics | 전자공학 | Tech and Engineering (기술·공학) | 30 | 8 | 26.67 % |
| 3 | Architecture_and_Engineering | 건축·공학 | Tech and Engineering (기술·공학) | 30 | 11 | 36.67 % |
| 4 | Diagnostics_and_Laboratory_Medicine | 진단검사의학 | Health and Medicine (보건·의학) | 30 | 12 | 40.00 % |
| 5 | Mechanical_Engineering | 기계공학 | Tech and Engineering (기술·공학) | 30 | 12 | 40.00 % |
| 6 | Music | 음악 | Art and Design (예술·디자인) | 30 | 13 | 43.33 % |
| 7 | Agriculture | 농학 | Tech and Engineering (기술·공학) | 30 | 14 | 46.67 % |
| 8 | Computer_Science | 컴퓨터과학 | Tech and Engineering (기술·공학) | 30 | 14 | 46.67 % |
| 9 | Energy_and_Power | 에너지·동력 | Tech and Engineering (기술·공학) | 30 | 15 | 50.00 % |
| 10 | Geography | 지리학 | Science (과학) | 30 | 15 | 50.00 % |
| 11 | Manage | 경영관리 | Business (경영·경제) | 30 | 15 | 50.00 % |
| 12 | Math | 수학 | Science (과학) | 30 | 15 | 50.00 % |
| 13 | Biology | 생물학 | Science (과학) | 30 | 16 | 53.33 % |
| 14 | Materials | 재료공학 | Tech and Engineering (기술·공학) | 30 | 16 | 53.33 % |
| 15 | Art | 미술 | Art and Design (예술·디자인) | 30 | 17 | 56.67 % |
| 16 | Finance | 재무 | Business (경영·경제) | 30 | 18 | 60.00 % |
| 17 | Accounting | 회계 | Business (경영·경제) | 30 | 19 | 63.33 % |
| 18 | Sociology | 사회학 | Humanities and Social Science (인문·사회과학) | 30 | 20 | 66.67 % |
| 19 | Clinical_Medicine | 임상의학 | Health and Medicine (보건·의학) | 30 | 21 | 70.00 % |
| 20 | History | 역사학 | Humanities and Social Science (인문·사회과학) | 30 | 21 | 70.00 % |
| 21 | Pharmacy | 약학 | Health and Medicine (보건·의학) | 30 | 21 | 70.00 % |
| 22 | Physics | 물리학 | Science (과학) | 30 | 21 | 70.00 % |
| 23 | Art_Theory | 미술이론 | Art and Design (예술·디자인) | 30 | 22 | 73.33 % |
| 24 | Basic_Medical_Science | 기초의학 | Health and Medicine (보건·의학) | 30 | 23 | 76.67 % |
| 25 | Psychology | 심리학 | Humanities and Social Science (인문·사회과학) | 30 | 23 | 76.67 % |
| 26 | Literature | 문학 | Humanities and Social Science (인문·사회과학) | 30 | 24 | 80.00 % |
| 27 | Public_Health | 보건학 | Health and Medicine (보건·의학) | 30 | 24 | 80.00 % |
| 28 | Design | 디자인 | Art and Design (예술·디자인) | 30 | 25 | 83.33 % |
| 29 | Economics | 경제학 | Business (경영·경제) | 30 | 26 | 86.67 % |
| 30 | Marketing | 마케팅 | Business (경영·경제) | 30 | 26 | 86.67 % |

### 5.1 성능 분석용 요약

- **가장 취약한 과목 5개**: Chemistry (화학) 23.33 %, Electronics (전자공학) 26.67 %, Architecture_and_Engineering (건축·공학) 36.67 %, Diagnostics_and_Laboratory_Medicine (진단검사의학) 40.00 %, Mechanical_Engineering (기계공학) 40.00 %
- **가장 우수한 과목 5개**: Marketing (마케팅) 86.67 %, Economics (경제학) 86.67 %, Design (디자인) 83.33 %, Public_Health (보건학) 80.00 %, Literature (문학) 80.00 %
- 과목 간 정확도 폭(최고 − 최저): 63.33 pp

과목당 표본은 30문항뿐이므로 한 문항이 3.33 pp 를 움직입니다. 즉 과목 단위 수치는 편차가 크며, 전체 n=900 기준 1문항이 0.111 pp 인 것과 비교해 약 30배 민감합니다(FACTS 7). 과목 순위는 경향을 보는 데까지만 쓰고, 단정적인 결론은 카테고리 단위(n=120~210)에서 내리십시오.

## 6. 문제 유형별 성능

| 유형 | n | 기대 n | 정답 | 정확도 | 채점 방식 |
| :--- | ---: | ---: | ---: | ---: | :--- |
| multiple-choice (객관식) | 847 | 847 | 519 | 61.28 % | 공식 `parse_multi_choice_response` 로 채점 |
| open (단답형) | 53 | 53 | 15 | 28.30 % | 공식 `parse_open_response` 로 채점 |

| 미파싱 진단 항목 | 값 |
| :--- | :--- |
| 미파싱(파서 fallback) 응답 수 | 48 |
| 객관식 대비 비율 | 5.67 % |
| 우연히 맞은 것으로 추정되는 문항 수 (선택지 4개 가정) | 약 12.0 문항 ≈ 전체 정확도 1.33 pp |
| 추정 범위 (선택지 9개 → 2개) | 5.3 ~ 24.0 문항 |

### 6.1 미파싱(unparseable)이 무엇을 뜻하는가

공식 MMMU 파서(`mmmu/utils/eval_utils.py`)는 응답에서 선택지 문자를 찾지 못하면 `random.choice(all_choices)` 로 **무작위 추측**을 반환합니다. 즉 미파싱 문항은 오답으로 처리되는 것이 아니라, 선택지 수의 역수만큼 확률로 정답 처리됩니다. 본 구현은 이 동작을 그대로 재현하되 몇 건이 fallback 에 걸렸는지 세어 `n_unparseable` 로 남깁니다(FACTS 4c).

실제로 fallback 에 걸리는 것이 확인된 응답 형태는 다음과 같습니다(FACTS 4c).

- `**C**` — Markdown 굵게 표시. 괄호 패스에 걸리지 않고, ` C ` 패스는 양쪽 공백을 요구합니다.
- `C) $8` — 닫는 괄호만 있는 형태.
- `c` — 소문자 단독.
- 빈 문자열(`""`) — 생성이 즉시 종료된 경우.
- `The correct option is $8` — 선택지 본문 매칭 패스는 응답 토큰이 5개를 **넘을 때만** 실행되므로 정확히 5토큰인 이 응답은 본문 매칭 없이 추측으로 넘어갑니다.

따라서 `n_unparseable` 은 그 자체로 프롬프트 품질 지표입니다. 값이 크면 정확도 수치에 무작위 성분이 섞였다는 뜻이므로, 파서를 고치는 대신(공식 호환성을 잃습니다) `--template anchored` 처럼 `Answer: <letter>` 앵커를 강제하는 프롬프트로 다시 측정하는 것이 올바른 대응입니다(FACTS 11).

또한 무작위 추측은 전역 `random` 스트림을 소비하므로 **문항 순회 순서가 바뀌면 점수도 바뀝니다**. 본 구현은 순서를 고정하고 채점 루프 직전에 `random.seed(42)` 를 호출합니다(FACTS 4c).

## 7. 소요 시간

| 구간 | 시간 | 총시간 대비 |
| :--- | ---: | ---: |
| 총 소요 시간 (total_wall_s) | 988.4 초 (16분 28초) | 100.0 % |
| 모델 로딩 (model_load_s) | 32.4 초 | 3.3 % |
| 추론 (inference_s) | 901.4 초 (15분 1초) | 91.2 % |
| 채점 (scoring_s) | 0.1 초 | 0.0 % |
| 그 외(데이터 로딩·집계 등) | 54.6 초 | 5.5 % |
| 문항당 평균 추론 시간 | 1.00 초/문항 | - |

모델 로딩 시간을 따로 계측하는 이유는, 엔진 기동(가중치 로딩, vLLM 의 torch.compile / CUDA 그래프 캡처) 비용이 알파벳 순으로 첫 번째 과목(`Accounting`)에 전가되어 과목별 시간 표를 왜곡하기 때문입니다(FACTS 7). 또한 첫 실행은 HF 다운로드가 포함된 cold-cache 실행이므로, 캐시를 채운 뒤의 실행만 보고용 수치로 사용하십시오.

### 7.1 카테고리별 소요 시간

| 카테고리 | n | 소요 시간 | 문항당 |
| :--- | ---: | ---: | ---: |
| Art and Design (예술·디자인) | 120 | 66.4 초 (1분 6초) | 0.55 초/문항 |
| Business (경영·경제) | 150 | 181.9 초 (3분 2초) | 1.21 초/문항 |
| Science (과학) | 150 | 184.8 초 (3분 5초) | 1.23 초/문항 |
| Health and Medicine (보건·의학) | 150 | 90.0 초 (1분 30초) | 0.60 초/문항 |
| Humanities and Social Science (인문·사회과학) | 120 | 52.5 초 | 0.44 초/문항 |
| Tech and Engineering (기술·공학) | 210 | 325.7 초 (5분 26초) | 1.55 초/문항 |

### 7.2 과목별 소요 시간 (문항당 시간 내림차순)

| 과목 | 과목(한글) | n | 소요 시간 | 문항당 |
| :--- | :--- | ---: | ---: | ---: |
| Materials | 재료공학 | 30 | 62.1 초 (1분 2초) | 2.07 초/문항 |
| Architecture_and_Engineering | 건축·공학 | 30 | 60.6 초 (1분 1초) | 2.02 초/문항 |
| Energy_and_Power | 에너지·동력 | 30 | 55.7 초 | 1.86 초/문항 |
| Mechanical_Engineering | 기계공학 | 30 | 50.4 초 | 1.68 초/문항 |
| Music | 음악 | 30 | 46.2 초 | 1.54 초/문항 |
| Accounting | 회계 | 30 | 44.5 초 | 1.48 초/문항 |
| Math | 수학 | 30 | 44.0 초 | 1.47 초/문항 |
| Electronics | 전자공학 | 30 | 41.6 초 | 1.39 초/문항 |
| Computer_Science | 컴퓨터과학 | 30 | 40.1 초 | 1.34 초/문항 |
| Finance | 재무 | 30 | 38.1 초 | 1.27 초/문항 |
| Chemistry | 화학 | 30 | 37.8 초 | 1.26 초/문항 |
| Public_Health | 보건학 | 30 | 36.0 초 | 1.20 초/문항 |
| Physics | 물리학 | 30 | 35.3 초 | 1.18 초/문항 |
| Biology | 생물학 | 30 | 34.8 초 | 1.16 초/문항 |
| Marketing | 마케팅 | 30 | 34.0 초 | 1.13 초/문항 |
| Economics | 경제학 | 30 | 32.9 초 | 1.10 초/문항 |
| Geography | 지리학 | 30 | 32.9 초 | 1.10 초/문항 |
| Manage | 경영관리 | 30 | 32.3 초 | 1.08 초/문항 |
| Pharmacy | 약학 | 30 | 32.4 초 | 1.08 초/문항 |
| Sociology | 사회학 | 30 | 28.0 초 | 0.93 초/문항 |
| Agriculture | 농학 | 30 | 15.1 초 | 0.50 초/문항 |
| Psychology | 심리학 | 30 | 10.5 초 | 0.35 초/문항 |
| Diagnostics_and_Laboratory_Medicine | 진단검사의학 | 30 | 9.4 초 | 0.31 초/문항 |
| Art_Theory | 미술이론 | 30 | 8.9 초 | 0.30 초/문항 |
| History | 역사학 | 30 | 7.8 초 | 0.26 초/문항 |
| Basic_Medical_Science | 기초의학 | 30 | 6.5 초 | 0.22 초/문항 |
| Art | 미술 | 30 | 6.2 초 | 0.21 초/문항 |
| Literature | 문학 | 30 | 6.1 초 | 0.20 초/문항 |
| Clinical_Medicine | 임상의학 | 30 | 5.7 초 | 0.19 초/문항 |
| Design | 디자인 | 30 | 5.2 초 | 0.17 초/문항 |

### 7.3 문항 단위 지연 시간 분포

| 통계량 | 값(초) |
| :--- | ---: |
| 문항 수 | 900 |
| 최소 | 0.17 |
| 중위수(p50) | 1.10 |
| 평균 | 1.00 |
| p95 | 2.02 |
| 최대 | 2.07 |
| 합계 | 901.4 |

vLLM 은 여러 요청을 연속 배치로 처리하므로 문항별 `latency_s` 의 합계는 `inference_s` 보다 크게 나올 수 있습니다(요청 구간이 서로 겹칩니다). 처리량 기준 수치는 위 7절의 `inference_s` 를 쓰십시오.

## 8. 실험 환경

- env.json schema_version: `1.0.0`
- 수집 시각(UTC): `2026-09-14T16:50:19Z`

### 8.1 하드웨어

| 항목 | 값 |
| :--- | :--- |
| GPU | NVIDIA GeForce RTX 4090 |
| GPU 개수 | 1 |
| GPU 메모리 | 24564 MiB (24.0 GiB) |
| CPU | AMD EPYC 7542 32-Core Processor |
| CPU 코어 수 | 64 |
| 시스템 메모리 | 503.55 GiB |

### 8.2 드라이버와 CUDA 버전

| 항목 | 값 | 의미 |
| :--- | :--- | :--- |
| nvidia-smi 헤더 CUDA | 13.0 | 드라이버가 지원하는 **최대** 런타임 버전입니다. 실제 사용 버전이 아닙니다. |
| torch.version.cuda | 12.8 | 휠이 빌드된 CUDA — **실제로 중요한 값**입니다. |
| nvcc --version | 12.8.93 | 로컬 툴킷. 보통 설치되어 있지 않고, 미리 빌드된 휠과는 무관합니다. |
| NVIDIA 드라이버 버전 | 580.159.04 | CUDA 12.x 는 525 이상, 13.x 는 580 이상이 필요합니다. |

세 CUDA 버전은 서로 다른 것을 가리킵니다(FACTS 9). 예를 들어 `nvidia-smi` 가 13.0 인데 `torch.version.cuda` 가 12.9 인 상태는 **정상**이며 조치할 필요가 없습니다. 또한 RunPod 머신마다 드라이버가 다르므로, 팀원 4명은 Pod 생성 시 CUDA 버전 필터를 써서 같은 드라이버를 받아야 합니다. 드라이버가 다르면 커널 경로가 달라져 설명할 수 없는 정확도 차이가 생깁니다(FACTS 8).

### 8.3 운영체제와 Python

| 항목 | 값 |
| :--- | :--- |
| os.system | Linux |
| os.kernel_release | 6.8.0-134-generic |
| os.kernel_version | #134~22.04.1-Ubuntu SMP PREEMPT_DYNAMIC Tue Jun 30 14:05:04 UTC  |
| os.machine | x86_64 |
| os.platform | Linux-6.8.0-134-generic-x86_64-with-glibc2.39 |
| os.hostname | a2347273df5e |
| os.libc | glibc 2.39 |
| os.os_release.id | ubuntu |
| os.os_release.name | Ubuntu |
| os.os_release.pretty_name | Ubuntu 24.04.3 LTS |
| os.os_release.version_id | 24.04 |
| os.os_release.version_codename | noble |
| os.container.in_container | True |
| os.container.hints | /.dockerenv 파일이 존재합니다 (Docker), PID 1 cgroup 에 docker 문자열이 있습니다, RUNPOD_POD_ID 환경 변수가 설정되어 있습니다 (RunPod 파드) |
| os.container.image_tag | N/A |
| os.container.image_digest | N/A |
| os.runpod.pod_id | p0vdltcdw4o654 |
| os.runpod.pod_hostname | p0vdltcdw4o654-6441156a |
| os.runpod.gpu_count | 1 |
| os.runpod.cpu_count | 12 |
| os.runpod.mem_gb | 100 |
| os.runpod.datacenter_id | EUR-IS-2 |
| os.runpod.volume_id | N/A |
| os.runpod.volume_path | N/A |
| os.runpod.endpoint_id | N/A |
| os.relevant_env.HF_HOME | /workspace/.cache/huggingface/ |
| os.relevant_env.HF_HUB_CACHE | /workspace/.cache/huggingface//hub |
| os.relevant_env.HF_DATASETS_CACHE | /workspace/.cache/huggingface//datasets |
| os.relevant_env.HF_XET_HIGH_PERFORMANCE | 1 |
| os.relevant_env.CUDA_VERSION | 12.8.1 |
| os.relevant_env.NVIDIA_VISIBLE_DEVICES | void |
| os.relevant_env.NVIDIA_DRIVER_CAPABILITIES | compute,utility |
| os.relevant_env.LD_LIBRARY_PATH | /usr/local/cuda/lib64 |
| os.relevant_env.TOKENIZERS_PARALLELISM | <비밀값이므로 기록하지 않음> |
| os.relevant_env.VLLM_ENABLE_V1_MULTIPROCESSING | 0 |
| os.relevant_env.TZ | Etc/UTC |
| python.version | 3.12.3 |
| python.version_full | 3.12.3 (main, Aug 14 2025, 17:47:21) [GCC 13.3.0] |
| python.implementation | CPython |
| python.compiler | GCC 13.3.0 |
| python.executable | /workspace/venv/bin/python |
| python.prefix | /workspace/venv |
| python.base_prefix | /usr |
| python.in_virtualenv | True |

### 8.4 도구 패키지 버전

| 패키지 | 버전 |
| :--- | :--- |
| torch | 2.8.0+cu128 |
| torchvision | 0.23.0+cu128 |
| transformers | 4.57.1 |
| tokenizers | 0.22.2 |
| huggingface-hub | 0.35.3 |
| accelerate | 1.11.0 |
| safetensors | 0.6.2 |
| vllm | 0.11.0 |
| datasets | 4.0.0 |
| pillow | 11.3.0 |
| numpy | 2.2.6 |
| qwen-vl-utils | 미설치 |
| flash-attn | 미설치 |

`flash-attn` 이 `미설치` 인 것은 의도된 상태입니다. PyPI 에 소스 배포본만 있어 설치에 30~60분의 컴파일이 필요하고, Qwen3-VL 은 `_supports_sdpa = True` 이므로 `attn_implementation="sdpa"` 로 충분합니다(FACTS 5).

<details>
<summary>pip freeze 전체 목록 (156개 패키지) — 클릭하여 펼치기</summary>

```text
accelerate==1.11.0
agent-detector==2.0.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.3
aiosignal==1.4.0
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
astor==0.8.1
attrs==26.1.0
blake3==1.0.9
cachetools==7.1.8
cbor2==6.1.4
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
click==8.5.0
cloudpickle==3.1.2
compressed-tensors==0.11.0
cuda-pathfinder==1.8.1
cupy-cuda12x==14.2.0
datasets==4.0.0
depyf==0.19.0
detect-installer==0.2.1
dill==0.3.8
diskcache==5.6.3
dnspython==2.8.0
einops==0.8.2
email-validator==2.3.0
fastapi==0.141.1
fastapi-cli==0.0.32
fastapi-cloud-cli==0.26.0
fastar==0.12.0
filelock==3.32.3
frozendict==2.4.7
frozenlist==1.8.0
fsspec==2025.3.0
gguf==0.19.0
h11==0.16.0
hf-xet==1.6.0
httpcore==1.0.9
httpcore2==2.13.0
httptools==0.8.0
httpx==0.28.1
httpx2==2.13.0
huggingface-hub==0.35.3
idna==3.19
interegular==0.3.3
Jinja2==3.1.6
jiter==0.17.0
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
lark==1.2.2
llguidance==0.7.30
llvmlite==0.44.0
lm-format-enforcer==0.11.3
markdown-it-py==4.2.0
MarkupSafe==3.0.3
mdurl==0.1.2
mistral_common==1.11.7
mpmath==1.3.0
msgpack==1.2.2
msgspec==0.21.1
multidict==6.8.0
multiprocess==0.70.16
networkx==3.6.1
ninja==1.13.2
numba==0.61.2
numpy==2.2.6
nvidia-cublas-cu12==12.8.4.1
nvidia-cuda-cupti-cu12==12.8.90
nvidia-cuda-nvrtc-cu12==12.8.93
nvidia-cuda-runtime-cu12==12.8.90
nvidia-cudnn-cu12==9.10.2.21
nvidia-cufft-cu12==11.3.3.83
nvidia-cufile-cu12==1.13.1.3
nvidia-curand-cu12==10.3.9.90
nvidia-cusolver-cu12==11.7.3.90
nvidia-cusparse-cu12==12.5.8.93
nvidia-cusparselt-cu12==0.7.1
nvidia-nccl-cu12==2.27.3
nvidia-nvjitlink-cu12==12.8.93
nvidia-nvtx-cu12==12.8.90
openai==3.13.0
openai-harmony==0.0.8
opencv-python-headless==5.0.0.93
outlines_core==0.2.11
packaging==26.3
pandas==3.0.5
partial-json-parser==0.2.1.1.post7
pillow==11.3.0
prometheus-fastapi-instrumentator==8.1.0
prometheus_client==0.26.0
propcache==0.5.2
protobuf==7.36.1
psutil==7.2.2
py-cpuinfo==9.0.0
pyarrow==25.0.1
pybase64==1.5.0
pycountry==26.2.16
pycparser==3.0
pydantic==2.13.5
pydantic-extra-types==2.11.1
pydantic-settings==2.15.0
pydantic_core==2.46.5
Pygments==2.21.0
python-dateutil==2.9.0.post0
python-dotenv==1.2.3
python-json-logger==4.2.0
python-multipart==0.0.32
PyYAML==6.0.3
pyzmq==27.2.0
ray==2.58.0
referencing==0.37.0
regex==2026.9.10
requests==2.34.2
rich==15.0.0
rich-toolkit==0.20.5
rignore==0.8.1
rpds-py==2026.6.3
safetensors==0.6.2
scipy==1.18.1
sentencepiece==0.2.2
sentry-sdk==2.69.1
setproctitle==1.3.7
setuptools==79.0.1
shellingham==1.5.4
six==1.17.0
sniffio==1.3.1
soundfile==0.14.0
soxr==1.1.0
starlette==1.6.0
sympy==1.14.0
tiktoken==0.14.0
tokenizers==0.22.2
torch==2.8.0+cu128
torchaudio==2.8.0+cu128
torchvision==0.23.0+cu128
tqdm==4.70.1
transformers==4.57.1
triton==3.4.0
truststore==0.10.4
typer==0.27.2
typing-inspection==0.4.4
typing_extensions==4.16.0
urllib3==2.7.0
uvicorn==0.53.0
uvloop==0.22.1
vllm==0.11.0
watchfiles==1.2.0
websockets==17.1
wheel==0.48.0
xformers==0.0.32.post1
xgrammar==0.1.25
xxhash==4.0.1
yarl==1.24.5
```

</details>

### 8.5 모델·데이터셋 아티팩트 리비전

| 항목 | 값 |
| :--- | :--- |
| 모델 repo_id | Qwen/Qwen3-VL-4B-Instruct |
| 모델 revision (커밋 SHA) | ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| 모델 로컬 경로 | /workspace/.cache/huggingface/hub/models--Qwen--Qwen3-VL-4B-Instruct/snapshots/ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| dtype | bfloat16 |
| attn_implementation | vllm 내부 백엔드 (transformers attn_implementation 미적용) |
| 데이터셋 repo_id 또는 경로 | MMMU/MMMU |
| 데이터셋 revision | 98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68 |
| 분할(split) | validation |
| 표본 수 | 900 |

두 리비전이 커밋 SHA 로 고정되어 있어야 결과가 재현 가능합니다. `main` 은 움직이는 포인터이며, MMMU/MMMU 의 데이터 파일은 67.4 공개 이후에도 세 차례 변경되었습니다(FACTS 6).

### 8.6 실행 설정 (inference settings)

| 설정 키 | 값 |
| :--- | :--- |
| aggregation | micro / sample-weighted |
| backend | vllm |
| context.allow_output_squeeze | False |
| context.limit_mm_per_prompt.image | 5 |
| context.limit_mm_per_prompt.video | 0 |
| context.max_model_len | 9048 |
| context.max_new_tokens | 2048 |
| data_path | MMMU/MMMU |
| determinism.full_determinism | False |
| determinism.note | FACTS 7: enable_full_determinism() 은 CUDA_LAUNCH_BLOCKING=1 을 켜서 소요 시간 측정을 무의미하게 만들므로 사용하지 않았습니다. |
| determinism.parser_seed | 42 |
| determinism.sample_order | load_mmmu 의 (SUBJECTS 인덱스, id 의 문항 번호) 정렬 |
| determinism.seed | 3407 |
| determinism.vllm_enable_v1_multiprocessing | 0 |
| engine.attn_implementation | vllm 내부 선택 |
| engine.enforce_eager | False |
| engine.gpu_memory_utilization | 0.9 |
| engine.max_num_seqs | 32 |
| limit | N/A |
| metrics_accuracy_scale | fraction_0_1 (백분율로 쓰려면 100을 곱하십시오) |
| out_dir | /workspace/MMDL/outputs/baseline-vllm-anchored-seed3407 |
| pixel_budget.max_pixels | 4014080 |
| pixel_budget.max_pixels_spec | 5120*28*28 |
| pixel_budget.max_vision_tokens_per_image | 3920 |
| pixel_budget.min_pixels | 1003520 |
| pixel_budget.min_pixels_spec | 1280*28*28 |
| pixel_budget.min_vision_tokens_per_image | 980 |
| pixel_budget.note | Qwen3-VL 은 patch_size 16 * spatial_merge_size 2 = 32 그리드이므로 visual token 1개가 32x32=1024 px 를 덮습니다. 교수님 슬라이드의 '*28*28' 은 Qwen2.5-VL 관례이며 Qwen3-VL 에서는 토큰 수를 뜻하지 않습니다. |
| pixel_budget.pixels_per_vision_token | 1024 |
| pixel_budget.precount_max_pixels | 4014080 |
| pixel_budget.precount_min_pixels | 1003520 |
| pixel_budget.processor_size_forced | False |
| pixel_budget.processor_size_requested.longest_edge | 4014080 |
| pixel_budget.processor_size_requested.shortest_edge | 1003520 |
| pixel_budget.processor_size_resolved.longest_edge | 4014080 |
| pixel_budget.processor_size_resolved.shortest_edge | 1003520 |
| pixel_budget.smart_resize_factor | 32 |
| presence_penalty_mechanism.applied | True |
| presence_penalty_mechanism.mechanism | vllm.SamplingParams.presence_penalty (네이티브, 가산형) |
| presence_penalty_mechanism.note | vLLM 공식 구현. logits -= penalty * (생성된 토큰 여부), prompt 제외, 횟수 무시. |
| presence_penalty_mechanism.requested | 1.5 |
| sampling.max_new_tokens | 2048 |
| sampling.note | temperature>0 이므로 표본 추출이 확률적입니다. FACTS 7: n=900, p=0.674 에서 서로 독립인 두 실행의 차이에 대한 95% 구간은 ±4.33pp 이므로 팀원 간 1~2pp 차이는 잡음입니다. |
| sampling.presence_penalty | 1.5 |
| sampling.repetition_penalty | 1.0 |
| sampling.seed | 3407 |
| sampling.temperature | 0.7 |
| sampling.top_k | 20 |
| sampling.top_p | 0.8 |
| split | validation |
| subjects_filter | N/A |
| template | anchored |
| timing_note | total_wall_s 는 이번 프로세스 wall clock + 이어받은 추론 시간입니다. model_load_s 는 별도로 측정하여 알파벳순 첫 과목에 엔진 시작 비용이 섞이지 않게 했습니다. |

#### 픽셀 예산이 실제로 뜻하는 것

- 전달된 `min_pixels` = `N/A`, `max_pixels` = `N/A`
- Qwen3-VL-4B-Instruct 는 `patch_size=16`, `spatial_merge_size=2` 이므로 smart_resize 격자가 32 이고, **시각 토큰 1개가 32×32 = 1,024 픽셀**을 담습니다(FACTS 1).
- 따라서 교수님 슬라이드의 `1280*28*28` = 1,003,520 px 는 이미지당 **약 980 토큰 하한**, `5120*28*28` = 4,014,080 px 는 **약 3,920 토큰 상한**을 뜻합니다. `*28*28` 표기는 Qwen2-VL / Qwen2.5-VL 의 관례(토큰당 14×2=28 격자, 784 px)이며 Qwen3-VL 에서는 토큰 수와 일치하지 않습니다.
- 공식 QwenLM/Qwen3-VL README 권장값은 32 격자로 쓴 `{"shortest_edge": 256*32*32, "longest_edge": 1280*32*32}`, 즉 이미지당 256~1,280 토큰입니다. 본 실행의 상한은 그보다 약 3배 큽니다 → 속도와 점수 모두 달라질 수 있습니다.
- 재현성을 위해서는 공식이 아니라 **해석된 `processor.image_processor.size` 딕트**를 기록해야 합니다. `AutoProcessor.from_pretrained()` 에 `max_pixels` 를 넘기는 방식은 transformers 4.57.1 이하에서 조용히 무시되었습니다(transformers #41955, PR #41997 에서 수정).

### 8.7 Git 상태

| 항목 | 값 |
| :--- | :--- |
| commit | N/A |
| branch | N/A |
| dirty | N/A |

### 8.8 환경 수집 시 기록된 메모

| 항목 | 내용 |
| :--- | :--- |
| file_purpose | 이 파일은 eval 스크립트가 모델을 적재하기 전에 자동으로 생성합니다(FACTS 12). 손으로 고치지 마십시오. 팀원끼리 환경이 같은지 확인할 때는 `python -m src.capture_env --check <상대방의 env.json>` 을 실행해 한국어 비교 표를 보십시오. |
| cuda_versions | CUDA 버전 세 개는 서로 다른 것을 가리키므로 값이 일치하지 않는 것이 정상입니다(FACTS 9). ① nvidia_smi_cuda = 설치된 드라이버가 지원하는 최대 CUDA 런타임 버전. ② nvcc_version = 컨테이너에 설치된 로컬 CUDA 툴킷 버전이며, 보통 설치되어 있지 않고 미리 빌드된 PyTorch 휠과는 아무 관계가 없습니다(null 이어도 정상). ③ torch_version_cuda = 실제로 중요한 값으로, 사용 중인 PyTorch 휠이 어떤 CUDA 로 빌드되었는지를 나타냅니다. 예컨대 nvidia-smi 가 13.0 인데 torch.version.cuda 가 12.9 인 상태는 '올바른' 상태이며 아무것도 고칠 필요가 없습니다. CUDA 12.x 는 드라이버 525 이상, 13.x 는 580 이상만 요구합니다. 이 항목을 맞추려고 드라이버나 툴킷을 재설치하며 시간을 쓰지 마십시오. |
| container_image_digest | 컨테이너 이미지 다이제스트는 컨테이너 내부에서 읽을 수 없습니다(FACTS 8). RepoDigests 는 Docker 데몬 메타데이터에 있고 로컬 image ID 는 전혀 다른 해시입니다. 따라서 image_digest 는 구조적으로 null 이며, 정확히 남기려면 RunPod 템플릿에서 이미지 태그를 환경 변수로 주입한 뒤 레지스트리에 HEAD 요청을 보내 다이제스트를 확인해야 합니다. |
| artifact_revision | model.revision 과 dataset.revision 은 'main' 같은 가변 포인터가 아니라 해석된 40자 커밋 SHA 여야 합니다(FACTS 6). MMMU/MMMU 의 데이터 파일은 공개 점수 67.4 가 발표된 이후에도 2026-02-12, 2026-04-21, 2026-07-10 에 변경되었으므로 'MMMU/MMMU' 라는 이름만으로는 재현이 불가능합니다. vLLM 을 쓸 때는 tokenizer_revision 도 따로 고정해야 합니다(기본값 None 이면 main 을 따라갑니다). |
| runpod_driver | RunPod 의 머신은 호스트마다 NVIDIA 드라이버가 다릅니다(FACTS 8). 파드를 고를 때 UI 의 Filters > CUDA version(또는 GraphQL 의 allowedCudaVersions)으로 드라이버 CUDA 를 고정해 팀원 4명이 같은 드라이버를 받도록 하십시오. 드라이버가 다르면 커널 경로가 달라져 설명할 수 없는 정확도 차이가 생깁니다. |
| determinism | temperature=0.7 / top_p=0.8 / top_k=20 은 확률적 샘플링이므로 실행은 비트 단위로 재현되지 않고 팀원 4명의 점수는 서로 다릅니다(FACTS 7). n=900, p=0.674 에서 한 문제는 0.111pp, 표준오차는 1.56pp, 독립 실행 두 번의 차이에 대한 95% 구간은 ±4.33pp 입니다. 즉 1~2pp 차이는 버그가 아니라 노이즈입니다. 원인을 확인하려면 예측을 diff 하십시오(샘플링 노이즈는 원문 차이가 많고 라벨 변화가 적으며, 파서/정답키 버그는 원문 차이가 적은데 점수 차이가 큽니다). 또한 타이밍 표를 위해 transformers.enable_full_determinism() 은 쓰지 마십시오(CUDA_LAUNCH_BLOCKING=1 때문에 경과 시간이 무의미해집니다). |
| gpu_detail | GPU 0: NVIDIA GeForce RTX 4090, 24564 MiB, 드라이버 580.159.04, sm_89 (출처 nvidia-smi) |
| cpu_detail | 프로세스에 할당된 논리 CPU 64개 / os.cpu_count() 기준 64개. 컨테이너에서는 두 값이 다를 수 있으며, 할당된 값이 실제 전처리 병렬도를 결정합니다. |
| memory_detail | 시스템 RAM 503.55 GiB, 컨테이너 메모리 상한 93.13 GiB (cgroup) |
| torch_detail | torch 2.8.0+cu128, torch.version.cuda=12.8, cudnn=91002, cuda.is_available()=True |
| pip_freeze_source | pip freeze, 총 156개 패키지 |
| stack | STACK A (FACTS 5 권장: vllm 0.11.0 + transformers 4.57.1, 공개 점수 67.4 발표 시점과 릴리스가 맞는 조합) |
| model_revision_resolution | 요청 'ebb281ec70b05090aa6165b016eac8ec08e71b17' -> 확정 'ebb281ec70b05090aa6165b016eac8ec08e71b17' (해석 경로: 인자로 받은 값이 이미 커밋 SHA) |
| dataset_revision_resolution | 요청 '98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68' -> 확정 '98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68' (해석 경로: 인자로 받은 값이 이미 커밋 SHA) |
| probe_errors.git.repo | 탐지에 실패했습니다 (RuntimeError: `git rev-parse --is-inside-work-tree` 가 종료 코드 128 로 실패했습니다: fatal: not a git repository (or any parent up to mount point /) Stopping at filesystem boundary (GIT_DISCOVERY_ACROSS_FILESYSTEM not set).) |
| probe_errors.os.container.image_digest | FACTS 8: 컨테이너 안에서는 자신의 이미지 다이제스트를 읽을 수 없습니다(RepoDigests 는 Docker 데몬 메타데이터이고 로컬 image ID 는 다른 해시입니다). 구조적으로 null 입니다. |
| probe_errors.os.container.image_tag | 컨테이너 이미지 태그를 알려 주는 환경 변수가 없습니다. RunPod 템플릿의 환경 변수에 RUNPOD_IMAGE_NAME 을 추가하면 자동으로 기록됩니다(FACTS 8). |
| probe_errors.packages.flash-attn | 설치되어 있지 않습니다. FACTS 5 기준으로 이는 정상이며 의도된 상태입니다(flash-attn 은 sdist 전용이라 긴 컴파일이 필요하고, Qwen3VL 은 _supports_sdpa=True 이므로 attn_implementation="sdpa" 로 충분합니다). |
| probe_errors.packages.qwen-vl-utils | 설치되어 있지 않습니다. FACTS 5 기준으로 이미지 전용 MMMU 베이스라인에는 필요하지 않은 선택 패키지입니다. |
| probe_warnings | /workspace/MMDL 가 git 저장소가 아니어서 커밋을 기록할 수 없습니다. 제출용 실행은 반드시 커밋된 상태에서 해야 합니다(FACTS 12). |

> 팀 비교 시 주의: FACTS 7 에 따르면 재현성은 **동일 하드웨어 + 동일 vLLM 버전**에서만 성립합니다. 위 표의 GPU, 드라이버, `torch`/`transformers`/`vllm` 버전이 팀원 간에 다르면 점수 차이를 샘플링 노이즈로 설명할 수 없습니다.

## 9. 공개 성능과의 비교

| 항목 | 값 |
| :--- | :--- |
| 공개 보고 점수 (MMMU validation) | 67.40 % |
| 출처 | Qwen3-VL technical report arXiv:2511.21631 |
| 본 실행 점수 (micro) | 59.33 % |
| 차이 (본 실행 − 공개) | -8.07 pp |
| n = 900, p = 0.674 기준 1문항의 가치 | 0.111 pp |
| n = 900, p = 0.674 기준 표준오차(SE) | 1.56 pp |
| 독립적인 두 실행의 차이에 대한 95 % 구간 | ±4.33 pp |
| 관측값 기준 표준오차 sqrt(p(1−p)/n) | 1.64 pp |
| 차이 / 관측 SE | 4.93 배 |

**판정**: 차이 -8.07 pp 는 n=900 의 표준오차 1.56 pp 의 1.96배(±3.06 pp)를 넘습니다. 단순 표본오차로는 설명되지 않으므로, 아래 9.1 의 항목들을 순서대로 점검해야 합니다.

### 9.1 로컬 수치가 공개 수치와 정당하게 달라지는 이유

아래 다섯 가지는 구현이 정확해도 점수가 달라지는, 이미 알려진 원인들입니다.

1. **프롬프트 템플릿** — 본 실행은 `--template anchored` 를 사용했습니다. MMMU 가 제공하는 유일한 템플릿은 LLaVA 시절의 범용 프롬프트이고, 템플릿을 바꾸면 MMMU 점수가 몇 점 단위로 움직입니다. 공개 점수가 어떤 템플릿으로 측정되었는지는 공개되어 있지 않습니다(FACTS 11).
2. **추론 프레임워크** — 본 실행의 백엔드는 `vllm` 입니다. 교수님도 "The results may vary slightly depending on the inference framework" 라고 명시했습니다(슬라이드 16). 특히 `presence_penalty=1.5` 는 transformers 의 `GenerationConfig` 에 존재하지 않는 인자여서 vLLM 경로에서만 적용됩니다(FACTS 2). 또한 lmms-eval 의 객관식 파서는 공식 파서에 없는 추가 패스를 갖고 있어 **동일한 생성 결과에서도 더 높은 점수**를 보고합니다(FACTS 10).
3. **샘플링 확률성** — `temperature=0.7`, `top_p=0.8`, `top_k=20` 은 확률적 디코딩입니다(FACTS 7). 같은 코드·같은 하드웨어에서도 실행마다 점수가 달라지며, n=900 에서 표준오차는 1.56 pp, 독립적인 두 실행의 차이는 95 % 구간이 ±4.33 pp 입니다. 공개 점수와 1~2 pp 차이는 노이즈로 보아야 합니다.
4. **데이터셋 리비전 드리프트** — 본 실행의 데이터셋 리비전은 `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` 입니다. MMMU/MMMU 의 데이터 파일은 2026-02-12, 2026-04-21, 2026-07-10 의 "Upload dataset" 커밋으로 변경되었습니다. 즉 67.4 가 공개된 뒤에 데이터가 바뀌었으므로, 공개 점수와 현재 데이터는 애초에 완전히 같은 문제 집합이 아닐 수 있습니다(FACTS 6).
5. **픽셀(시각 토큰) 예산** — Qwen3-VL 의 격자는 32 이고 토큰 1개가 1,024 px 를 담습니다. 교수님의 `1280*28*28` / `5120*28*28` 은 이미지당 약 980 / 3,920 토큰으로 해석되며, 공식 README 권장인 256~1,280 토큰보다 최대 3배 큽니다(FACTS 1). 시각 토큰 수는 해상도 인식에 직접 영향을 주므로 점수와 속도가 함께 변합니다.

여기에 더해 객관식 파서의 무작위 추측(FACTS 4c)이 남아 있습니다. 파서가 실패하면 공식 구현은 무작위로 한 선택지를 고르므로, 미파싱 문항 수만큼 점수에 난수 성분이 섞이고 그 값은 문항 순회 순서에까지 의존합니다. 6절의 `n_unparseable` 을 함께 보고하십시오.

### 9.2 보고 시 권장 문장

> 본 팀의 로컬 측정값은 59.33 % 로, 공개 보고값 67.40 %(Qwen3-VL technical report arXiv:2511.21631) 대비 -8.07 pp 입니다. n=900 에서 1문항은 0.111 pp, 표준오차는 1.56 pp 이므로 이 정도 차이는 프롬프트 템플릿, 추론 프레임워크, 샘플링 확률성, 데이터셋 리비전, 시각 토큰 예산의 차이로 설명할 수 있는 범위입니다.

---

*본 문서는 `src/report.py` (report.py / MMMU baseline report generator v1) 가 자동 생성했습니다. 수치의 출처는 `/workspace/MMDL/outputs/baseline-vllm-anchored-seed3407` 의 metrics.json / timing.json / env.json / predictions.jsonl 입니다.*

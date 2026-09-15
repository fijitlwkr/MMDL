# Baseline Evaluation 결과 공유 (Qwen3-VL-4B-Instruct / MMMU val)

실행일 2026-09-15 · RunPod RTX 4090 · 총 비용 $0.82

## 결과 한눈에

| 항목 | 값 |
|---|---|
| **전체 정확도** | **59.3%** (534 / 900) |
| 공개 점수 (Qwen 공식) | 67.4% |
| 차이 | −8.1 pp |
| 객관식 (847문항) | 61.3% |
| 주관식 (53문항) | 28.3% |
| 파싱 실패 → 무작위 처리 | 48문항 (5.3%) |
| 추론 시간 | 15분 (900문항) |

## 카테고리별

| 카테고리 | 정확도 | n |
|---|---|---|
| 인문·사회 | 73.3% | 120 |
| 경영 | 69.3% | 150 |
| 보건·의학 | 67.3% | 150 |
| 예술·디자인 | 64.2% | 120 |
| 과학 | 49.3% | 150 |
| **기술·공학** | **42.9%** | 210 |

약한 과목 TOP 5: Chemistry 23.3% · Electronics 26.7% · Architecture_and_Engineering 36.7% · Mechanical_Engineering 40.0% · Diagnostics_and_Laboratory_Medicine 40.0%

강한 과목: Marketing 86.7% · Economics 86.7% · Design 83.3% · Literature 80.0% · Public_Health 80.0%

## 발견한 것

**파싱 실패 48개는 전부 `max_new_tokens=2048`에서 잘린 것.**
모델이 계산을 길게 하다가 답을 내기 전에 끊김. 공학·수학·회계에 집중.

```
문제 → 모델이 풀이 시작 → 2048 토큰 도달 → 강제 종료 → 답 없음 → 무작위 찍기
```

→ 계산 위주 과목은 토큰 한도를 늘리면 바로 점수가 오를 가능성 있음.

## 실험 환경

| 항목 | 값 |
|---|---|
| GPU | RTX 4090 24GB (RunPod) |
| 드라이버 / CUDA | 580.159.04 / 12.8 |
| Python | 3.12.3 |
| torch | 2.8.0+cu128 |
| transformers | 4.57.1 |
| vLLM | 0.11.0 |
| 모델 revision | `ebb281ec70b05090aa6165b016eac8ec08e71b17` |
| 데이터 revision | `98e6ac0cb9b7b2cd2c991b85a50762edc4aedc68` |
| seed | 3407 |

추론 설정은 교수님 슬라이드 그대로 (temp 0.7 / top_p 0.8 / top_k 20 / presence 1.5 / max_model_len 9048).

## 주의: 픽셀 설정 해석

슬라이드의 `min_pixels = 1280*28*28`은 Qwen2.5-VL 기준. Qwen3-VL은 토큰 하나가 32×32라서 실제로는:

| 설정 | 슬라이드 의도 | Qwen3-VL 실제 |
|---|---|---|
| min_pixels | 1280 토큰 | **980 토큰** |
| max_pixels | 5120 토큰 | **3920 토큰** |

값은 그대로 써도 되지만 리포트엔 실제 토큰 수로 적어야 함.

## 파이프라인

```mermaid
flowchart LR
    A[MMMU val 900문항] --> B[프롬프트 생성]
    B --> C[vLLM 추론]
    C --> D[답 파싱]
    D --> E[채점]
    E --> F[과목/카테고리별 집계]
    F --> G[report.md + env.json]
```

## 재현 방법

```bash
bash scripts/setup_pod.sh      # 환경 설치 (15분)
bash scripts/fetch_data.sh     # 데이터 + 모델 다운로드 (5분)
bash scripts/run_baseline.sh   # 평가 + 리포트 (20분)
```

결과물: `outputs/baseline-vllm-anchored-seed3407/` 안의 `metrics.json` · `timing.json` · `env.json` · `report.md`

## 팀원 결과 비교할 때

같은 seed여도 GPU·드라이버·버전이 다르면 1~2pp 차이는 정상 (n=900 표준오차 1.6pp).
그 이상 차이 나면 `env.json` 비교해서 버전 차이부터 확인.

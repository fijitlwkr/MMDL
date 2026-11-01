# 가설 B 평가 2단계 GPU 생성 결과 — 2026-11-01

E1 소량 시험과 E1·E2 각각 900문항 생성을 완료했다.
기본 Python의 Torch 메타데이터와 런타임 버전은 설치 전후·각 생성 후 모두 2.8.0+cu128로 유지됐다.
Judge 호출은 0회이며, 파드는 Stop/Terminate하지 않았다.

## 실행 조건과 소스

- 생성 소스 Git: 9fe57b1176caa74435d1c739de93e9de96e857df, exp/hypB-data.
- 평가 코드 기준 main: 016b3cf558e3dd9e366b277f5f871b28092a1379.
  verify_code.py의 40개 소스 해시가 실행 전후 일치했고 파드 Git 작업 트리도 깨끗했다.
- 실제 생성 config SHA-256:
  a41d4973f753da715b8cf5258913ff075b5de60ffdc014ee4eb58dea17e41ce7.
  check_env.py·gate·config.yaml·requirements.txt는 수정하지 않았다.
- GPU: NVIDIA GeForce RTX 4090 1개, 24,564 MiB, driver 595.91.07.
- 이미지(사용자 지정): runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404.
- 생성: 이미지 기본 /usr/bin/python3.12 (3.12.3), Torch 2.8.0+cu128, CUDA build 12.8,
  vLLM 0.11.0, Transformers 4.57.1, Tokenizers 0.22.2. 기본 환경에 PEFT는 없다.
- 병합: 기존 /workspace/hypB-eval-env만 사용. PEFT 0.17.1과 기존 merge.py로 bf16 병합했다.
  이 venv의 Torch 배포 메타데이터 2.8.0은 병합에만 사용하며 생성 PATH에 넣지 않았다.
- HF_HOME=/workspace/hf_cache. 작업·캐시·결과는 /workspace에 보관했다.
  기본 Python 패키지 설치는 사용자 지시에 따라 이미지의 기본 설치 위치를 사용했다.
- 세부 평가 조건은 PLAN.md 그대로이다. validation 30과목 × 30 = 900,
  출력 예산 8192, 모델 길이 16384, seed 3407, 샘플링·이미지·프롬프트 모두 고정했다.

| 구성 | 저장소 | 고정 revision |
|---|---|---|
| 원본 | Qwen/Qwen3-VL-4B-Instruct | ebb281ec70b05090aa6165b016eac8ec08e71b17 |
| E1 adapter | MMDL-team4/hypB-e1-structured-3k | 0de38ff61af238608dc7be53358f1dac23788995 |
| E2 adapter | MMDL-team4/hypB-e2-answer-3k | 72e45c1bb07eb79179739fae949ccf80f21e891b |

기본 환경 패키지와 병합 환경 패키지는 각각
[generation packages](generation_20261101/packages_generation.txt),
[merge packages](generation_20261101/packages_merge.txt)에 기록했다.
[환경 요약](generation_20261101/environment_summary.json)에는 Torch 유지·PEFT 미설치·이미지·GPU·소스가 있다.

## 소량 시험

별도 smoke_E1/에서 3문항을 생성해 끝까지 검증했다.
생성 시간 184.759초, 출력 토큰 2,770개, length 0개, 정상 3행이다.
시험 raw·기록은 로컬 runs/smoke_E1/에 보관했고 파드·로컬 해시가 일치했다.
세 문항의 입력과 프롬프트 토큰 수도 M0와 일치했다.

본 실행은 각각 새 E1/, E2/에서 원본과 고정 adapter를 다시 병합하고 처음부터 시작했다.
본 생성은 실행별 invocation 1회이며 시험 raw와 섞지 않았다.

## 본 생성 결과

| 항목 | E1 | E2 |
|---|---:|---:|
| 생성 시간 | 1,327.053초 (22분 7.053초) | 389.278초 (6분 29.278초) |
| 정상 / 고유 ID | 900 / 900 | 900 / 900 |
| 과목 구성 | 30 × 30 | 30 × 30 |
| skip / error | 0 / 0 | 0 / 0 |
| length 종료 | 6/900 (0.67%) | 0/900 (0%) |
| 입력 토큰 합계 | 1,193,656 | 1,193,656 |
| 입력 토큰 평균 | 1,326.28 | 1,326.28 |
| 출력 토큰 합계 | 920,965 | 4,691 |
| 출력 토큰 평균 | 1,023.29 | 5.21 |
| 최대 VRAM (nvidia-smi) | 22,280 MiB | 22,280 MiB |
| 병합 safetensors 총 크기 | 8,875,719,328 bytes | 8,875,719,328 bytes |

시간은 main run_metadata.json의 run.duration_seconds이다.
모델 초기화·그래프 컴파일을 포함하며 설치·병합·별도 preflight 시간은 제외한다.
E1 완료 직후 생성 시간·length 수를 중간 보고한 뒤 E2를 시작했다.

- 두 실행 모두 환경 게이트·900문항 preflight를 통과했다.
  입력 초과 0, validation failure 0, partial=false이다.
- 생성 직전 main 환경 게이트는 두 실행 모두 PASS 15 / INFO 10 / FAIL 0 / WARN 0이다.
  앞단 전체 검사에 있던 환경변수 WARN 3개는 main의 config 환경변수 export 전에 발생한 것으로,
  실제 생성 시점에는 모두 설정되어 통과했다.
- main raw 검증과 로컬 검증을 모두 통과했다.
  전체 900문항의 ID·문항 입력·프롬프트·프롬프트 토큰 수는 M0와 일치했다.
  raw의 문항·응답은 수정하지 않았다.
- Torch 재설치 로그가 없고 버전은 계속 2.8.0+cu128이다.
  기본 Python에 PEFT를 추가하지 않았다.
- 결과는 생성·검증 통계이다. 정확도 채점과 가설 판정은 수행하지 않았다.

상세 숫자는 [E1 요약](generation_20261101/E1_summary.json),
[E2 요약](generation_20261101/E2_summary.json)에 있다.

## raw 전송과 해시

| 실행 | 파드·로컬 공통 raw SHA-256 |
|---|---|
| E1 | a6e307b88a0c8ab6afd4a76d6706004736ec4b8319a94a014e54fe0faa43e317 |
| E2 | 0026e5e6437f8c0ece78ca7c627847eff120783cc737e44faead4d41b8d92d1a |

로컬 MMDL 루트 기준 경로:

- work/eval_B_20261101/runs/E1/generation/raw.jsonl
- work/eval_B_20261101/runs/E2/generation/raw.jsonl
- 각 runs/E1/, runs/E2/에는 metadata·env·로그·게이트·preflight·병합 receipt와 파일별 해시도 있다.
- 공통 환경·설치·실행 기록: work/eval_B_20261101/runs/baseline_environment_20261101/.
- 최초 중단 기록: work/eval_B_20261101/runs/setup_20261101/.
  재개 시 PEP 668 최초 오류 기록도 공통 백업에 포함했다.

raw 및 실행별 압축 기록의 파드·로컬 SHA-256이 모두 일치했다.
[E1 전송 검증](generation_20261101/E1_transfer_verification.json),
[E2 전송 검증](generation_20261101/E2_transfer_verification.json),
[공통 기록 검증](generation_20261101/common_transfer_verification.json)에 보관했다.

병합 safetensors의 파일별 SHA-256은
[E1](generation_20261101/E1_merged_safetensors.sha256),
[E2](generation_20261101/E2_merged_safetensors.sha256)에 있다.
병합 모델은 HF나 GitHub에 올리지 않았다.

## 설치 변경 기록

1. 최초 setup_gpu.sh는 baseline과 달리 새 venv를 생성해 PyPI Torch 메타데이터 2.8.0을 설치했다.
   고정 게이트의 2.8.0+cu128 조건을 통과하지 못해 생성 전에 중단했다.
   [최초 실패 요약](gpu_20261101_setup/failure_summary.json)과 원본 기록을 보존했다.
2. 사용자 지시에 따라 기본 Python을 먼저 검사했다.
   배포 메타데이터와 torch.__version__ 모두 2.8.0+cu128임을 확인한 뒤 설치했다.
   setup_gpu.sh의 venv 생성·PEFT 설치를 제거하고, 기본 Python에서 main과 같은 requirements 설치를 사용했다.
3. 이때 main 설치 블록의 PEP 668 처리를 처음 옮길 때 누락해 기본 설치 명령이 중단됐다.
   main에 이미 있는 externally-managed-environment 감지와 --break-system-packages 재시도를 그대로 반영했다.
   수정 커밋은 c8da6867f1dbd4f5f4dc227eb95bbb8402d0aa4d 및 9fe57b1176caa74435d1c739de93e9de96e857df이다.
4. 수정 후 기본 환경 설치는 약 105초였으며, 기존 Torch는 requirements를 이미 만족해 재설치되지 않았다.
   설치 후 버전 확인과 pip check를 통과했다. 실제 생성도 기본 Python의 main run_generate.sh --install을 사용했다.
5. 기존 venv는 병합에만 사용했다. 게이트·config·requirements 수정, 다른 인덱스의 Torch 재설치,
   게이트 우회는 하지 않았다. raw와 팀원 결과도 수정하지 않았다.

## 보관과 종료 판단

Git에는 스크립트·요약·패키지/GPU 정보·해시와 검증 기록만 포함한다.
raw·문항별 응답·채점 결과·모델 가중치·HF 캐시·토큰은 포함하지 않는다.
main merge·PR·HF 업로드는 하지 않았다.

2단계는 완료됐다. 원본 raw와 실행 기록이 로컬에 백업됐고 해시 대조도 끝났다.
실행 중인 GPU 작업은 없으며 최종 GPU 상태는 1 MiB / 0%였다.
기록 보존 측면에서 파드를 Stop해도 된다. 파드 Stop/Terminate는 사용자가 직접 수행한다.

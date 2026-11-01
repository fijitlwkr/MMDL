# 가설 B 평가 1단계 준비 결과

- 날짜: 2026-11-01. 로컬 CPU만 사용, GPU 작업·Judge API 호출 0회.
- 브랜치: exp/hypB-data. 시작 전 git pull --ff-only 완료.
- 시작 Git: cc8fe32c9f6c811c0e1fc83068b2ed288fbca531.
- 평가 코드 기준 main: 016b3cf558e3dd9e366b277f5f871b28092a1379.
  main code/와 현재 code/의 Git 차이 없음.
- code_freeze.json은 code/ 35개와 재사용 분석·학습 병합 관련 5개 파일을 고정한다.
  Windows 줄바꿈 차이만 LF로 정규화해 검증하며 코드 내용은 수정하지 않았다.
- raw·문항별 채점·팀원 결과·평가 조건·판정 기준 변경 없음. MMMU validation 기존 결과만 읽었다.
- 커밋에는 요약·스크립트·128개 ID만 포함한다. push는 하지 않는다.

## M0 재현

원문:
assignment/experiments/received_20260922/results/input/raw.jsonl

SHA-256:
ef23f0c49d9b1ae6c62b9625fbd52cce474a0c035c1a644cfa737e0967daa313

채점:
work/team-evaluator-no-length/assignment/experiments/raw_evaluation/outputs/release-v2-latest/

| 항목 | 기대 | 실측 | 확인 |
|---|---:|---:|---|
| v2 정답 | 600/900 | 600/900 (66.67%) | 일치 |
| 객관식 | 560/847 | 560/847 | 일치 |
| 주관식 | 40/53 | 40/53 | 일치 |
| 자동 / Judge | 555 / 345 | 555 / 345 | 일치 |
| 추출 실패 | 36 | 36 | 일치 |
| length 종료 | 128 | 128 (14.22%) | 일치 |
| length 중 v2 정답 | 46 | 46/128 | 일치 |
| 방향 전환 과다 | 217/900 | 217/900 (24.11%) | 일치 |
| Judge 없는 MMMU 참고 점수 | 기록 | 452/900 (50.22%) | 계산 완료 |

Judge 경로는 충돌 4 + 규칙 실패 341이다.
참고 MMMU 점수는 random fallback을 제거한 기존 진단 함수 그대로이며 추출 실패는 69개이다.
반복 후보는 기존 검출 기준으로 73/900 (8.11%)이다.
출력 토큰은 총 1,813,255, 평균 2,014.73, 중앙값 456, 최소 4, 최대 8,192이다.

방향 전환 마커는 wait, perhaps, alternatively, actually, however, reconsider, re-examine, re-evaluate이다.
대소문자 무시·단어 경계로 합계 ≥ 21을 적용했다. 기대값을 맞추기 위한 규칙 변경은 없었다.
m0_length_ids.txt에는 128문항의 ID만 저장했으며 목록의 SHA는 각 요약에 기록했다.
유형·분야·30과목·종료 사유·처리 경로별 정확도는 preparation_v2/m0_summary.json에 있다.

## k0 재현

사용한 파일은 모두
work/error-analysis-A/results/baseline_seed_robustness/{실행}/item_results.jsonl 이다.
기존 v2 Judge 포함 final_correct를 M0 고정 128문항에 맞춰 계산했다.
각 파일·manifest SHA는 preparation_v2/k0_reproduction.json에 보관했다.

| 실행 | 기대 net_gain | 오답→정답 | 정답→오답 | 실측 net_gain |
|---|---:|---:|---:|---:|
| seed_42 | +10 | 22 | 12 | +10 |
| seed_1234 | +8 | 24 | 16 | +8 |
| seed_2026 | +5 | 17 | 12 | +5 |
| rep_draft | +12 | 23 | 11 | +12 |
| rep_new_output | +14 | 27 | 13 | +14 |

5개 모두 기대값과 일치한다.
seed 세 실행은 기존 raw.jsonl.gz·metadata·config diff도 검증했다.
변경은 요청 sampling.seed 3407→42/1234/2026뿐이며 engine seed 3407, 모델 revision, 900개 문항 입력은 동일하다.
rep 두 실행은 요청대로 기존 compact v2 채점 파일을 사용했으며 같은 seed·다른 서버 실행으로 기록했다.
재실행 raw 자체의 바이트 동일성까지 새로 확인했다고 주장하지 않는다.

참고 점수인 Judge 없는 128문항 net_gain은 seed_42 −7, seed_1234 −6, seed_2026 −8이다.
이는 v2 점수와 다른 채점 결과이며 1차 기준이나 k0를 대체하지 않는다.
k0 최종값은 아직 확정하지 않았다. 기존 실행 수치나 최댓값을 자동으로 선택하지 않는다.

## 집계·회귀 점검

| 점검 | 결과 |
|---|---|
| M0 vs M0, 고정 128문항 v2 net_gain | 0 |
| M0 vs M0, 900문항 v2 정확도 차이 | 0%p |
| M0 vs M0, 참고 net_gain·length·방향 전환·반복 차이 | 모두 0 |
| M0 vs seed_42, 고정 128문항 v2 net_gain | +10 (22 − 12) |
| M0 vs seed_42, 900문항 v2 정확도 차이 | −0.4444%p (63 − 67 = −4문항) |
| net_gain 방향·pending 처리, 마커 단어 경계 | 단위 점검 2개 통과 |
| 고정 코드 SHA 검증 | 40개 일치 |
| GPU bash 문법 | setup_gpu.sh, run_gpu.sh 모두 bash -n 통과 |
| 생성 자원 요약 함수 | 기존 M0 원문과 metadata/env로 검증 |
| k0 인자 변경 점검 | 테스트 입력 10 → 임계값 14, net_gain +10이므로 primary_pass=false |

preparation_v2/m0_vs_m0.json과 m0_vs_seed42.json에 전체 결과가 있다.
점검의 k0=0은 명시적 테스트 인자이며 합의값이 아니다.
추가 CLI 점검의 k0=10도 인자 반영 확인용 입력이며 최종값으로 선택한 것이 아니다.
CLI는 --k0 생략을 허용하지 않으며 임계값은 전달값 +4로 계산한다.
미완료 점수는 오답으로 바꾸지 않고 해당 비교·판정을 null로 유지한다.
M0와 seed 실행의 raw·채점 해시, 정책·Judge 설정, 문항 입력 동일성을 확인했다.

run_metrics.py의 SHA 거절 동작도 확인했다.
저장소 results/mmmu_team_baseline/raw.jsonl 사본은 Windows 줄바꿈으로 원문 metadata SHA와 달라 거절됐다.
이 사본을 고치거나 기준 SHA를 완화하지 않았다.
성공 점검은 사용자 지정 ef23f0c4 원문과 일치하는 metadata, 동일 실행의 기존 env.json을
Git 밖의 새 임시 폴더에 복사해 수행했다. 원본 파일은 수정하지 않았다.

## 2단계 준비와 자원 추정

대상: RTX 4090 1개, runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404,
HF_HOME=/workspace/hf_cache. 아직 파드에 접속하거나 환경을 설치하지 않았다.

- 원본 snapshot 약 8.88 GB + 병합 모델 2개 약 17.75 GB + adapter 2개 약 0.27 GB로,
  모델 관련 약 26.9 GB를 예상한다. 기존 4B 모델 크기에 근거한 추정이며 이번 다운로드 실측은 아니다.
- 별도로 Python 환경·설치 캐시 약 25–40 GB, MMMU 데이터·이미지 캐시, preflight/로그/결과 공간이 필요하다.
  데이터 캐시 크기는 이번 단계에서 재측정하지 않았다.
- main 생성 스크립트의 여유 디스크 20 GB 게이트를 유지한다.
  기존 캐시가 없는 새 /workspace라면 100 GB 이상 여유를 권장한다.
  실제 설치·다운로드 후 게이트로 다시 확인한다. 자동 삭제·캐시 정리는 하지 않는다.
- 기존 RTX 4090 M0 생성은 3,469.539초(57분 49.5초), 최대 VRAM 22,297 MiB였다.
  metadata/raw SHA와 env 토큰 합계 1,813,255가 일치함을 확인했다.
  이는 M0 과거 실측이며 E1/E2의 새 측정값이 아니다.
- 기존 seed 3개 생성은 5,829–6,385초(약 97–106분)였다.
  따라서 900문항 두 번 생성만 약 2–3.6시간, 새 환경·다운로드·두 병합·preflight까지
  포함하면 약 3–5시간을 예상한다. 다운로드 속도와 E1/E2 출력 길이에 따라 달라진다.

GPU 스크립트는 고정 revision 다운로드 → 기존 merge.py로 bf16 병합 →
main check_env/gate → 900문항 preflight → main run_generate.sh →
900 ID·30×30·오류 검증 → 시간·토큰·VRAM 요약을 E1, E2 순서로 수행한다.
평가 코드와 config.yaml은 그대로 사용하며 모델 경로만 바꾼다.
새 결과 경로만 허용하고 오류 시 즉시 중단한다. GPU 설치·병합·추론은 문법/연결 검토만 완료했다.

## 다음 단계 판단

1단계의 M0·k0 재현과 집계 점검은 모두 통과했다.
2단계 GPU 생성은 사용자가 파드를 준비하고 실행을 지시하면 진행할 수 있다.
k0는 아직 미확정이며 최종 집계·판정 전에 합의해야 한다.
GPU 실제 환경 호환성·병합·900문항 생성 성공과 E1/E2 자원 사용량은 2단계에서 확인해야 한다.

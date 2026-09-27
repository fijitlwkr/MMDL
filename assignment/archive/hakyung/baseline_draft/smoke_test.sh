#!/usr/bin/env bash
# Step 2 전체를 한 번에 실행 (비용 절감을 위해 한 번의 호출로 끝까지)
set -euo pipefail
cd "$(dirname "$0")"

source ./env.sh

STEP2_T0=$(date +%s)
step_banner () {
  local now elapsed
  now=$(date '+%H:%M:%S')
  elapsed=$(( $(date +%s) - STEP2_T0 ))
  echo "############################################################"
  echo "$1   [현재시각 ${now} | 시작後 ${elapsed}s 경과]"
  echo "############################################################"
}

step_banner "[1/5] 환경 설치 + 검증"
bash setup_env.sh

echo
step_banner "[2/5] Group A(smoke test) 데이터셋 구성: MC 1문항 x 30과목"
python3 build_dataset.py \
  --limit-per-subject 1 \
  --mc-only \
  --out data/mmmu_light.jsonl \
  --img-dir data/images_light

echo
step_banner "[3/5] vLLM 추론 (라이트 테스트, revision/seed/샘플링 파라미터 고정값 적용, 자체 progress bar 표시됨)"
python3 run_inference.py \
  --data data/mmmu_light.jsonl \
  --out data/predictions_light.jsonl \
  --max-model-len 9048 \
  --max-new-tokens 2048

echo
step_banner "[4/5] finish_reason 집계 (max_new_tokens=2048 충분성 확인)"
python3 - <<'PY'
import json
from collections import Counter
rows = [json.loads(l) for l in open("data/predictions_light.jsonl")]
c = Counter(r["finish_reason"] for r in rows)
print("finish_reason 분포:", dict(c))
if c.get("length", 0) > 0:
    print(f"주의: {c['length']}건이 max_new_tokens=2048 한도에 걸려 절단됨. 상향 검토 필요.")
else:
    print("전부 자연 종료(stop). 2048 유지 가능.")
PY

echo
step_banner "[5/5] 파서 비교 실험 (VLMEvalKit vs MMMU 공식)"
python3 mc_parsers.py --preds data/predictions_light.jsonl --out data/parser_compare_light.json

echo
TOTAL_ELAPSED=$(( $(date +%s) - STEP2_T0 ))
echo "============================================================"
echo "Group A(smoke test) 완료. 총 소요 시간: ${TOTAL_ELAPSED}초 (약 $((TOTAL_ELAPSED/60))분)"
echo "결과물:"
echo "  data/mmmu_light.jsonl          - Group A 입력 (MC 30문항)"
echo "  data/predictions_light.jsonl   - 모델 원문/최종 응답 + finish_reason"
echo "  data/parser_compare_light.json - 파서 비교(실패율 + GT 정확도 + 불일치) 상세 결과"
echo "============================================================"
echo
echo "표 항목 전부 정상이면 Group B(stress test)로 진행:"
echo "  python3 build_stress_dataset.py --top-n 2 --out data/mmmu_stress.jsonl --img-dir data/images_stress"
echo "  python3 run_inference.py --data data/mmmu_stress.jsonl --out data/predictions_stress.jsonl"
echo "  (다중 이미지/최장 입력/open-ended 문항에서 truncation·에러 여부 확인용, 900문항 전체 스캔이라 A보다 시간이 더 걸림)"

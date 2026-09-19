"""Import the returned H1 labels and compare frozen parsers; no API or inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
import parsers


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--labels', type=Path, required=True)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    source_path = args.source
    source_bytes = source_path.read_bytes()
    require(sha(source_bytes) == '77a97690dcda256bc322dd8d3309fe33f5e9d4fad9f69416ff5f9b1cb630942f', 'Source export changed')
    source = json.loads(source_bytes)
    label_bytes = args.labels.read_bytes()
    returned = json.loads(label_bytes.decode('utf-8-sig'))
    rows = {r['id']: r for r in source['items']}
    labels = returned['labels']
    require(returned['task'] == 'H1_Qwen_MMMU_disagreements' and returned['source_kind'] == 'legacy-pilot', 'Wrong cohort')
    require(returned['total'] == len(labels) == len(rows) == 49, 'Expected 49 cases')
    require(len({l['id'] for l in labels}) == 49 and {l['id'] for l in labels} == set(rows), 'Missing, duplicate or extra IDs')
    comparisons = []
    joined = []
    for index, label in enumerate(labels, 1):
        row = rows[label['id']]
        require(label['number'] == index and label['id'] == source['items'][index-1]['id'], f'Queue order mismatch: {index}')
        for key in ('analysis_id', 'raw_sha256'):
            require(label[key] == row[key], f'{key} mismatch: {label["id"]}')
        require(sha(row['raw_text'].encode()) == row['raw_sha256'], f'Raw hash mismatch: {label["id"]}')
        require(label['review_mode'] in ('human_confirmed', 'ai_only', 'pending'), 'Unknown review provenance')
        require(label['answer_status'] in ('unique', 'ambiguous', 'no_answer'), 'Incomplete answer status')
        require(bool(label['evidence_quote']) and label['evidence_quote'] in row['raw_text'], f'Evidence not verbatim: {label["id"]}')
        require((label['human_answer'] in row['options']) if label['answer_status'] == 'unique' else not label['human_answer'], 'Invalid answer')
        require(isinstance(label['adjudicated'], bool) and bool(label['reviewed_by']), 'Missing reviewer metadata')
        q = parsers.qwen_parse(row['raw_text'], row['options'])
        m, blocked = parsers.mmmu_mc_parse(row['raw_text'], row['options'])
        marker = parsers.marker(row['raw_text'], row['options'])
        require(q is not None and m is not None and q != m and not blocked, 'Not a joint-success disagreement')
        conflict = bool(q and marker['answer'] and q != marker['answer'])
        hybrid = None if conflict else (q or marker['answer'])
        comparisons.append({**label, 'qwen': q, 'mmmu_no_random': m, 'marker': marker,
                            'hybrid100': hybrid, 'hybrid_route': 'judge_conflict' if conflict else 'auto',
                            'qwen_matches_review': label['answer_status'] == 'unique' and q == label['human_answer'],
                            'mmmu_matches_review': label['answer_status'] == 'unique' and m == label['human_answer'],
                            'hybrid_matches_review': label['answer_status'] == 'unique' and hybrid == label['human_answer']})
        joined.append({**row, **label, 'label_source': 'user_returned_review_file'})
    old_labels = {l['id']: l for l in source['completed_human_labels']}
    for label in labels:
        if label['id'] in old_labels:
            for key in ('answer_status', 'human_answer', 'evidence_quote'):
                require(label[key] == old_labels[label['id']][key], 'Previously confirmed label changed')
    provenance = Counter(l['review_mode'] for l in labels)
    require(returned['completed_human_confirmed'] == provenance['human_confirmed'], 'Human count mismatch')
    # This report is for this complete, single-reviewer return. Never promote AI labels to human gold.
    require(provenance == {'human_confirmed': 49} and all(not l['adjudicated'] for l in labels), 'Use a separate report for other review modes')
    require({l['reviewed_by'] for l in labels} == {'yoonseok'}, 'Unexpected reviewer set')
    totals = {key: sum(c[key] for c in comparisons) for key in ('qwen_matches_review', 'mmmu_matches_review', 'hybrid_matches_review')}
    totals['hybrid_auto'] = sum(c['hybrid_route'] == 'auto' for c in comparisons)
    totals['hybrid_judge'] = 49 - totals['hybrid_auto']
    totals['hybrid_auto_mismatch'] = totals['hybrid_auto'] - totals['hybrid_matches_review']
    summary = {
        'task': returned['task'], 'source_kind': returned['source_kind'],
        'analysis_id': source['items'][0]['analysis_id'], 'cases': 49,
        'validation': {'complete_unique_id_set': True, 'all_raw_hashes_match': True,
                       'all_quotes_verbatim': True, 'all_answers_valid_options': True,
                       'all_recomputed_parsers_disagree': True, 'initial_two_labels_unchanged': True},
        'review_provenance': '49 labels supplied as human_confirmed by yoonseok; single reviewer, no independent adjudication',
        'human_confirmed_as_reported': 49, 'adjudicated': 0,
        'counts': totals, 'api_calls': 0, 'generation_runs': 0,
        'scope': 'Answer extraction on the 49 legacy-pilot H1 disagreements only; not GT accuracy, H2 validation or final HF evaluation',
        'source_export_sha256': sha(source_bytes), 'returned_labels_sha256': sha(label_bytes),
        'code_sha256': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
                        [Path(__file__).resolve(), ROOT / 'parsers.py',
                         *sorted((ROOT / 'vendor').glob('*.py'))]},
    }
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'returned_review_original.json').write_bytes(label_bytes)
    write_json(args.out / 'summary.json', summary)
    for name, items in [('human_labels_full.jsonl', joined), ('parser_comparison.jsonl', comparisons)]:
        (args.out / name).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in items), encoding='utf-8')
    table = '\n'.join(f"| {c['number']} | `{c['id']}` | {c['human_answer']} | {c['qwen']} | {c['mmmu_no_random']} | {c['hybrid100'] or 'Judge'} |" for c in comparisons)
    report = f'''# H1 반환 라벨 검증 및 파서 비교 — 2026-09-19

## 결과

사용자가 반환한 **49건의 사람 확인 라벨**을 원본과 대조하고 고정된 파서를 다시 실행했다. ID·분석 ID·원문 SHA-256·근거 문장·유효 선택지 모두 통과했다. 최초 2개 라벨도 그대로다. 라벨은 파일에 `human_confirmed`, 검토자 `yoonseok`으로 기록된 내용을 보존했다. **단일 검토자 결과이며 두 사람의 독립 검토·조정 결과는 아니다**(`adjudicated=false` 49건).

| 방식 | 검토 답과 일치 | 자동 추출 불일치 | Judge로 이동 |
|---|---:|---:|---:|
| Qwen 규칙 | {totals['qwen_matches_review']}/49 ({totals['qwen_matches_review']/49:.2%}) | {49-totals['qwen_matches_review']} | 0 |
| MMMU 규칙 + 랜덤 폴백 제거 | {totals['mmmu_matches_review']}/49 ({totals['mmmu_matches_review']/49:.2%}) | {49-totals['mmmu_matches_review']} | 0 |
| 기존 hybrid100 | {totals['hybrid_matches_review']}/49 | {totals['hybrid_auto_mismatch']} | {totals['hybrid_judge']} |

모두 **두 파서가 서로 다른 답을 낸 49문항 안에서의 추출 비교**다. 문제의 GT 정답률이나 전체 MMMU 정확도가 아니다. Hybrid의 Judge 대상은 실제 호출하지 않았으며 성공으로 세지 않았다. 이번 처리의 신규 API 비용과 재추론은 0이다.

## 남은 두 사례

- `validation_Physics_8`: 검토 답 A, Qwen C, MMMU A. 기존 hybrid는 Final Answer의 A와 충돌해 Judge로 넘긴다.
- `validation_Chemistry_18`: 검토 답 D, Qwen C, MMMU D. 기존 hybrid도 C를 자동 채택한다. 원문은 `Correct Answer: D`인데 기존 Final Answer 규칙이 이 형식을 잡지 못한다. 이 사례는 현재 방식의 오독이 남아 있음을 보여준다.

## 해석과 다음 단계

이 불일치군에서는 **Qwen을 기본으로 두는 쪽을 지지**한다. MMMU의 낮은 파싱 실패율만으로 교체를 결정할 수 없다. 다만 Qwen만 성공한 군·MMMU만 성공한 군과 두 파서가 일치한 군의 추출 정확도는 이번에 검증하지 않았다.

기존 pilot에서 공동 추출 성공군 일치율은 267/316=84.49%였다. “대부분”의 임계값이 사전에 확정되지 않았으므로 이를 사전 등록된 95% 기준의 공식 기각 결과로 쓰지 않는다. 49건의 검토 결과는 앞선 AI 결론부 예비 검토 47:2와 같지만, 근거 파일과 검토 출처를 별도 보존한다.

**H2 Final Answer 자동 채택 표본 100건은 별도 검토가 남아 있다.** 이 H1 결과를 H2의 99% 추출 충실도나 최종 baseline 확정 근거로 대신하지 않는다. H1과 H2의 중복 10건은 선정 파일의 ID·해시를 대조한 뒤 재사용할 수 있다. 오류를 본 뒤 규칙을 수정한다면 새 후보로 분리하고 별도 표본 또는 최종 HF raw에서 검증한다.

자료는 당시 seed 42/cap 9048의 legacy-pilot이다. 팀 최종 HF/seed 3407 평가로 일반화하지 않는다. 기존 파서·Judge·캐시는 변경하지 않았고, 반환 파일은 로컬에 보존했다. Pod에는 아직 동기화하지 않았다.

## 산출물

- `returned_review_original.json`: 반환 파일 원본 바이트 보존.
- `human_labels_full.jsonl`: 원문·선택지와 반환 라벨을 결합한 49건. 사람 판정을 변경하지 않음.
- `parser_comparison.jsonl`: 동일 원문을 고정 파서로 재실행한 문항별 결과.
- `summary.json`: 검증 결과·집계·입력과 코드 해시.

## 49문항 대조표

| 번호 | ID | 검토 답 | Qwen | MMMU(no random) | 기존 hybrid100 |
|---|---|---|---|---|---|
{table}
'''
    (args.out / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps({'validated': 49, **totals, 'output': str(args.out.resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    main()

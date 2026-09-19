"""Validate a complete single-reviewer H2 return and score extraction fidelity offline."""
import argparse
import base64
from collections import Counter
import gzip
import hashlib
import json
from math import sqrt
from pathlib import Path
import random
from statistics import NormalDist
import sys

ROOT = Path(__file__).resolve().parent
import parsers


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def metric(rows):
    n = len(rows)
    k = sum(r['matches_review'] for r in rows)
    require(n > 0, 'Empty review group')
    p = k / n
    z = NormalDist().inv_cdf(0.975)
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    radius = z*sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return dict(n=n, matches=k, mismatches=n-k, observed_fidelity=p,
                wilson_95=[max(0, center-radius), min(1, center+radius)])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', required=True, type=Path)
    ap.add_argument('--template', required=True, type=Path)
    ap.add_argument('--h1-summary', required=True, type=Path)
    ap.add_argument('--labels', required=True, type=Path)
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    source_bytes = args.source.read_bytes()
    require(sha(source_bytes) == manifest['source_export_sha256'] ==
            '756a79e5a1e8fc8acdc4fbf36d4d2de3f5d660aa2fd08d8d9290e2ea19cf404d', 'Source export changed')
    source = json.loads(source_bytes)
    selection = source['selection']
    items = source['items']
    require([r['id'] for r in items] == selection['h2_sample_ids_private'], 'Sample order changed')
    require(random.Random(3407).sample(sorted(selection['h2_population_ids_private']), 100)
            == selection['h2_sample_ids_private'], 'Sample does not reproduce')
    template_path = args.template
    require(sha(template_path.read_bytes()) == manifest['files']['H2_결과반환양식.json'], 'Original template changed')
    template = json.loads(template_path.read_text(encoding='utf-8'))
    previous_code = json.loads(args.h1_summary.read_text(encoding='utf-8'))['code_sha256']
    for filename, expected in previous_code.items():
        if 'parsers.py' in filename or 'vendor' in filename:
            relative = Path(filename.replace('\\', '/'))
            parser_file = ROOT / ('vendor' if 'vendor' in relative.parts else '') / relative.name
            require(sha(parser_file.read_bytes()) == expected, f'Parser source changed: {filename}')
    returned_bytes = args.labels.read_bytes()
    returned = json.loads(returned_bytes.decode('utf-8-sig'))
    for key in ('task', 'source_kind', 'total', 'population_total', 'sample_seed', 'reused_h1'):
        require(returned[key] == template[key], f'Metadata mismatch: {key}')
    labels = returned['labels']
    require(len(labels) == len({r['id'] for r in labels}) == 100, 'Expected 100 unique labels')
    require({r['id'] for r in labels} == {r['id'] for r in items}, 'Missing or extra IDs')
    by_id = {r['id']: r for r in labels}
    comparisons, joined = [], []
    for row, old in zip(items, template['labels']):
        require(row['id'] == old['id'], 'Template order mismatch')
        label = by_id[row['id']]
        for key in ('id', 'analysis_id', 'raw_sha256', 'number', 'sample_number', 'review_number'):
            require(label[key] == old[key], f'{key} mismatch: {row["id"]}')
        require(row['analysis_id'] == manifest['analysis_id'], 'Analysis ID changed')
        require(sha(row['raw_text'].encode()) == row['raw_sha256'], 'Raw hash mismatch')
        require(label['review_mode'] == 'human_confirmed' and label['reviewed_by'] == 'yoonseok'
                and label['adjudicated'] is False, 'This importer expects the complete single-reviewer return')
        require(label['answer_status'] in ('unique', 'ambiguous', 'no_answer'), 'Invalid answer status')
        require(label['human_answer'] in row['options'] if label['answer_status'] == 'unique'
                else not label['human_answer'], 'Invalid answer')
        require(label['evidence_quote'] and label['evidence_quote'] in row['raw_text'], 'Evidence not verbatim')
        reused = old['review_mode'] == 'human_confirmed'
        if reused:
            for key in ('answer_status', 'human_answer', 'evidence_quote', 'review_mode', 'reviewed_by',
                        'adjudicated', 'notes', 'label_source', 'source_h1_number'):
                require(label.get(key) == old.get(key), f'Reused H1 label changed: {row["id"]}, {key}')
        q = parsers.qwen_parse(row['raw_text'], row['options'])
        marker = parsers.marker(row['raw_text'], row['options'])
        require(marker['answer'] is not None and (q is None or q == marker['answer']), 'No longer marker-auto')
        hybrid = q or marker['answer']
        result = {**label, 'qwen': q, 'marker': marker, 'hybrid100': hybrid,
                  'group': 'qwen_rescued' if q is None else 'qwen_already_success',
                  'reused_from_h1': reused,
                  'matches_review': label['answer_status'] == 'unique' and hybrid == label['human_answer']}
        comparisons.append(result)
        joined.append({**row, **label, 'import_provenance': 'user_returned_h2_review_file'})
    require(returned['completed_human_confirmed'] == 100 and returned['remaining'] == 0, 'Completion count mismatch')
    require(sum(r['reused_from_h1'] for r in comparisons) == 10, 'Overlap changed')
    groups = {key: metric([r for r in comparisons if r['group'] == key])
              for key in ('qwen_rescued', 'qwen_already_success')}
    require(groups['qwen_rescued']['n'] == 59 and groups['qwen_already_success']['n'] == 41, 'Subgroups changed')
    overall = metric(comparisons)
    summary = {
        'task': returned['task'], 'source_kind': returned['source_kind'], 'analysis_id': manifest['analysis_id'],
        'population_marker_auto': 305, 'sample_n': 100, 'sample_seed': 3407, 'generation_seed': 42,
        'human_confirmed_as_reported': 100, 'new_h2_labels': 90, 'reused_h1_labels': 10, 'adjudicated': 0,
        'review_provenance': 'User returned all labels as human_confirmed by yoonseok; single reviewer, not independent two-rater gold',
        'overall': overall, 'groups': groups, 'answer_status_counts': dict(Counter(r['answer_status'] for r in labels)),
        'confidence_interval_method': 'Two-sided 95% binomial Wilson, z=NormalDist.inv_cdf(0.975), no finite-population correction; does not include rater error',
        'validation': '100 unique fixed sample IDs; all raw hashes, verbatim evidence, option labels and metadata pass; 10 H1 labels unchanged; marker-auto eligibility and subgroup counts reproduced; parser sources unchanged',
        'scope': 'Extraction fidelity in stop multiple-choice marker-auto sample; not GT correctness or all hybrid routes',
        'api_calls': 0, 'generation_runs': 0, 'source_export_sha256': sha(source_bytes),
        'returned_labels_sha256': sha(returned_bytes), 'original_template_sha256': sha(template_path.read_bytes()),
        'code_sha256': {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in
                       [Path(__file__).resolve(), ROOT / 'parsers.py',
                        *sorted((ROOT / 'vendor').glob('*.py'))]},
    }
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'returned_review_original.json').write_bytes(returned_bytes)
    write_json(args.out / 'summary.json', summary)
    for name, rows in [('human_labels_full.jsonl', joined), ('parser_comparison.jsonl', comparisons)]:
        (args.out / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    def table_row(name, m):
        lo, hi = m['wilson_95']
        return f"| {name} | {m['matches']}/{m['n']} | {m['observed_fidelity']:.2%} | {lo:.2%}–{hi:.2%} |"
    table = '\n'.join([table_row('H2 전체 표본', overall), table_row('Qwen 실패 → marker 추가 채택', groups['qwen_rescued']),
                       table_row('기존 Qwen도 성공', groups['qwen_already_success'])])
    cases = '\n'.join(f"| {r['sample_number']} | `{r['id']}` | {r['human_answer'] or r['answer_status']} | {r['qwen'] or '추출 실패'} | {r['hybrid100']} | {'일치' if r['matches_review'] else '불일치'} |" for r in comparisons)
    report = f'''# H2 Final Answer 자동 채택 — 반환 라벨 분석

## 결과

고정된 H2 표본 100건의 사용자 반환 라벨을 검증하고 동일 파서를 재실행했다. **검토 답과 {overall['matches']}/100개 일치**, 추출 불일치 {overall['mismatches']}개다. 특히 기존 Qwen이 추출하지 못한 추가 채택군은 {groups['qwen_rescued']['matches']}/59개가 일치했다.

| 집단 | 검토 답과 일치 | 관측 추출 충실도 | Wilson 95% 구간 |
|---|---:|---:|---:|
{table}

이는 **원문에서 모델이 최종적으로 낸 답을 제대로 읽었는지**의 결과다. 실제 문제의 정답률, MMMU 점수 또는 Judge의 정확도가 아니다. 기존 10개 H1 라벨과 이번 90개 H2 라벨을 합친 고정 표본 100건이며, H1 49개 전체를 이 분모에 더하지 않았다.

## 검증과 출처

- 고유 ID 100개·분석 ID·번호·원문 SHA-256·유효 답·근거 문장의 원문 일치가 모두 확인됐다. 재사용한 H1 10개 판정은 그대로다.
- 기존 모집단 305개에서 seed 3407로 선정한 표본 목록을 재현했다. 표본을 바꾸거나 답을 고쳐 쓰지 않았다.
- 동일 파서를 다시 실행해 100개가 marker 자동 채택 조건을 만족하며 Qwen 추가 구제 59개/기존 성공 41개임을 확인했다. H1 당시 파서 소스 해시와 같다.
- 반환 파일은 전부 `human_confirmed`, 검토자 `yoonseok`, `adjudicated=false`다. 사용자 신고 검토 출처를 보존했으며 **단일 검토자 결과**다. 독립 2인 검증·조정 완료로 표현하지 않는다.
- 원본 반환 파일의 바이트를 별도 보존했다. 기존 파서·Judge·캐시는 변경하지 않았다. 신규 API 호출과 재추론은 0이다. Pod에는 이번 반환 자료를 동기화하지 않았다.

## 무엇을 판단할 수 있나

이 표본은 **Qwen 규칙 + 기존 Final Answer 100자 보완 규칙을 후보로 유지할 근거를 강화한다.** 기존 Qwen이 읽지 못한 59건의 추가 추출도 사용자 판정과 일치했다. H1의 Qwen 47/49, MMMU 2/49 결과와 함께 보면 파싱 실패율만 보고 MMMU로 교체하는 것보다 Qwen을 기본으로 보완하는 방향이 타당하다.

제안했던 99% 점 추정 목표와 관측치를 비교할 수는 있지만, 기준이 사전 확정되지 않았으므로 사전 등록된 가설 검증 완료라고 쓰지 않는다. 모집단이나 미래 응답의 추출 충실도가 99% 이상이라고 보장하지 않는다. 95% 구간은 계획한 일반 Wilson 방법이며 비복원 표본의 유한모집단 보정을 적용하지 않았다. 라벨러 오판·모델/환경 변화는 이 구간에 반영되지 않는다.

기존 899건 pilot에서 Judge 대상은 Qwen 503건 → hybrid100 327건으로 176건(34.99%) 줄었다. 이는 앞선 라우팅 집계이며 이번 100건에서 새로 측정한 비용 절감이나 전량 채점 완료 수치가 아니다.

## 남아 있는 한계와 후속

- H2는 **정상 종료 객관식 중 유효 marker와 자동 채택이 함께 있는 군**만 검토한다. marker가 없는 Qwen 자동 채택, open 응답, length 응답, Judge 출력 전체의 검증이 아니다.
- H1 `validation_Chemistry_18`에서는 여전히 hybrid가 D 대신 C를 잘못 자동 채택한다. `Correct Answer:` 형식이 기존 marker에 잡히지 않은 사례로, H2 모집단에 포함되지 않는다.
- 합성 반례 `Final Answer: A or B.`의 오독 가능성도 남아 있다. 표본에서 오류가 없었다고 이 반례가 해결된 것은 아니다. 규칙을 바꾼다면 새 버전 후보로 분리하고 별도 자료로 검증한다.
- `length`는 항상 Judge로 보내고 random fallback은 금지하는 기존 방침을 유지한다. 다음 분석은 H3의 length 진단이며 Judge 정확성 육안 검증은 사용자 범위 밖이다.
- 이 자료는 seed 42/cap 9048의 legacy-pilot이다. 최종 HF pinned revision/seed 3407 프로토콜의 검증을 대신하지 않는다.

## 산출물

`returned_review_original.json`(반환 원본), `human_labels_full.jsonl`(원문과 라벨), `parser_comparison.jsonl`(문항별 비교), `summary.json`(집계·검증·해시).

## 문항별 비교

| 표본 번호 | ID | 사용자 검토 답 | Qwen | hybrid100 | 비교 |
|---|---|---|---|---|---|
{cases}
'''
    (args.out / 'REPORT.md').write_text(report, encoding='utf-8')
    print(json.dumps({'validated': 100, 'overall': overall, 'groups': groups, 'output': str(args.out.resolve())}, ensure_ascii=False))


if __name__ == '__main__':
    main()

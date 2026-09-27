"""Compare two rule-only MC pipelines; open answers become A/gold vs B/Other Answers."""
import argparse
import json
from pathlib import Path
from common import ROOT, SUBJECTS, read_rows, full_validation, input_metadata, aggregate, write_json, write_text, check_output
from mc_parsers import MMMUParser, parse_vlmevalkit, score_mc

def compare(rows, seed=42):
    parser = MMMUParser(seed)
    results = {'mmmu': [], 'vlmevalkit': []}
    disagreements = []
    for row in rows:
        choices, gold = row['options'], row['answer']
        if row['question_type'] == 'open':
            # Mirrors the historical Qwen/VLMEvalKit conversion. This intentionally
            # differs from the official open evaluator (including accepted aliases).
            text = gold if isinstance(gold, str) else str(gold)
            choices, gold = {'A': text, 'B': 'Other Answers'}, 'A'
        if row.get('data_issue'):
            parsed = {name: {'parsed': None, 'parse_success': False, 'random_fallback': False, 'data_issue': row['data_issue']}
                      for name in results}
        else:
            parsed = {'mmmu': parser.parse(row['prediction'], choices),
                      'vlmevalkit': parse_vlmevalkit(row['prediction'], choices)}
        for name, result in parsed.items():
            results[name].append({'uid': row['uid'], 'subject': row['subject'], 'question_type': row['question_type'],
                                  'scoring_answer': gold, **result, 'correct': False if row.get('data_issue') else score_mc(gold, result['parsed'])})
        if parsed['mmmu']['parsed'] != parsed['vlmevalkit']['parsed']:
            disagreements.append({'uid': row['uid'], 'subject': row['subject'],
                                  'mmmu': parsed['mmmu']['parsed'], 'vlmevalkit': parsed['vlmevalkit']['parsed']})
    return {'pipelines': {name: {**aggregate(items), 'parsing_failure_uids': [r['uid'] for r in items if not r['parse_success']],
                                 'random_fallback_uids': [r['uid'] for r in items if r['random_fallback']], 'details': items}
                          for name, items in results.items()}, 'disagreements': disagreements}

def table(result):
    score = result['pipelines']['mmmu']
    lines = ['# MMMU MC 파서 비교 결과', '',
             '> 저장된 예측을 재채점한 분석용 결과입니다. Open 문항을 A=정답, B=Other Answers로 변환했습니다.',
             '> 최종 MC+open 점수는 eval_val.json을 확인하세요.', '',
             f"- 입력 SHA-256: `{result['input']['sha256']}`",
             f"- 전체 validation 구성: `{result['input']['full_validation']}`",
             f"- 데이터 오류 문항: {len(result['input']['data_issue_uids'])}개 (오답 처리, 예비 결과)",
             '- 점수 단위: 아래 표는 %, JSON의 accuracy는 0~1', '',
             '| Subject | Data Num | Acc (%) |', '|---|---:|---:|']
    for subject in SUBJECTS:
        item = score['subjects'].get(subject)
        if item:
            lines.append(f"| {subject} | {item['num_examples']} | {100*item['accuracy']:.2f} |")
        else:
            lines.append(f'| {subject} | 0 | 미평가 |')
    lines.extend([f"| **Overall (macro)** | **{score['num_examples']}** | **{100*score['macro_accuracy']:.2f}** |", '',
                  f"MMMU fallback {len(score['random_fallback_uids'])}문항; 두 parser의 선택 불일치 {len(result['disagreements'])}문항.", '',
                  'MMMU는 추출 실패 시 seeded random fallback을 포함합니다. VLMEvalKit은 규칙만 사용하며 실패는 오답 처리합니다.',
                  '이 점수는 GPT judge를 사용했던 기존 62.22%와 채점 조건이 다릅니다.', ''])
    return '\n'.join(lines)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', default=str(ROOT/'data/predictions_val.jsonl'))
    p.add_argument('--output', default=str(ROOT/'data/baseline_score.json'))
    p.add_argument('--table', default=str(ROOT/'data/baseline_table.md'))
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--allow-partial', action='store_true')
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    if Path(args.output).resolve() == Path(args.table).resolve():
        p.error('JSON and Markdown output paths must differ')
    check_output(args.output, args.force); check_output(args.table, args.force)
    rows = read_rows(args.input, predictions=True)
    if not args.allow_partial and not full_validation(rows):
        p.error('Expected 30 subjects x 30 validation items; use --allow-partial for smoke/stress only')
    result = {'schema_version': 1, 'status': 'completed', 'seed': args.seed, 'input': input_metadata(args.input, rows),
              'parser_sources': json.loads((ROOT/'vendor/sources.json').read_text()),
              'policy': {'open': 'A=gold answer string, B=Other Answers; scoring only, never used for inference',
                         'mmmu_no_match': 'seeded random choice', 'vlmevalkit_no_match': 'incorrect, no judge/fallback',
                         'vlmevalkit_VERBOSE': 'unset', 'primary_table': 'mmmu', 'invalid_imported_options': 'count incorrect and flag; provisional score'}, **compare(rows, args.seed)}
    write_json(args.output, result, args.force)
    write_text(args.table, table(result), args.force)
    for name, score in result['pipelines'].items():
        print(f"{name}: macro={score['macro_accuracy']:.4%}, micro={score['micro_accuracy']:.4%}")

if __name__ == '__main__':
    main()

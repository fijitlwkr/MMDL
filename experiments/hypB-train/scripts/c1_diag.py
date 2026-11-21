"""C1 teacher-signal diagnostic. Forward passes only: no training, no generation, no file changes besides --output.

Why: the smoke criterion "teacher mean logp > M0 mean logp on correct responses" failed without saving numbers.
M0's own samples are high-probability under M0 by construction, so that criterion may be wrong rather than the code.
This script saves every number first and then evaluates three criteria fixed before running:
  A. anchor rollouts (the response shown to the teacher): teacher mean logp > student mean logp in >= 90% of them.
  B. final-answer region (last 32 content tokens of fully kept stop responses): mean(teacher - student logp) is
     higher for correct non-anchor rollouts than for wrong rollouts.
  C. mean JS of wrong rollouts > mean JS of correct non-anchor rollouts.
"""
import argparse
import json
import os
from pathlib import Path

from c1_prepare import ROOT, WORKSPACE, read_rows, write_json
from c1_inputs import append_response, prefixes, response_ids

TAIL = 32
ITEMS = 40


def token_logp(logits, targets, chunk=128):
    import torch
    parts = []
    for start in range(0, targets.shape[1], chunk):
        part = logits[:, start:start + chunk].float()
        ids = targets[:, start:start + chunk]
        parts.append((part.gather(-1, ids.unsqueeze(-1)).squeeze(-1) - part.logsumexp(-1)).double().cpu())
    return torch.cat(parts, dim=1)[0]


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--model-path', type=Path, required=True)
    ap.add_argument('--image-root', type=Path, default=WORKSPACE)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if not args.run:
        ap.error('GPU forward passes require explicit --run')
    assert not args.output.exists()
    from c1_train import CONFIG, js_loss, load_model, verify_data
    cfg = json.loads(CONFIG.read_bytes())
    assert os.environ.get('PYTORCH_CUDA_ALLOC_CONF') == cfg['cuda_alloc_conf']
    verify_data(ROOT / 'data/c1_train.jsonl', ROOT / 'data/c1_anchors.jsonl', CONFIG, args.image_root)
    entries = read_rows(ROOT / 'data/c1_train.jsonl')
    anchors = {r['row']: r for r in read_rows(ROOT / 'data/c1_anchors.jsonl')}
    by_row = {}
    for entry in entries:
        by_row.setdefault(entry['row'], []).append(entry)
    assert all(len(v) == 4 for v in by_row.values())
    # First ITEMS items in file order whose four M0 responses are mixed (1-3 correct).
    rows = [row for row, group in by_row.items() if 0 < sum(r['reward'] for r in group) < 4][:ITEMS]
    assert len(rows) == ITEMS
    import torch
    model, processor = load_model(args.model_path, cfg)
    model.eval()
    records = []
    with torch.no_grad():
        for row in rows:
            for entry in sorted(by_row[row], key=lambda r: r['repeat']):
                anchor = anchors[row]
                student, teacher, _ = prefixes(entry, anchor, processor, cfg, args.image_root)
                assert student['input_ids'].shape[1] == entry['prompt_tokens']
                ids, info = response_ids(entry, processor.tokenizer, cfg)
                sb, sp, targets = append_response(student, ids, model.device)
                tb, tp, _ = append_response(teacher, ids, model.device)
                with model.disable_adapter():
                    t_logits = model(**tb, logits_to_keep=tp, use_cache=False).logits
                s_logits = model(**sb, logits_to_keep=sp, use_cache=False).logits
                js = js_loss(s_logits, t_logits, cfg['js_chunk_tokens'], False).item()
                s_lp, t_lp = token_logp(s_logits, targets), token_logp(t_logits, targets)
                content = info['kept_content_tokens']
                full_stop = info['eos_added']
                tail = slice(max(0, content - TAIL), content)
                record = {'row': row, 'repeat': entry['repeat'], 'reward': entry['reward'],
                          'finish_reason': entry['finish_reason'], 'is_anchor': entry['repeat'] == anchor['anchor_repeat'],
                          'full_stop': full_stop, 'response_tokens': len(ids), 'js': js,
                          'student_mean_logp': s_lp.mean().item(), 'teacher_mean_logp': t_lp.mean().item(),
                          'student_tail_logp': s_lp[tail].mean().item(), 'teacher_tail_logp': t_lp[tail].mean().item(),
                          'student_head_logp': s_lp[:max(1, content - TAIL)].mean().item(),
                          'teacher_head_logp': t_lp[:max(1, content - TAIL)].mean().item()}
                records.append(record)
                print(json.dumps(record), flush=True)
                del s_logits, t_logits
    args.output.mkdir(parents=True)
    write_json(args.output / 'c1_diag_records.json', records)  # saved before any criterion is evaluated
    gain = lambda r, k: r[f'teacher_{k}_logp'] - r[f'student_{k}_logp']
    groups = {'anchor': [r for r in records if r['is_anchor']],
              'correct_non_anchor': [r for r in records if r['reward'] == 1 and not r['is_anchor']],
              'wrong': [r for r in records if r['reward'] == 0]}
    table = {name: {'n': len(g), 'js': mean(r['js'] for r in g), 'mean_logp_gain': mean(gain(r, 'mean') for r in g),
                    'head_logp_gain': mean(gain(r, 'head') for r in g),
                    'n_full_stop': sum(r['full_stop'] for r in g),
                    'tail_logp_gain_full_stop': mean(gain(r, 'tail') for r in g if r['full_stop']),
                    'share_mean_gain_positive': mean(gain(r, 'mean') > 0 for r in g)}
             for name, g in groups.items()}
    a = table['anchor']['share_mean_gain_positive']
    b_c, b_w = table['correct_non_anchor']['tail_logp_gain_full_stop'], table['wrong']['tail_logp_gain_full_stop']
    c_c, c_w = table['correct_non_anchor']['js'], table['wrong']['js']
    criteria = {'A_anchor_copy': a is not None and a >= 0.9,
                'B_tail_gain_correct_gt_wrong': None not in (b_c, b_w) and b_c > b_w,
                'C_js_wrong_gt_correct': None not in (c_c, c_w) and c_w > c_c}
    summary = {'items': ITEMS, 'rollouts': len(records), 'tail_tokens': TAIL, 'groups': table, 'criteria': criteria,
               'status': 'PASS' if all(criteria.values()) else 'FAIL', 'training_steps': 0, 'generation_requests': 0}
    write_json(args.output / 'c1_diag_summary.json', summary)
    print(json.dumps(summary, indent=1), flush=True)


if __name__ == '__main__':
    main()

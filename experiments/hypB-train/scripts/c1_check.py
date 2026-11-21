"""CPU-only C1 contracts, complete sequence lengths, JS tests, and meta LoRA checks."""
import os
os.environ.update(CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import time

from c1_prepare import ROOT, WORKSPACE, inputs, read_rows, serialize, sha, write_json
from c1_inputs import PROCESSOR, append_response, load_processor, prefixes, response_ids
from c1_train import CONFIG, add_lora, check_lora, js_loss, mean_response_logp


def loss_tests():
    import torch
    torch.manual_seed(3407)
    p = torch.randn(1, 37, 19, requires_grad=True)
    q = torch.randn_like(p, requires_grad=True)
    identical = js_loss(p, p.detach(), 7)
    assert abs(identical.item()) < 1e-6
    whole = js_loss(p, q, 37, False)
    chunked = js_loss(p, q, 7, True)
    assert torch.allclose(whole, chunked, atol=1e-6, rtol=1e-6)
    assert torch.allclose(whole, js_loss(q, p, 11, False), atol=1e-6, rtol=1e-6)
    grad_whole, = torch.autograd.grad(whole, p, retain_graph=True)
    grad_chunk, = torch.autograd.grad(chunked, p, retain_graph=True)
    assert torch.allclose(grad_whole, grad_chunk, atol=1e-6, rtol=1e-6)
    prob, ref = p.softmax(-1), q.detach().softmax(-1)
    mixture = (prob + ref) / 2
    entropy = lambda x: -(x * x.log()).sum(-1).mean()
    entropy_js = entropy(mixture) - (entropy(prob) + entropy(ref)) / 2
    grad_entropy, = torch.autograd.grad(entropy_js, p)
    assert torch.allclose(whole, entropy_js, atol=1e-6, rtol=1e-6)
    assert torch.allclose(grad_whole, grad_entropy, atol=1e-6, rtol=1e-6)
    chunked.backward()
    assert p.grad is not None and bool(torch.isfinite(p.grad).all()) and p.grad.abs().sum() > 0
    assert q.grad is None
    bounds = []
    for scale in (0, 1, 20, 1000):
        a, b = torch.randn(1, 23, 17) * scale, torch.randn(1, 23, 17) * scale
        value = js_loss(a, b, 5, False).item()
        assert -1e-6 <= value <= math.log(2) + 1e-6
        bounds.append(value)
    # Equal response weights: unequal token lengths must not change the outer mean.
    a = torch.randn(1, 2, 7, requires_grad=True)
    b = torch.randn(1, 9, 7, requires_grad=True)
    aq, bq = torch.randn_like(a), torch.randn_like(b)
    combined = (js_loss(a, aq, 3) + js_loss(b, bq, 3)) / 2
    ga, gb = torch.autograd.grad(combined, (a, b), retain_graph=True)
    ja, = torch.autograd.grad(js_loss(a, aq, 3) / 2, a)
    jb, = torch.autograd.grad(js_loss(b, bq, 3) / 2, b)
    assert torch.allclose(ga, ja) and torch.allclose(gb, jb)
    # First response token is predicted by the last prompt position.
    prefix = {'input_ids': torch.tensor([[0, 1, 2]]), 'attention_mask': torch.ones(1, 3, dtype=torch.long)}
    batch, positions, target = append_response(prefix, [3, 4])
    assert positions.tolist() == [2, 3] and batch['input_ids'].tolist() == [[0, 1, 2, 3, 4]]
    logits = torch.randn(1, 5, 7, requires_grad=True)
    got = mean_response_logp(logits[:, positions], target)
    expected = logits.detach().float().log_softmax(-1)[0, [2, 3], [3, 4]].double().mean().item()
    assert abs(got - expected) < 1e-6
    js_loss(logits[:, positions], torch.randn(1, 2, 7), 1).backward()
    assert bool((logits.grad[:, [0, 1, 4]] == 0).all())
    class FakeTokens:
        eos_token_id = 99999
        def encode(self, text, add_special_tokens=False):
            assert not add_special_tokens
            return list(range(int(text)))
    for finish, n, eos in [('stop',2,True),('stop',4608,True),('stop',4609,False),
                           ('length',2,False),('length',4608,False),('length',4609,False)]:
        ids, info = response_ids({'raw_text':str(n),'finish_reason':finish}, FakeTokens(), {'max_response_tokens':4608})
        assert info['eos_added'] == eos and len(ids) == min(n,4608) + int(eos)
        assert ids[:min(n,4608)] == list(range(min(n,4608)))
    from peft import LoraConfig, get_peft_model
    tiny = get_peft_model(torch.nn.Sequential(torch.nn.Linear(3,5,bias=False)),
                         LoraConfig(r=2,lora_alpha=4,lora_dropout=0.05,target_modules=['0'],bias='none'))
    tiny.eval()
    x = torch.randn(2,3)
    with torch.no_grad(), tiny.disable_adapter():
        frozen_before = tiny(x).clone()
    optimizer = torch.optim.SGD([p for p in tiny.parameters() if p.requires_grad],lr=0.1)
    tiny(x).square().mean().backward()
    optimizer.step()
    with torch.no_grad(), tiny.disable_adapter():
        frozen_after = tiny(x).clone()
    assert torch.equal(frozen_before,frozen_after) and not torch.equal(tiny(x),frozen_before)
    return {'status': 'PASS', 'identity_js': identical.item(), 'whole_js': whole.item(),
            'chunked_js': chunked.item(), 'max_gradient_difference': (grad_whole - grad_chunk).abs().max().item(),
            'bounds': bounds, 'checks': ['identity_zero', 'bounds_0_log2', 'symmetry', 'chunked_value_and_gradient',
                       'student_gradient_only', 'equal_response_weight', 'causal_shift', 'response_only_positions',
                       'EOS_at_below_and_above_cap', 'shared_frozen_teacher_after_tiny_LoRA_update',
                       'independent_entropy_JS_value_and_gradient']}


def config_and_meta(cfg, processor_path):
    expected = {'learning_rate': 1e-5, 'lr_scheduler_type': 'constant', 'warmup_steps': 0, 'optimizer': 'AdamW',
                'adam_beta1': 0.9, 'adam_beta2': 0.999, 'weight_decay': 0.01, 'max_grad_norm': 1.0,
                'batch_size': 1, 'gradient_accumulation_steps': 16, 'num_train_epochs': 1, 'seed': 3407,
                'expected_examples': 4144, 'expected_optimizer_steps': 259, 'save_steps': [130, 259],
                'model_dtype': 'bfloat16', 'loss_dtype': 'float32', 'temperature': None,
                'max_response_tokens': 4608, 'anchor_max_output_tokens': 4096, 'max_model_len': 16384,
                'min_pixels': 1003520, 'max_pixels': 4014080, 'data_shuffle': False,
                'model': 'Qwen/Qwen3-VL-4B-Instruct', 'model_revision': 'ebb281ec70b05090aa6165b016eac8ec08e71b17',
                'loss': 'full_vocabulary_jensen_shannon', 'reduction': 'mean_tokens_per_response_then_equal_response_weight',
                'cuda_alloc_conf': 'expandable_segments:True'}
    for key, value in expected.items():
        assert cfg[key] == value, key
    literal = '\n\nA correct solution to this problem is given below for your reference:\n<solution>\n{anchor}\n</solution>\nGuided by the reference solution, write your own solution.'
    assert cfg['teacher_prompt_suffix'] == literal
    reference = json.loads((ROOT / 'adapter/d3_e1/adapter_config.json').read_bytes())
    for key, source in [('lora_r', 'r'), ('lora_alpha', 'lora_alpha'), ('lora_dropout', 'lora_dropout'), ('target_modules', 'target_modules')]:
        assert cfg[key] == reference[source], key
    import torch
    from transformers import Qwen3VLConfig, Qwen3VLForConditionalGeneration
    from accelerate import init_empty_weights
    architecture = Qwen3VLConfig.from_pretrained(processor_path, local_files_only=True)
    with init_empty_weights(include_buffers=True):
        base = Qwen3VLForConditionalGeneration(architecture)
        model = add_lora(base, cfg)
    result = check_lora(model, cfg)
    assert all(p.device.type == 'meta' for p in model.parameters())
    result.update(status='PASS', meta_architecture_only=True, checkpoint_weights_loaded=False,
                  config_sha256=sha(CONFIG), reference_adapter_config_sha256=sha(ROOT / 'adapter/d3_e1/adapter_config.json'))
    del model, base
    return result


def distribution(values):
    ordered = sorted(values)
    return {'count': len(values), 'min': ordered[0], 'max': ordered[-1], 'mean': statistics.mean(values),
            'median': statistics.median(values),
            'percentiles_nearest_lower': {str(p): ordered[int((len(ordered) - 1) * p / 100)] for p in (25, 75, 90, 95, 99)},
            'bins': {f'({lo},{hi}]': sum(lo < v <= hi for v in values) for lo, hi in ((0,4096),(4096,8192),(8192,12288),(12288,16384))}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--processor', type=Path, default=PROCESSOR)
    args = ap.parse_args()
    report_path = ROOT / 'reports/c1_cpu_check.json'
    lengths_path = ROOT / 'reports/c1_token_lengths.jsonl'
    assert not report_path.exists() and not lengths_path.exists(), 'Refuse to overwrite CPU evidence'
    import torch
    torch.set_num_threads(4)
    started = time.monotonic()
    cfg = json.loads(CONFIG.read_bytes())
    pool, raw_by_row, dev, protected = inputs()
    pool_by_row = {r['row']: r for r in pool}
    entries = read_rows(ROOT / 'data/c1_train.jsonl')
    anchors = {r['row']: r for r in read_rows(ROOT / 'data/c1_anchors.jsonl')}
    data_report = json.loads((ROOT / 'reports/c1_data_validation.json').read_bytes())
    repro = json.loads((ROOT / 'reports/c1_repro_validation.json').read_bytes())
    assert data_report['output_sha256'] == repro['output_sha256']
    for n, wanted in data_report['output_sha256'].items():
        assert sha(ROOT / 'data' / n) == sha(ROOT / 'data/c1_repro' / n) == wanted
    assert len(entries) == 4144 and len(anchors) == 1036
    processor = load_processor(args.processor)
    loss_check = loss_tests()
    structure = config_and_meta(cfg, args.processor)
    by_row, encoded, lengths = defaultdict(list), {}, []
    for index, entry in enumerate(entries):
        by_row[entry['row']].append((index, entry))
    assert not (set(by_row) & dev)
    for done, row in enumerate(sorted(by_row, key=int), 1):
        first = by_row[row][0][1]
        original = pool_by_row[row]
        anchor = anchors[row]
        sample = next(r for r in raw_by_row[row] if r['repeat'] == anchor['anchor_repeat'])
        assert anchor['raw_text'].encode('utf-8') == sample['raw_text'].encode('utf-8')
        assert sample['finish_reason'] == 'stop' and sample['reward'] == 1 and sample['output_tokens'] <= 4096
        student, teacher, proof = prefixes(first, anchor, processor, cfg)
        sid, tid = student['input_ids'][0].tolist(), teacher['input_ids'][0].tolist()
        assert len(sid) == original['prompt_tokens']
        assert sid[-1] == tid[-1] == 198
        expected_text = original['prompt'] + '\n\nA correct solution to this problem is given below for your reference:\n<solution>\n' + anchor['raw_text'] + '\n</solution>\nGuided by the reference solution, write your own solution.'
        assert proof['teacher_user_text'] == expected_text
        encoded[row] = {'student_ids': sid, 'teacher_ids': tid, 'image_tokens': proof['image_tokens']}
        for index, entry in by_row[row]:
            source = next(r for r in raw_by_row[row] if r['repeat'] == entry['repeat'])
            assert entry['raw_text'].encode('utf-8') == source['raw_text'].encode('utf-8')
            assert entry['prompt'].encode('utf-8') == original['prompt'].encode('utf-8')
            assert entry['images'] == original['images'] and entry['anchor_repeat'] == anchor['anchor_repeat']
            assert entry['prompt_tokens'] == source['prompt_tokens'] == len(sid)
            ids, info = response_ids(entry, processor.tokenizer, cfg)
            lengths.append({'index': index, 'row': row, 'repeat': entry['repeat'], 'student_prompt_tokens': len(sid),
                            'teacher_prompt_tokens': len(tid), 'response_tokens': len(ids),
                            'student_total_tokens': len(sid) + len(ids), 'teacher_total_tokens': len(tid) + len(ids),
                            'image_tokens': proof['image_tokens'], 'saved_output_tokens': entry['output_tokens'], **info})
        del student, teacher
        if done % 50 == 0:
            print(f'C1 CPU prefixes {done}/1036; no model weights loaded', flush=True)
    lengths.sort(key=lambda r: r['index'])
    assert len(lengths) == 4144
    longest_student = max(lengths, key=lambda r: r['student_total_tokens'])
    longest_teacher = max(lengths, key=lambda r: r['teacher_total_tokens'])
    if max(longest_student['student_total_tokens'], longest_teacher['teacher_total_tokens']) > 16384:
        write_json(ROOT / 'reports/c1_length_stop.json', {'status': 'STOP', 'longest_student': longest_student, 'longest_teacher': longest_teacher})
        raise SystemExit('Sequence length exceeds 16,384; stop without changing configuration')
    selected = {min(lengths, key=lambda r:r['student_total_tokens'])['index'], longest_student['index'],
                min(lengths, key=lambda r:r['teacher_total_tokens'])['index'], longest_teacher['index']}
    selected.update(range(0, len(entries), max(1, len(entries)//24)))
    for predicate in (lambda x:x['content_was_capped'], lambda x:x['eos_added'], lambda x:entries[x['index']]['finish_reason']=='length'):
        selected.add(next(r['index'] for r in lengths if predicate(r)))
    evidence = []
    for index in sorted(selected):
        entry, info = entries[index], lengths[index]
        cached = encoded[entry['row']]
        ids, _ = response_ids(entry, processor.tokenizer, cfg)
        batches = []
        for key in ('student_ids', 'teacher_ids'):
            prompt = torch.tensor([cached[key]])
            batch, positions, target = append_response({'input_ids':prompt, 'attention_mask':torch.ones_like(prompt)}, ids)
            assert positions[0] == prompt.shape[1] - 1
            assert torch.equal(batch['input_ids'][:, -len(ids):], target)
            batches.append(batch['input_ids'][0,-len(ids):])
        assert torch.equal(*batches)
        evidence.append({**info, 'shared_response_ids_equal': True, 'causal_shift_correct': True})
    assert len(evidence) >= 24
    # The actual pool has one image per used question; exercise two-image encoding separately.
    synthetic = dict(entries[0])
    different = next(r for r in entries if r['row'] != synthetic['row'])
    synthetic['images'] = synthetic['images'] + different['images']
    s, t, proof = prefixes(synthetic, anchors[synthetic['row']], processor, cfg)
    assert s['image_grid_thw'].shape[0] == t['image_grid_thw'].shape[0] == 2
    assert (s['input_ids'] == processor.image_token_id).sum() == (t['input_ids'] == processor.image_token_id).sum()
    multi = {'status':'PASS', 'synthetic':True, 'not_training_data':True, 'images':2,
             'image_tokens':proof['image_tokens'], 'm0_stored_prompt_reference_available':False}
    result = {'status':'PASS', 'device':'CPU', 'model_weights_loaded':False, 'gpu_executed':False,
              'processor_files_sha256':{p.name:sha(p) for p in sorted(args.processor.iterdir()) if p.is_file() and p.suffix in ('.json','.txt','.jinja') and p.name!='model.safetensors.index.json'},
              'data_validation_sha256':sha(ROOT/'reports/c1_data_validation.json'),
              'implementation_sha256':{n:sha(ROOT/'scripts'/n) for n in ('c1_prepare.py','c1_inputs.py','c1_train.py','c1_config.json','c1_check.py','c1_smoke.py')},
              'reuse_code_sha256':{p.relative_to(ROOT/'scripts').as_posix():sha(p) for p in sorted((ROOT/'scripts/frozen_generation').rglob('*.py'))},
              'reproducible_data_hashes':data_report['output_sha256'], 'protected_inputs_sha256':protected,
              'student_prompt_checks':1036, 'prompt_mismatches':0, 'lengths_checked':4144,
              'real_multiple_image_questions':sum(len(pool_by_row[r]['images'])>1 for r in by_row),
              'synthetic_two_image_check':multi, 'detailed_input_checks':evidence,
              'student_lengths':distribution([r['student_total_tokens'] for r in lengths]),
              'teacher_lengths':distribution([r['teacher_total_tokens'] for r in lengths]),
              'longest_student':longest_student, 'longest_teacher':longest_teacher,
              'eos_added':sum(r['eos_added'] for r in lengths), 'content_capped':sum(r['content_was_capped'] for r in lengths),
              'saved_vs_retokenized_count_differences':sum(r['saved_output_tokens']!=r['retokenized_content_tokens'] for r in lengths),
              'loss_tests':loss_check, 'config_and_meta_lora':structure, 'duration_seconds':time.monotonic()-started}
    for name, wanted in protected.items():
        assert sha(ROOT/name) == wanted, name
    with lengths_path.open('xb') as f:
        f.write(serialize(lengths))
    result['token_lengths_sha256'] = sha(lengths_path)
    write_json(report_path, result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('detailed_input_checks','protected_inputs_sha256')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()

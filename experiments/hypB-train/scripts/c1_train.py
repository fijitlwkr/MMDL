"""Single-M0, full-vocabulary JS distillation. Weight loading requires --run + CUDA."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import time

from c1_prepare import ROOT, WORKSPACE, read_rows, sha, write_json
from c1_inputs import append_response, load_processor, prefixes, response_ids

CONFIG = ROOT / 'scripts/c1_config.json'


def js_chunk(student, teacher):
    import torch
    logp = student.float().log_softmax(-1)
    logq = teacher.detach().float().log_softmax(-1)
    logm = torch.logaddexp(logp, logq) - math.log(2)
    return (0.5 * (logp.exp() * (logp - logm) + logq.exp() * (logq - logm))).sum()


def js_loss(student, teacher, chunk_tokens=128, checkpoint_chunks=True):
    import torch
    from torch.utils.checkpoint import checkpoint
    assert student.shape == teacher.shape and student.ndim == 3 and student.shape[0] == 1
    assert chunk_tokens > 0 and student.shape[1] > 0
    terms = []
    for start in range(0, student.shape[1], chunk_tokens):
        p = student[:, start:start + chunk_tokens]
        q = teacher[:, start:start + chunk_tokens].detach()
        if checkpoint_chunks and torch.is_grad_enabled() and p.requires_grad:
            terms.append(checkpoint(js_chunk, p, q, use_reentrant=False))
        else:
            terms.append(js_chunk(p, q))
    return torch.stack(terms).sum() / student.shape[1]


def mean_response_logp(logits, targets, chunk_tokens=128):
    import torch
    assert logits.shape[:2] == targets.shape
    with torch.no_grad():
        total = torch.zeros((), dtype=torch.float64, device=logits.device)
        for start in range(0, targets.shape[1], chunk_tokens):
            part = logits[:, start:start + chunk_tokens].float()
            ids = targets[:, start:start + chunk_tokens]
            values = part.gather(-1, ids.unsqueeze(-1)).squeeze(-1) - part.logsumexp(-1)
            total += values.double().sum()
        return total.item() / targets.numel()


def check_lora(model, cfg):
    layers = [(name, module) for name, module in model.named_modules()
              if hasattr(module, 'lora_A') and 'default' in module.lora_A]
    assert len(layers) == cfg['expected_lora_modules'] == 252
    pattern = re.compile(cfg['target_modules'])
    for name, layer in layers:
        assert pattern.fullmatch(name.removeprefix('base_model.model.')), name
        assert '.visual.' not in name and '.merger.' not in name
        assert layer.r['default'] == cfg['lora_r'] and layer.lora_alpha['default'] == cfg['lora_alpha']
        assert layer.lora_dropout['default'].p == cfg['lora_dropout']
    trainable = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    assert len(trainable) == cfg['expected_trainable_tensors'] == 504
    assert all('.language_model.layers.' in name and ('.lora_A.default.weight' in name or '.lora_B.default.weight' in name)
               for name, _ in trainable)
    assert not any(p.requires_grad for name, p in model.named_parameters() if '.visual.' in name or '.merger.' in name)
    return {'lora_modules': len(layers), 'trainable_tensors': len(trainable), 'visual_trainable_tensors': 0,
            'trainable_parameters': sum(p.numel() for _, p in trainable), 'target_modules': cfg['target_modules']}


def add_lora(base, cfg):
    from peft import LoraConfig, get_peft_model
    model = get_peft_model(base, LoraConfig(task_type='CAUSAL_LM', r=cfg['lora_r'], lora_alpha=cfg['lora_alpha'],
                                         lora_dropout=cfg['lora_dropout'], target_modules=cfg['target_modules'],
                                         bias='none', inference_mode=False, init_lora_weights=True))
    check_lora(model, cfg)
    return model


def seed_all(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_model(path, cfg):
    import torch
    from transformers import Qwen3VLForConditionalGeneration
    assert torch.cuda.is_available(), 'GPU execution requires a separate user approval and CUDA'
    path = path.resolve(strict=True)
    cpu = json.loads((ROOT / 'reports/c1_cpu_check.json').read_bytes())
    for name, expected in cpu['processor_files_sha256'].items():
        assert sha(path / name) == expected, 'M0 processor/config mismatch: ' + name
    for name, expected in cfg['base_sha256'].items():
        assert sha(path / name) == expected, 'Not the pinned M0 base: ' + name
    seed_all(cfg['seed'])
    base = Qwen3VLForConditionalGeneration.from_pretrained(path, dtype=torch.bfloat16,
             attn_implementation=cfg['attn_implementation'], device_map={'': 'cuda:0'}, local_files_only=True)
    base.config.use_cache = False
    model = add_lora(base, cfg)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    model.enable_input_require_grads()
    return model, load_processor(path)


def example_loss(model, processor, entry, anchor, cfg, image_root=WORKSPACE, identical_teacher=False):
    import torch
    student, teacher, evidence = prefixes(entry, anchor, processor, cfg, image_root, identical_teacher)
    assert student['input_ids'].shape[1] == entry['prompt_tokens'], 'Student prompt differs from frozen M0 input'
    ids, token_info = response_ids(entry, processor.tokenizer, cfg)
    sb, sp, targets = append_response(student, ids, model.device)
    tb, tp, teacher_targets = append_response(teacher, ids, model.device)
    assert torch.equal(targets, teacher_targets)
    assert max(sb['input_ids'].shape[1], tb['input_ids'].shape[1]) <= cfg['max_model_len']
    prior_training = model.training
    try:
        model.eval()
        # The base is frozen, and this context removes every LoRA delta from the teacher.
        with torch.no_grad(), model.disable_adapter():
            teacher_logits = model(**tb, logits_to_keep=tp, use_cache=False).logits.detach()
    finally:
        model.train(prior_training)
    student_logits = model(**sb, logits_to_keep=sp, use_cache=False).logits
    assert student_logits.shape[1] == teacher_logits.shape[1] == len(ids)
    loss = js_loss(student_logits, teacher_logits, cfg['js_chunk_tokens'], cfg['checkpoint_js_chunks'])
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError('Non-finite JS loss; stop without changing settings')
    info = {'student_mean_logp': mean_response_logp(student_logits, targets),
            'teacher_mean_logp': mean_response_logp(teacher_logits, targets),
            'response_tokens': len(ids), 'student_sequence_tokens': sb['input_ids'].shape[1],
            'teacher_sequence_tokens': tb['input_ids'].shape[1], **token_info}
    return loss, info


def verify_data(train, anchors, config=CONFIG, image_root=WORKSPACE):
    report = json.loads((ROOT / 'reports/c1_data_validation.json').read_bytes())
    assert sha(train) == report['output_sha256']['c1_train.jsonl']
    assert sha(anchors) == report['output_sha256']['c1_anchors.jsonl']
    # Original R1 material is audited on CPU; the GPU needs only the frozen C1 bundle.
    checked = json.loads((ROOT / 'reports/c1_cpu_check.json').read_bytes())
    assert checked['status'] == 'PASS' and checked['data_validation_sha256'] == sha(ROOT / 'reports/c1_data_validation.json')
    assert sha(config) == checked['config_and_meta_lora']['config_sha256']
    for name, expected in checked['implementation_sha256'].items():
        assert sha(ROOT / 'scripts' / name) == expected, name
    for name, expected in checked['reuse_code_sha256'].items():
        assert sha(ROOT / 'scripts' / name) == expected, name
    for name, expected in report['image_sha256'].items():
        path = (image_root / name).resolve(strict=True)
        assert path.is_relative_to(image_root.resolve()) and sha(path) == expected, name
    return report


def train_loop(args, cfg, model, processor):
    import torch
    assert not args.output.exists(), 'Refuse to overwrite any output directory'
    data_report = verify_data(args.data, args.anchors, args.config, args.image_root)
    entries = read_rows(args.data)
    anchors = {r['row']: r for r in read_rows(args.anchors)}
    assert len(entries) == cfg['expected_examples'] == 4144 and len(anchors) == 1036
    if args.limit is not None:
        assert 0 < args.limit <= len(entries)
        entries = entries[:args.limit]
    if args.max_steps is not None:
        assert 0 < args.max_steps <= math.ceil(len(entries) / cfg['gradient_accumulation_steps'])
        entries = entries[:args.max_steps * cfg['gradient_accumulation_steps']]
    partial = len(entries) != 4144
    structure = check_lora(model, cfg)
    args.output.mkdir(parents=True)
    seed_all(cfg['seed'])
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=cfg['learning_rate'], betas=(cfg['adam_beta1'], cfg['adam_beta2']),
                                 weight_decay=cfg['weight_decay'])
    write_json(args.output / 'c1_run.json', {'config': cfg, 'config_sha256': sha(args.config), 'data_sha256': data_report['output_sha256'],
               'model_start': 'pinned M0 + fresh zero-B LoRA; no adapter load; no resume', 'partial_run': partial,
               'examples': len(entries), 'lora': structure, 'image_root':str(args.image_root.resolve()),
               'cuda_alloc_conf': os.environ['PYTORCH_CUDA_ALLOC_CONF'],
               'scripts_sha256': {name: sha(ROOT / 'scripts' / name) for name in ('c1_train.py', 'c1_inputs.py', 'c1_config.json')}})
    started, records = time.monotonic(), []
    accumulation = cfg['gradient_accumulation_steps']
    with (args.output / 'c1_steps.jsonl').open('x', encoding='utf-8', newline='\n') as log:
        for offset in range(0, len(entries), accumulation):
            window = entries[offset:offset + accumulation]
            optimizer.zero_grad(set_to_none=True)
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            step_started = time.monotonic()
            infos, losses = [], []
            for entry in window:
                anchor = anchors[entry['row']]
                assert anchor['anchor_repeat'] == entry['anchor_repeat']
                loss, info = example_loss(model, processor, entry, anchor, cfg, args.image_root)
                losses.append(loss.item())
                infos.append(info)
                (loss / len(window)).backward()
                del loss
            norm = torch.nn.utils.clip_grad_norm_(params, cfg['max_grad_norm'], error_if_nonfinite=True)
            optimizer.step()
            torch.cuda.synchronize()
            step = len(records) + 1
            record = {'step': step, 'examples': offset + len(window), 'js_loss': sum(losses) / len(window),
                      'grad_norm': float(norm), 'step_seconds': time.monotonic() - step_started,
                      'max_vram_allocated_mib': torch.cuda.max_memory_allocated() / 2**20,
                      'max_vram_reserved_mib': torch.cuda.max_memory_reserved() / 2**20,
                      'response_tokens': sum(r['response_tokens'] for r in infos),
                      'student_mean_logp': sum(r['student_mean_logp'] for r in infos) / len(window),
                      'teacher_mean_logp': sum(r['teacher_mean_logp'] for r in infos) / len(window),
                      'learning_rate': optimizer.param_groups[0]['lr']}
            assert all(math.isfinite(record[k]) for k in ('js_loss', 'grad_norm', 'student_mean_logp', 'teacher_mean_logp'))
            records.append(record)
            log.write(json.dumps(record) + '\n')
            log.flush()
            print(json.dumps(record), flush=True)
            final = offset + len(window) == len(entries)
            if step in cfg['save_steps'] or (partial and final):
                checkpoint = args.output / f'checkpoint-{step}'
                assert not checkpoint.exists()
                model.save_pretrained(checkpoint, safe_serialization=True)
                shutil.copyfile(args.config, checkpoint / 'c1_config.json')
                write_json(checkpoint / 'c1_step.json', record)
    assert partial or len(records) == cfg['expected_optimizer_steps'] == 259
    result = {'status': 'PASS', 'steps': len(records), 'examples': len(entries), 'partial_run': partial,
              'training_seconds': time.monotonic() - started,
              'estimated_full_259_step_seconds': sum(r['step_seconds'] for r in records) / len(records) * 259,
              'last_step': records[-1]}
    write_json(args.output / 'c1_training_summary.json', result)
    return result


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', action='store_true', help='GPU execution; requires separate user approval')
    ap.add_argument('--config', type=Path, default=CONFIG)
    ap.add_argument('--model-path', type=Path, required=True)
    ap.add_argument('--data', type=Path, default=ROOT / 'data/c1_train.jsonl')
    ap.add_argument('--anchors', type=Path, default=ROOT / 'data/c1_anchors.jsonl')
    ap.add_argument('--image-root', type=Path, default=WORKSPACE)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--max-steps', type=int)
    ap.add_argument('--limit', type=int)
    return ap


def main():
    ap = parser()
    args = ap.parse_args()
    if not args.run:
        ap.error('Weight loading and training require explicit --run and a separate GPU instruction')
    cfg = json.loads(args.config.read_bytes())
    if os.environ.get('PYTORCH_CUDA_ALLOC_CONF') != cfg['cuda_alloc_conf']:
        ap.error('Set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True before launching Python')
    assert not args.output.exists()
    verify_data(args.data, args.anchors, args.config, args.image_root)
    model, processor = load_model(args.model_path, cfg)
    train_loop(args, cfg, model, processor)


if __name__ == '__main__':
    main()

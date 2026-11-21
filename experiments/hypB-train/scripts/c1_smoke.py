"""Prepared GPU probes and 20-step trial. This file is not run by CPU preparation."""
import argparse
import gc
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys

from c1_prepare import ROOT, read_rows, sha, write_json


def vllm_load():
    ap = argparse.ArgumentParser(description='Load only; never generate benchmark responses')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--model-path', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(sys.argv[2:])
    if not args.run:
        ap.error('GPU loading requires explicit --run and separate user approval')
    assert not args.output.exists() and version('vllm') == '0.11.0'
    import yaml
    from frozen_generation.vllm_engine import VLLMEngine
    config = ROOT / 'scripts/frozen_generation/config.yaml'
    assert sha(config) == '3946c9a93cd5ab1cc5a8010fc00473e8a71f1c589e0a5f664edb70a3097234dc'
    engine = VLLMEngine(yaml.safe_load(config.read_text(encoding='utf-8')), args.model_path.resolve(strict=True))
    write_json(args.output, {'status':'PASS', 'vllm_version':version('vllm'), 'generation_requests':0,
                            'initialization_seconds':engine.init_seconds, 'config_sha256':sha(config)})


def main():
    from c1_train import example_loss, load_model, parser, train_loop, verify_data
    ap = parser()
    ap.description = __doc__
    ap.add_argument('--merge-python', type=Path, required=True)
    ap.add_argument('--merge-script', type=Path, required=True, help='Existing hypB_train/yoonseok/merge.py; keep sibling train.py/config')
    ap.add_argument('--vllm-python', type=Path, required=True)
    args = ap.parse_args()
    if not args.run:
        ap.error('GPU smoke requires explicit --run and separate user approval')
    cfg = json.loads(args.config.read_bytes())
    assert os.environ.get('PYTORCH_CUDA_ALLOC_CONF') == cfg['cuda_alloc_conf']
    assert args.max_steps in (None, 20) and args.limit is None
    assert not args.output.exists()
    for p in (args.merge_python, args.merge_script, args.vllm_python):
        assert p.is_file(), p
    verify_data(args.data, args.anchors, args.config, args.image_root)
    entries = read_rows(args.data)
    anchors = {r['row']:r for r in read_rows(args.anchors)}
    cpu = json.loads((ROOT / 'reports/c1_cpu_check.json').read_bytes())
    model, processor = load_model(args.model_path, cfg)
    import torch
    smoke_output = args.output
    args.output.mkdir(parents=True)
    stage = 'identity'
    try:
        model.eval()
        with torch.no_grad():
            entry = entries[0]
            identity, _ = example_loss(model, processor, entry, anchors[entry['row']], cfg, args.image_root, True)
            assert abs(identity.item()) <= 1e-6
        identity_value = identity.item()
        del identity
        stage = 'reference_effect'
        correct = [r for r in entries if r['reward'] == 1][:20]
        assert len(correct) == 20
        effect = []
        with torch.no_grad():
            for entry in correct:
                loss, info = example_loss(model, processor, entry, anchors[entry['row']], cfg, args.image_root)
                effect.append({'row':entry['row'], 'repeat':entry['repeat'], 'js_loss':loss.item(), **info})
                del loss
        assert all(r['js_loss'] > 0 for r in effect)
        logp_gain = sum(r['teacher_mean_logp'] - r['student_mean_logp'] for r in effect) / 20
        assert logp_gain > 0, 'Teacher reference does not improve mean logp; stop without changing settings'
        stage = 'longest_forward_backward'
        entry = entries[cpu['longest_teacher']['index']]
        model.train()
        model.zero_grad(set_to_none=True)
        torch.cuda.reset_peak_memory_stats()
        loss, info = example_loss(model, processor, entry, anchors[entry['row']], cfg, args.image_root)
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0, error_if_nonfinite=True)
        longest = {'row':entry['row'], 'repeat':entry['repeat'], 'js_loss':loss.item(), 'grad_norm':float(norm),
                   'max_vram_allocated_mib':torch.cuda.max_memory_allocated()/2**20,
                   'max_vram_reserved_mib':torch.cuda.max_memory_reserved()/2**20, **info}
        assert info['teacher_sequence_tokens'] == cpu['longest_teacher']['teacher_total_tokens']
        del loss
        model.zero_grad(set_to_none=True)
        write_json(args.output / 'c1_probe_results.json', {'status':'PASS', 'identity_js':identity_value,
                   'identity_tolerance':1e-6, 'correct_response_effect':effect, 'mean_teacher_logp_gain':logp_gain,
                   'longest_forward_backward':longest, 'optimizer_steps_before_trial':0})
        stage = '20_step_training'
        output = args.output
        args.output = output / 'c1_training'
        args.max_steps, args.limit = 20, None
        training = train_loop(args, cfg, model, processor)
        assert training['steps'] == 20
        checkpoint = args.output / 'checkpoint-20'
        assert (checkpoint / 'adapter_model.safetensors').is_file()
        args.output = output
        # Release the training model before the separate merge/load subprocesses.
        del model, processor
        gc.collect()
        torch.cuda.empty_cache()
        stage = 'merge'
        merged = output / 'c1_merged'
        env = {**os.environ, 'HF_HUB_OFFLINE':'1', 'HF_DATASETS_OFFLINE':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
        with (output / 'c1_merge.log').open('x') as f:
            subprocess.run([str(args.merge_python), '-B', str(args.merge_script), str(checkpoint), str(merged)],
                           stdout=f, stderr=subprocess.STDOUT, check=True, env=env)
        hashes = {p.name:sha(p) for p in sorted(merged.glob('*.safetensors'))}
        assert hashes
        stage = 'vllm_load_only'
        with (output / 'c1_vllm.log').open('x') as f:
            subprocess.run([str(args.vllm_python), '-B', str(Path(__file__).resolve()), 'vllm-load', '--run',
                            '--model-path', str(merged), '--output', str(output / 'c1_vllm_load.json')],
                           stdout=f, stderr=subprocess.STDOUT, check=True, env=env)
        result = {'status':'PASS', 'training':training, 'adapter_sha256':sha(checkpoint / 'adapter_model.safetensors'),
                  'merged_sha256':hashes, 'generation_requests':0, 'full_training_started':False,
                  'estimated_full_training_over_8h':training['estimated_full_259_step_seconds'] > 8*3600}
        write_json(output / 'c1_smoke_summary.json', result)
        print(json.dumps(result), flush=True)
    except BaseException as exc:
        write_json(smoke_output / 'c1_smoke_failed.json', {'status':'STOP','stage':stage,'error_type':type(exc).__name__,
                   'settings_changed':False,'full_training_started':False})
        raise


if __name__ == '__main__':
    if sys.argv[1:2] == ['vllm-load']:
        vllm_load()
    else:
        main()

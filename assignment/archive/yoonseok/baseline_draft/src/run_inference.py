"""Common vLLM inference, or lossless text import from saved Qwen JSONL predictions."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import subprocess
import threading
import time
from pathlib import Path
from common import ROOT, MODEL, MODEL_REVISION, read_rows, validate, write_rows, write_json, check_output, input_metadata

def prompt_text(row, style='official'):
    text = ''
    if row.get('hint'):
        text += f"Hint: {row['hint']}\n"
    text += f"Question: {row['question']}\n"
    if row['question_type'] == 'multiple-choice':
        text += 'Options:\n' + ''.join(f'{k}. {v}\n' for k, v in row['options'].items())
        text += 'Please select the correct answer from the options above.'
        if style == 'answer-only':
            text += '\nOutput only the single correct option letter. Do not include an explanation.'
    elif style == 'answer-only':
        text += '\nOutput only the final answer. Do not include an explanation.'
    return text.rstrip()

def import_qwen(path):
    path = Path(path).resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        old = json.loads(line)
        ann = old['annotation']
        result = old['result']
        # Preserve the exact saved final text; gen_raw remains available for audit.
        if not isinstance(result.get('gen'), str):
            raise ValueError(f"No saved gen field: {old.get('question_id')}")
        images = [c['image'] for m in old.get('messages', []) for c in m['content'] if c['type'] == 'image']
        choices = {k: str(v) for k, v in ann.items() if len(k) == 1 and k in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' and v is not None and not (isinstance(v, float) and math.isnan(v)) and str(v).strip()}
        row = {'uid': ann['id'], 'subject': ann['l2-category'], 'split': ann['split'],
               'question': ann['question'], 'question_type': ann['question_type'],
               'options': choices if ann['question_type'] == 'multiple-choice' else {},
               'answer': ann['answer'], 'images': images, 'prediction': result['gen'],
               'prediction_raw': result.get('gen_raw', result['gen']), 'finish_reason': None, 'generated_tokens': None,
               'provenance': {'source': 'imported_qwen_jsonl', 'source_name': path.name, 'source_sha256': digest,
                              'model_revision': None, 'dataset_revision': None, 'status': 'preliminary_existing_run'}}
        if row['question_type'] == 'multiple-choice':
            golds = row['answer'] if isinstance(row['answer'], list) else [row['answer']]
            missing = [gold for gold in golds if gold not in choices]
            if missing:
                row['data_issue'] = {'type': 'missing_gold_option_text', 'missing_labels': missing,
                                     'policy': 'invalid imported sample; count incorrect, do not guess option content'}
        if isinstance(ann.get('hint'), str):
            row['hint'] = ann['hint']
        rows.append(row)
    validate(rows, predictions=True)
    return rows

class GPUMonitor:
    """Sample device-wide memory; explicitly not per-process or an exact allocator peak."""
    def __init__(self):
        self.stop_event = threading.Event()
        self.peak = {}
        self.samples = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
    def _run(self):
        while not self.stop_event.is_set():
            try:
                out = subprocess.run(['nvidia-smi', '--query-gpu=uuid,memory.used', '--format=csv,noheader,nounits'],
                                     capture_output=True, text=True, timeout=5, check=True).stdout
                for line in out.splitlines():
                    uuid, memory = line.split(',')
                    self.peak[uuid.strip()] = max(float(memory.strip()), self.peak.get(uuid.strip(), 0))
                self.samples += 1
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            self.stop_event.wait(1)
    def __enter__(self):
        self.thread.start()
        return self
    def __exit__(self, *args):
        self.stop_event.set(); self.thread.join(timeout=6)


def generate(args, rows):
    os.environ.setdefault('VLLM_WORKER_MULTIPROC_METHOD', 'spawn')
    from transformers import AutoProcessor
    from qwen_vl_utils import process_vision_info
    from vllm import LLM, SamplingParams
    started = time.perf_counter()
    model_path = Path(args.model)
    # Local paths must point to the intended revision; no claim of automatic verification.
    local_model = model_path.exists()
    revision = None if local_model else args.model_revision
    model_kwargs = {} if revision is None else {'revision': revision}
    settings = {k: getattr(args, k) for k in ['model', 'model_revision', 'max_model_len', 'max_new_tokens', 'temperature',
                'top_p', 'top_k', 'repetition_penalty', 'presence_penalty', 'seed', 'min_pixels', 'max_pixels',
                'batch_size', 'prompt_style', 'dtype', 'gpu_memory_utilization', 'tensor_parallel_size', 'max_images']}
    settings['revision_applied'] = revision
    base = Path(args.input).resolve().parent
    for row in rows:
        if len(row['images']) > args.max_images:
            raise ValueError(f"Too many images: {row['uid']}")
        for image in row['images']:
            if not (base/image).is_file():
                raise FileNotFoundError(base/image)
    with GPUMonitor() as monitor:
        processor = AutoProcessor.from_pretrained(args.model, **model_kwargs)
        llm = LLM(model=args.model, **model_kwargs, tokenizer_revision=revision, dtype=args.dtype,
                  tensor_parallel_size=args.tensor_parallel_size, gpu_memory_utilization=args.gpu_memory_utilization,
                  max_model_len=args.max_model_len, limit_mm_per_prompt={'image': args.max_images},
                  seed=args.seed, generation_config='vllm')
        sampling = SamplingParams(max_tokens=args.max_new_tokens, temperature=args.temperature, top_p=args.top_p,
                                  top_k=args.top_k, repetition_penalty=args.repetition_penalty,
                                  presence_penalty=args.presence_penalty)
        output_rows = []
        batch_times = []
        for start in range(0, len(rows), args.batch_size):
            batch = rows[start:start+args.batch_size]
            requests = []
            for row in batch:
                content = [{'type': 'image', 'image': str((base/x).resolve()), 'min_pixels': args.min_pixels,
                            'max_pixels': args.max_pixels} for x in row['images']]
                content.append({'type': 'text', 'text': prompt_text(row, args.prompt_style)})
                messages = [{'role': 'user', 'content': content}]
                text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                image_inputs, _, kwargs = process_vision_info(messages,
                    image_patch_size=processor.image_processor.patch_size, return_video_kwargs=True, return_video_metadata=True)
                request = {'prompt': text, 'mm_processor_kwargs': kwargs}
                if image_inputs is not None:
                    request['multi_modal_data'] = {'image': image_inputs}
                requests.append(request)
            clock = time.perf_counter()
            outputs = llm.generate(requests, sampling_params=sampling)
            elapsed = time.perf_counter() - clock
            batch_times.append(elapsed)
            if len(outputs) != len(batch):
                raise RuntimeError('vLLM returned the wrong number of outputs')
            for row, output in zip(batch, outputs):
                completion = output.outputs[0]
                raw = completion.text
                # Same postprocessing used in the existing Qwen runner; keep raw text.
                final = raw.split('</think>')[-1].strip()
                output_rows.append({**row, 'images': [str((base/x).resolve()) for x in row['images']],
                    'prediction': final, 'prediction_raw': raw, 'prompt_text': prompt_text(row, args.prompt_style),
                    'finish_reason': completion.finish_reason, 'stop_reason': completion.stop_reason,
                    'generated_tokens': len(completion.token_ids), 'prompt_tokens': len(output.prompt_token_ids or []),
                    'batch_elapsed_seconds': elapsed, 'batch_size_actual': len(batch), 'inference': settings})
            print(f'Completed {len(output_rows)}/{len(rows)}')
    versions = {name: importlib.metadata.version(name) for name in ['torch', 'vllm', 'transformers', 'qwen-vl-utils']}
    return output_rows, {'mode': 'vllm', 'settings': settings, 'versions': versions,
        'elapsed_including_load_seconds': time.perf_counter()-started, 'generate_seconds': sum(batch_times),
        'gpu_memory': {'measurement': 'device-wide sampled peak MiB; includes other processes; 1s interval',
                       'peak_mib_by_uuid': monitor.peak, 'samples': monitor.samples}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group()
    source.add_argument('--input', default=None)
    source.add_argument('--import-qwen-jsonl', help='Reuse saved Qwen predictions without GPU or model/API calls')
    p.add_argument('--output', default=str(ROOT/'data/predictions_val.jsonl'))
    p.add_argument('--model', default=os.environ.get('BASELINE_MODEL', MODEL))
    p.add_argument('--model-revision', default=os.environ.get('BASELINE_MODEL_REVISION', MODEL_REVISION))
    p.add_argument('--max-model-len', type=int, default=9048)
    p.add_argument('--max-new-tokens', type=int, default=2048)
    p.add_argument('--temperature', type=float, default=.7)
    p.add_argument('--top-p', type=float, default=.8)
    p.add_argument('--top-k', type=int, default=20)
    p.add_argument('--repetition-penalty', type=float, default=1.0)
    p.add_argument('--presence-penalty', type=float, default=1.5)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--min-pixels', type=int, default=1280*28*28)
    p.add_argument('--max-pixels', type=int, default=5120*28*28)
    p.add_argument('--max-images', type=int, default=10)
    p.add_argument('--batch-size', type=int, default=32)
    p.add_argument('--tensor-parallel-size', type=int, default=1)
    p.add_argument('--gpu-memory-utilization', type=float, default=.9)
    p.add_argument('--dtype', choices=['bfloat16', 'auto'], default='bfloat16')
    p.add_argument('--prompt-style', choices=['official', 'answer-only'], default='official')
    p.add_argument('--force', action='store_true')
    args = p.parse_args()
    if args.batch_size < 1 or args.max_new_tokens < 1 or args.max_new_tokens >= args.max_model_len:
        p.error('Positive batch/tokens required; max-new-tokens must leave room for input in max-model-len')
    if not 0 < args.min_pixels <= args.max_pixels:
        p.error('Require 0 < min-pixels <= max-pixels')
    output = Path(args.output).resolve()
    check_output(output, args.force); check_output(output.with_suffix('.meta.json'), args.force)
    if args.import_qwen_jsonl:
        if Path(args.import_qwen_jsonl).resolve() == output:
            p.error('Import input and output must differ')
        rows = import_qwen(args.import_qwen_jsonl)
        metadata = {'mode': 'import', 'source': str(Path(args.import_qwen_jsonl).resolve()),
                    'note': 'No inference performed. Historical model/data revisions, timing and finish reasons not inferred.'}
    else:
        args.input = args.input or str(ROOT/'data/dataset_val.jsonl')
        if Path(args.input).resolve() == output:
            p.error('Dataset and prediction output must differ')
        dataset = read_rows(args.input)
        rows, metadata = generate(args, dataset)
        metadata['input'] = input_metadata(args.input, dataset)
    validate(rows, predictions=True)
    write_rows(output, rows, args.force)
    metadata['num_examples'] = len(rows)
    metadata['prediction_sha256'] = hashlib.sha256(output.read_bytes()).hexdigest()
    write_json(output.with_suffix('.meta.json'), metadata, args.force)
    print(f'Saved {len(rows)} predictions: {output}')

if __name__ == '__main__':
    main()

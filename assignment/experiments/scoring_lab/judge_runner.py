#!/usr/bin/env python3
"""Shared, resumable Judge requests. Dry-run by default; --execute sends API calls."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import urllib.request
import uuid

import lab
from parsers import PRIMARY_PARSERS, qwen_parse

MODEL = 'gpt-4.1-mini-2025-04-14'
ENDPOINT = 'https://api.openai.com/v1/chat/completions'
DEFAULT_POLICIES = [f'{p}__always_judge' for p in PRIMARY_PARSERS]
INPUT_PRICE, OUTPUT_PRICE = .40, 1.60


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_jsonl(path, row):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def exclusive_lock(out):
    path = out / 'runner.lock'
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('Runner lock exists. Check for a running/interrupted process before clearing it.') from None
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'created_at': now()}))
        yield
    finally:
        path.unlink()


def settings():
    root = Path(__file__).resolve().parent
    return {
        'protocol': 'scoring-lab-common-judge-v1', 'model': MODEL, 'endpoint': ENDPOINT,
        'temperature': 0, 'top_p': 1, 'seed': 3407, 'max_tokens': 8,
        'timeout_seconds': 60, 'attempts_per_item': 1, 'semantic_retries': 0,
        'full_response': True, 'response_parser': 'pinned_qwen_can_infer_and_finish_stop',
        'code_sha256': {str(p.relative_to(root)): lab.file_hash(p) for p in
                        [root/'judge_runner.py', root/'lab.py', root/'parsers.py', root/'vendor/qwen_eval_utils.py']},
        'prices_per_million': {'input_uncached': INPUT_PRICE, 'output': OUTPUT_PRICE},
        'price_date': '2026-09-19',
        'price_source': 'https://developers.openai.com/api/docs/models/gpt-4.1-mini',
    }


def reserve_cost(request):
    # UTF-8 byte count bounds text tokens; allow additional message framing.
    return ((len(request['prompt'].encode('utf-8')) + 256) * INPUT_PRICE + 8 * OUTPUT_PRICE) / 1e6


def usage_cost(prompt, completion):
    return (prompt * INPUT_PRICE + completion * OUTPUT_PRICE) / 1e6


def send_request(payload, key):
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode('utf-8'), method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def parse_response(data, choices):
    usage = data.get('usage') or {}
    counts = [usage.get('prompt_tokens'), usage.get('completion_tokens')]
    if any(not isinstance(n, int) or isinstance(n, bool) or n < 0 for n in counts):
        raise ValueError('Missing or invalid API usage')
    if data.get('model') != MODEL:
        raise ValueError('API response model differs from pinned snapshot')
    choice = data['choices'][0]
    raw = choice['message'].get('content')
    if raw is None:
        raw = ''
    if not isinstance(raw, str):
        raise ValueError('Unexpected Judge response content type')
    parsed = qwen_parse(raw, choices) if choice.get('finish_reason') == 'stop' else None
    return {
        'status': 'success' if parsed is not None else 'extraction_failure',
        'raw_output': raw, 'parsed': parsed,
        'response_model': data['model'], 'finish_reason': choice.get('finish_reason'),
        'system_fingerprint': data.get('system_fingerprint'),
        'prompt_tokens': counts[0], 'completion_tokens': counts[1], 'usage': usage,
        'estimated_cost_usd_uncached': usage_cost(*counts),
    }


def make_report(rows, requests, selected, policies, cache, journal, budget, calls, reason, source_kind):
    items = {r['id']: r for r in rows}
    pending = [uid for uid in selected if uid not in cache or cache[uid]['status'] == 'api_error']
    known_cost = sum(r.get('estimated_cost_usd_uncached', 0) for r in cache.values())
    uncertain = [r for r in journal if r['id'] not in cache or cache[r['id']]['status'] == 'api_error']
    reserved = sum(r['reserved_cost_upper_usd'] for r in uncertain)
    report = {
        'source_kind': source_kind, 'model': MODEL, 'selected_policies': policies,
        'judge_union': len(selected), 'pending': len(pending),
        'success': sum(cache.get(uid, {}).get('status') == 'success' for uid in selected),
        'extraction_failure': sum(cache.get(uid, {}).get('status') == 'extraction_failure' for uid in selected),
        'api_error': sum(cache.get(uid, {}).get('status') == 'api_error' for uid in selected),
        'api_calls_this_invocation': calls, 'api_started_total': len(journal), 'stop_reason': reason,
        'budget_usd': budget, 'known_usage_cost_usd_uncached': known_cost,
        'uncertain_reserved_cost_usd': reserved,
        'remaining_request_cost_upper_usd': sum(reserve_cost(requests[uid]) for uid in pending),
        'cost_note': 'Usage-based estimate, not invoice; no cached-token discount or tax. Policy costs overlap.',
        'policy_costs': {}, 'length_diagnostics': {},
    }
    for policy in policies:
        ids = [r['id'] for r in rows if r['analysis']['policies'][policy]['route'] != 'auto']
        report['policy_costs'][policy] = {
            'required': len(ids),
            'pending': sum(uid not in cache or cache[uid]['status'] == 'api_error' for uid in ids),
            'standalone_known_cost_usd_uncached': sum(cache.get(uid, {}).get('estimated_cost_usd_uncached', 0) for uid in ids),
        }
    for question_type in ['multiple-choice', 'open']:
        ids = [uid for uid in selected if items[uid]['finish_reason'] == 'length' and items[uid]['question_type'] == question_type]
        successful = [uid for uid in ids if cache.get(uid, {}).get('status') == 'success']
        correct = sum(cache[uid]['parsed'] == (items[uid]['answer'] if question_type == 'multiple-choice' else 'A') for uid in successful)
        failures = [uid for uid in ids if cache.get(uid, {}).get('status') == 'extraction_failure']
        z = sum(cache[uid].get('raw_output', '').strip().upper() == 'Z' for uid in failures)
        report['length_diagnostics'][question_type] = {
            'selected': len(ids), 'valid_answer': len(successful), 'z': z,
            'other_extraction_failure': len(failures)-z,
            'api_error': sum(cache.get(uid, {}).get('status') == 'api_error' for uid in ids),
            'pending_including_api_error': sum(uid not in cache or cache[uid]['status'] == 'api_error' for uid in ids),
            'valid_answer_correct': correct,
            'accuracy_among_valid_answers': correct/len(successful) if successful else None,
            'score_lower_bound_all_selected': correct/len(ids) if ids else None,
            'uniform_guess_reference_same_valid_cohort': sum(1/len(items[uid]['options']) for uid in successful)/len(successful)
                if successful and question_type == 'multiple-choice' else None,
            'note': 'GT accuracy is not extraction faithfulness; no inference of random guessing from this statistic.',
        }
    mc = [r for r in rows if r['question_type'] == 'multiple-choice']
    exposed = {r['id'] for r in mc if any(k not in 'ABCD' for k in r['options'])}
    report['ad_prompt_exposure'] = {
        'mc_option_count_distribution': dict(Counter(len(r['options']) for r in mc)),
        'mc_with_options_outside_ad': len(exposed),
        'mc_gt_outside_ad': sum(r['answer'] not in 'ABCD' for r in mc),
        'judge_union_with_options_outside_ad': len(set(selected) & exposed),
        'policy_judge_counts': {p: sum(r['id'] in exposed and r['analysis']['policies'][p]['route'] != 'auto' for r in mc) for p in policies},
        'note': 'Exposure to original Qwen prompt wording; this is not an observed error count.',
    }
    return report


def run(args, transport=send_request):
    if not math.isfinite(args.budget_usd) or args.budget_usd <= 0 or args.limit < 0:
        raise ValueError('Require a finite positive budget and a nonnegative limit')
    policies = list(dict.fromkeys(args.policies))
    if not policies or any(p not in lab.POLICIES for p in policies):
        raise ValueError('Unknown/empty policy selection')
    rows, manifest, requests = lab.validated_judge_requests(args.run)
    selected = sorted(r['id'] for r in rows if any(r['analysis']['policies'][p]['route'] != 'auto' for p in policies))
    choices = {r['id']: r['options'] if r['question_type'] == 'multiple-choice' else {'A': r['answer'], 'B': 'Other Answers'} for r in rows}
    config = settings()
    settings_hash = lab.digest(config)
    binding = {'analysis_id': manifest['analysis_id'], 'judge_settings_sha256': settings_hash,
               'requests_sha256': lab.file_hash(args.run/'judge_requests.jsonl'), 'settings': config}
    args.out.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(args.out):
        config_path = args.out/'judge_settings.json'
        cache_path = args.out/'judge_results.jsonl'
        journal_path = args.out/'api_attempts.jsonl'
        if config_path.exists():
            if json.loads(config_path.read_text(encoding='utf-8')) != binding:
                raise ValueError('Different inputs/model/settings/code: create a separate cache directory')
        else:
            if cache_path.exists() or journal_path.exists():
                raise ValueError('Refusing cache without its settings manifest')
            atomic_json(config_path, binding)
        if not cache_path.exists():
            cache_path.touch()
        cache = lab.validated_judge_cache(args.run, cache_path, MODEL)
        if any(r['judge_settings_sha256'] != settings_hash for r in cache.values()):
            raise ValueError('Cache/settings hash mismatch')
        journal = lab.read_jsonl(journal_path) if journal_path.exists() else []
        if len({r['id'] for r in journal}) != len(journal):
            raise ValueError('Duplicate API starts: review possible repeated billing')
        for entry in journal:
            request = requests.get(entry.get('id'))
            if not request or entry.get('request_sha256') != request['request_sha256'] or entry.get('judge_settings_sha256') != settings_hash:
                raise ValueError('API journal identity mismatch')
            if entry.get('reserved_cost_upper_usd') != reserve_cost(request):
                raise ValueError('API reservation changed')
        journal_by_id = {r['id']: r for r in journal}
        for uid, record in cache.items():
            if uid not in journal_by_id or record.get('attempt_id') != journal_by_id[uid]['attempt_id']:
                raise ValueError('Cache result has no matching API start')
            if record['status'] != 'api_error':
                decoded = parse_response({'model': record.get('response_model'), 'usage': record.get('usage'),
                    'system_fingerprint': record.get('system_fingerprint'),
                    'choices': [{'message': {'content': record['raw_output']}, 'finish_reason': record.get('finish_reason')}]}, choices[uid])
                if any(record.get(k) != v for k, v in decoded.items()):
                    raise ValueError('Cached usage, parsed answer, or cost was modified')
        uncertain = any(r['id'] not in cache or cache[r['id']]['status'] == 'api_error' for r in journal)
        pending = [uid for uid in selected if uid not in cache]
        key = os.getenv('OPENAI_API_KEY', '')
        if args.execute and uncertain:
            raise ValueError('Earlier failed/interrupted API call requires review; no automatic retry')
        if args.execute and pending and not key:
            raise ValueError('OPENAI_API_KEY is missing; no API requests sent')
        started_this_run = 0
        reason = 'dry_run' if not args.execute else 'complete'
        spent = sum(r.get('estimated_cost_usd_uncached', 0) for r in cache.values())
        if args.execute:
            for uid in pending:
                if args.limit and started_this_run >= args.limit:
                    reason = 'limit'
                    break
                request = requests[uid]
                reserve = reserve_cost(request)
                if spent + reserve > args.budget_usd:
                    reason = 'budget'
                    break
                attempt_id = str(uuid.uuid4())
                entry = {'id': uid, 'attempt_id': attempt_id, 'started_at': now(),
                         'request_sha256': request['request_sha256'], 'judge_settings_sha256': settings_hash,
                         'reserved_cost_upper_usd': reserve}
                append_jsonl(journal_path, entry)
                journal.append(entry)
                started_this_run += 1
                began = time.monotonic()
                payload = {'model': MODEL, 'temperature': 0, 'top_p': 1, 'seed': 3407, 'max_tokens': 8,
                           'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': request['prompt']}]}]}
                record = {'id': uid, 'attempt_id': attempt_id, 'request_sha256': request['request_sha256'],
                          'judge_settings_sha256': settings_hash, 'model': MODEL, 'attempts': 1}
                try:
                    response = transport(payload, key)
                    record.update(parse_response(response, choices[uid]))
                except Exception as exc:
                    # No exception message, HTTP body, request headers, or key is logged.
                    record.update(status='api_error', parsed=None, raw_output=None,
                                  error_type=type(exc).__name__, http_status=getattr(exc, 'code', None))
                    reason = 'api_error'
                record['latency_seconds'] = round(time.monotonic()-began, 3)
                append_jsonl(cache_path, record)
                cache[uid] = record
                spent += record.get('estimated_cost_usd_uncached', reserve)
                print(json.dumps({'id': uid, 'status': record['status'], 'api_calls': started_this_run}))
                if record['status'] == 'api_error':
                    break
        report = make_report(rows, requests, selected, policies, cache, journal, args.budget_usd,
                             started_this_run, reason, manifest['source_kind'])
        report['judge_settings_sha256'] = settings_hash
        atomic_json(args.out/'execution_summary.json', report)
        append_jsonl(args.out/'invocations.jsonl', {'time': now(), 'execute': args.execute, 'policies': policies,
                                                'budget_usd': args.budget_usd, 'api_calls': started_this_run, 'reason': reason})
        print(json.dumps({k: report[k] for k in ['source_kind','judge_union','pending','api_calls_this_invocation',
                                               'known_usage_cost_usd_uncached','stop_reason']}))
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--policies', nargs='+', default=DEFAULT_POLICIES)
    parser.add_argument('--budget-usd', type=float, default=1.0)
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--execute', action='store_true', help='Send paid API requests; omission is a dry-run')
    args = parser.parse_args()
    try:
        report = run(args)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.exit(2, str(exc)+'\n')
    if report['stop_reason'] == 'api_error':
        parser.exit(1, 'API error; remaining items are pending.\n')


if __name__ == '__main__':
    main()

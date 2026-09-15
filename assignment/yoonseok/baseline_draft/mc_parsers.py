"""Pinned MMMU and VLMEvalKit rule parsers, with explicit failure tracking.
See vendor/sources.json and the bundled upstream licenses.
"""
import argparse
import os
import random
import types
from vendor import mmmu_eval, vlmevalkit_matching

class TrackedRandom:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.used = False
    def choice(self, choices):
        self.used = True
        return self.rng.choice(choices)

class MMMUParser:
    """Official algorithm; seeded sequential fallback follows input row order."""
    def __init__(self, seed=42):
        self.random = TrackedRandom(seed)
        source = mmmu_eval.parse_multi_choice_response
        self.parse_fn = types.FunctionType(source.__code__, {**source.__globals__, 'random': self.random})
    def parse(self, text, choices):
        if not choices:
            raise ValueError('MC parser needs choices')
        self.random.used = False
        result = self.parse_fn(text, list(choices), dict(choices))
        return {'parsed': result, 'parse_success': not self.random.used,
                'random_fallback': self.random.used}

def parse_vlmevalkit(text, choices):
    # Upstream has a VERBOSE-sensitive branch. Fix and restore it for reproducibility.
    previous = os.environ.pop('VERBOSE', None)
    try:
        result = vlmevalkit_matching.can_infer(text, dict(choices))
    finally:
        if previous is not None:
            os.environ['VERBOSE'] = previous
    return {'parsed': result if result else None, 'parse_success': result in choices,
            'random_fallback': False}

def parse_open(text):
    # Upstream returns a set-derived list; sorting only stabilizes JSON ordering.
    return sorted(mmmu_eval.parse_open_response(text), key=lambda x: (type(x).__name__, str(x)))

def score_open(answer, parsed):
    return bool(mmmu_eval.eval_open(answer, parsed))

def score_mc(answer, parsed):
    return bool(mmmu_eval.eval_multi_choice(answer, parsed))

def self_test():
    choices = {'A': 'red', 'B': 'blue', 'C': 'green', 'D': 'yellow'}
    parser = MMMUParser()
    assert parser.parse('After checking (A), the final answer is (B).', choices)['parsed'] == 'B'
    assert parser.parse('', choices)['random_fallback']
    assert not parse_vlmevalkit('Cannot determine the answer', choices)['parse_success']
    assert parse_vlmevalkit('(C)', choices)['parsed'] == 'C'
    assert choices['A'] == 'red'
    assert score_open('1,200', parse_open('The answer is 1200.'))
    assert not score_open('1200', parse_open('The answer is 17.'))
    print('Parser self-test passed: MC, fallback, refusal, and numeric open answers')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    if args.self_test:
        self_test()
    else:
        p.print_help()

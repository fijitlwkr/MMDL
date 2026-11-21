"""Apply PLAN_C1 section 5; reuse the frozen D3/SD1 input/reward/stratum checks."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from sd1_select import DEV, SPLIT, SOURCE, STRATUM, metrics, read_rows, run_reward, sha, stratum, validate_raw, write_json

NAMES = ('M0', 'D3-e1', 'C1-h', 'C1-f')


def select(values):
    assert set(values) == set(NAMES)
    for value in values.values():
        assert value['responses'] == 1200 and value['by_stratum'][STRATUM]['responses'] == 632
    assert values['M0']['correct'] == 861 and values['M0']['by_stratum'][STRATUM]['correct'] == 594
    assert values['D3-e1']['correct'] == 882
    eligible, excluded = [], {}
    for name in NAMES[2:]:
        reasons = []
        if values[name]['correct'] < 861:
            reasons.append('overall correct < 861')
        if values[name]['by_stratum'][STRATUM]['correct'] <= 581:
            reasons.append('protected correct <= 581')
        if reasons:
            excluded[name] = reasons
        else:
            eligible.append(name)
    provisional = None
    if len(eligible) == 1:
        provisional = eligible[0]
    elif len(eligible) == 2:
        difference = abs(values['C1-h']['correct'] - values['C1-f']['correct'])
        provisional = 'C1-h' if difference <= 5 else max(eligible, key=lambda n: values[n]['correct'])
    chosen = provisional if provisional and values[provisional]['correct'] > 882 else None
    return {'selected': chosen, 'provisional_candidate': provisional, 'eligible': eligible, 'excluded': excluded,
            'strictly_exceeds_D3_e1': bool(chosen), 'tie_tolerance_correct_count': 5,
            'other_metrics_used_for_selection': False, 'validation_started': False,
            'reason': 'Selected candidate exceeds 882' if chosen else 'No eligible selected candidate strictly exceeds 882'}


def self_test(out):
    layers = {str(i): STRATUM if i < 158 else 'target' for i in range(300)}
    def fake(total, protected):
        assert 0 <= total - protected <= 568
        rows = [{'row':str(i//4), 'reward':int(i < protected if i < 632 else i-632 < total-protected),
                 'finish_reason':'stop', 'output_tokens':10, 'marker_count':0} for i in range(1200)]
        return metrics(rows, layers)
    cases = [('full_clearly_higher',(890,594),(920,594),'C1-f'),
             ('within_five_prefers_half',(895,594),(900,594),'C1-h'),
             ('equal_to_882_is_not_enough',(882,594),(880,594),None),
             ('protected_rejects_best',(890,582),(920,581),'C1-h'),
             ('both_below_M0',(860,594),(850,594),None),
             ('six_difference_prefers_full',(890,594),(896,594),'C1-f'),
             ('tie_priority_precedes_882_gate',(881,594),(886,594),None),
             ('582_protected_boundary_passes',(883,582),(900,581),'C1-h')]
    checks = []
    for name, h, f, expected in cases:
        values = {'M0':fake(861,594), 'D3-e1':fake(882,594), 'C1-h':fake(*h), 'C1-f':fake(*f)}
        actual = select(values)
        assert actual['selected'] == expected, (name,actual)
        checks.append({'case':name,'h':h,'f':f,'expected':expected,'actual':actual,'passed':True})
    assert not out.exists()
    write_json(out, {'status':'PASS','synthetic':True,'real_C1_measurements_read':False,'tests':checks})
    print('C1_SELECTION_SYNTHETIC_PASS',len(checks),flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--self-test',action='store_true')
    ap.add_argument('--m0',type=Path)
    ap.add_argument('--d3',type=Path)
    ap.add_argument('--half',type=Path)
    ap.add_argument('--full',type=Path)
    ap.add_argument('--out',type=Path,required=True)
    args = ap.parse_args()
    assert not args.out.exists()
    if args.self_test:
        assert not any((args.m0,args.d3,args.half,args.full))
        self_test(args.out)
        return
    if not all((args.m0,args.d3,args.half,args.full)):
        ap.error('Provide all four frozen raw paths')
    items = {r['row']:r for r in read_rows(DEV)}
    split = json.loads(SPLIT.read_bytes())
    assert len(items)==300 and set(items)==set(split['development_rows'])
    groups = {r['row']:r for r in json.loads((SOURCE/'groups.json').read_bytes())['groups']}
    layers = {row:stratum(groups[row]) for row in items}
    assert sum(v==STRATUM for v in layers.values())==158
    score, identity = run_reward(True)
    paths = dict(zip(NAMES,(args.m0,args.d3,args.half,args.full)))
    values, manifest_identity = {}, None
    for name,path in paths.items():
        manifest = json.loads((path.parent/'manifest.json').read_bytes())
        assert manifest['k']==4 and manifest['repeat_start']==4
        assert manifest['questions_sha256']==sha(DEV)
        assert manifest['reward_sha256']==identity['reward_sha256']
        common = {k:v for k,v in manifest.items() if k!='model_path'}
        if manifest_identity is None:
            manifest_identity=common
        else:
            assert manifest_identity==common,(name,'generation manifest conditions differ')
        value = validate_raw(path,items,layers,score)
        rows = read_rows(path)
        correct_per_row = Counter()
        for row in rows:
            correct_per_row[row['row']] += row['reward']
        value['question_outcomes'] = {'all_correct':sum(n==4 for n in correct_per_row.values()),
                                      'mixed':sum(1<=n<=3 for n in correct_per_row.values()),
                                      'all_wrong':sum(n==0 for n in correct_per_row.values())}
        assert sum(value['question_outcomes'].values())==300
        value['length_count']=sum(r['finish_reason']=='length' for r in rows)
        value['direction_overuse_count']=sum(r['marker_count']>=21 for r in rows)
        value['output_tokens_total']=sum(r['output_tokens'] for r in rows)
        values[name]=value
    result = {'measurements':values,'selection':select(values),'reward':identity,
              'development_sha256':sha(DEV),'raw_sha256':{n:sha(p) for n,p in paths.items()},
              'baselines_reused':True,'baseline_current_GPU_same':False,'validation_started':False}
    write_json(args.out,result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()

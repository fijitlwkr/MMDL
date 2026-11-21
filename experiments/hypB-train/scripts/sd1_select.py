"""Apply the fixed five-candidate D3/SD1 joint selection to frozen development raws."""
import argparse,json
from pathlib import Path
from classify_answers import ROOT,read_rows,write_json
from d3_prepare import DEV,SPLIT,SOURCE,stratum
from d3_select import metrics,validate_raw
from sample_m0 import run_reward,sha

PRIORITY=('D3-e1','D3-e2','SD1-a','SD1-b','SD1-c')
STRATUM='excluded_correct_4'
def select(values):
    assert set(values)=={'M0',*PRIORITY}
    baseline=values['M0'];assert baseline['responses']==1200 and baseline['by_stratum'][STRATUM]['responses']==632
    eligible=[];excluded={};protection={}
    for name in PRIORITY:
        item=values[name];assert item['responses']==1200 and item['by_stratum'][STRATUM]['responses']==632
        loss=baseline['by_stratum'][STRATUM]['correct']-item['by_stratum'][STRATUM]['correct']
        guard=loss*50<=632
        protection[name]={'delta_pp':-100*loss/632,'passed':guard}
        reasons=[]
        if item['correct']<baseline['correct']:reasons.append('overall reward below M0')
        if not guard:reasons.append('all-correct stratum drops by more than 2 percentage points')
        if reasons:excluded[name]=reasons
        else:eligible.append(name)
    best=max((values[name]['correct'] for name in eligible),default=None)
    near=[name for name in eligible if (best-values[name]['correct'])*200<1200] if eligible else []
    chosen=next((name for name in PRIORITY if name in near),None)
    return {'selected':chosen,'eligible':eligible,'excluded':excluded,'protection':protection,'best_correct':best,
            'within_strict_half_percentage_point_of_best':near,'priority_order':list(PRIORITY),
            'other_metrics_used_for_selection':False,'reason':'No eligible candidate' if chosen is None else 'First priority among eligible candidates within <0.5pp of the highest overall mean'}
def self_test():
    cases=[
      ('highest_of_five',[(840,600),(850,600),(860,600),(870,600),(900,600)],'SD1-c'),
      ('priority_within_half_pp',[(855,600),(856,600),(857,600),(858,600),(860,600)],'D3-e1'),
      ('protection_rejects_highest',[(900,587),(799,600),(850,600),(799,600),(799,600)],'SD1-a'),
      ('all_rejected',[(799,600),(799,600),(900,587),(799,600),(799,600)],None),
      ('exact_half_pp_excluded_from_tie',[(854,600),(855,600),(852,600),(853,600),(860,600)],'D3-e2'),
      ('twelve_protected_losses_allowed',[(900,588),(850,600),(850,600),(850,600),(850,600)],'D3-e1')]
    layers={str(n):STRATUM if n<158 else 'excluded_correct_0' if n<191 else 'retain' if n<236 else 'target' for n in range(300)}
    def fake(total,protected):
        assert 0<=total-protected<=568
        rows=[{'row':str(n//4),'reward':int(n<protected if n<632 else n-632<total-protected),
               'finish_reason':'stop','output_tokens':10,'marker_count':0} for n in range(1200)]
        return metrics(rows,layers)
    tests=[]
    for name,counts,expected in cases:
        values={'M0':fake(800,600),**{key:fake(*count) for key,count in zip(PRIORITY,counts,strict=True)}}
        result=select(values);assert result['selected']==expected,(name,result)
        tests.append({'case':name,'expected':expected,'selection':result,'passed':True,'counts':dict(zip(PRIORITY,counts))})
    out=ROOT/'reports/d3sd1_dev/joint_selection_self_test.json'
    assert not out.exists();write_json(out,{'status':'PASS','synthetic':True,'tests':tests})
    print('JOINT_SELECTION_SYNTHETIC_PASS',len(tests))
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-test',action='store_true')
    p.add_argument('--reference',type=Path);p.add_argument('--candidate',action='append',default=[],metavar='NAME=RAW')
    p.add_argument('--out',type=Path);args=p.parse_args()
    if args.self_test:
        assert not args.reference and not args.candidate and not args.out;self_test();return
    if not args.reference or len(args.candidate)!=5 or not args.out:p.error('Provide M0 --reference, five named --candidate raws, and a new --out')
    if args.out.exists():raise FileExistsError(args.out)
    candidates={}
    for entry in args.candidate:
        name,sep,path=entry.partition('=')
        if not sep or name not in PRIORITY or name in candidates:p.error('Expected unique fixed candidate names')
        candidates[name]=Path(path)
    assert set(candidates)==set(PRIORITY)
    items={r['row']:r for r in read_rows(DEV)};split=json.loads(SPLIT.read_bytes())
    assert len(items)==300 and set(items)==set(split['development_rows'])
    groups={r['row']:r for r in json.loads((SOURCE/'groups.json').read_bytes())['groups']}
    layers={row:stratum(groups[row]) for row in items};score,identity=run_reward(True)
    paths={'M0':args.reference,**{name:candidates[name] for name in PRIORITY}}
    values={name:validate_raw(path,items,layers,score) for name,path in paths.items()}
    result={'measurements':values,'selection':select(values),'reward':identity,'development_sha256':sha(DEV),
            'raw_sha256':{name:sha(path) for name,path in paths.items()}}
    write_json(args.out,result)
    print('model\treward_mean\tprotected_mean\tlength_rate\tmean_output_tokens\tdirection_overuse_rate')
    for name,v in values.items():print(name,v['reward_mean'],v['by_stratum'][STRATUM]['reward_mean'],v['length_rate'],v['mean_output_tokens'],v['direction_overuse_rate'],sep='\t')
    print(json.dumps(result['selection'],ensure_ascii=False))
if __name__=='__main__':main()

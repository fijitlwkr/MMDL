"""E1/E2/holdout messages JSONL → ms-swift 형식({"messages": [...], "images": [...]}).

user content = 이미지 수만큼 "<image>" + 평가 프롬프트 텍스트. Qwen3-VL chat template은 이미지 항목을 텍스트 앞에
구분자 없이 렌더링하므로, ms-swift가 <image>를 vision 토큰으로 바꾸면 원본과 같은 입력이 된다(verify에서 확인).
순서는 원본 JSONL과 같다. 이미지 경로는 원본과 같은 상대 경로(images/...).
"""
import json, sys
from pathlib import Path
D = Path(sys.argv[1])
for name in ['E1_train', 'E2_train', 'holdout_300']:
    out = []
    for line in open(D / f'{name}.jsonl', encoding='utf-8'):
        r = json.loads(line); u, a = r['messages']
        imgs = [c['image'] for c in u['content'] if c['type'] == 'image']
        text = [c['text'] for c in u['content'] if c['type'] == 'text']
        assert len(text) == 1 and '<image>' not in text[0] and [c['type'] for c in u['content']] == ['image'] * len(imgs) + ['text']
        out.append(dict(messages=[dict(role='user', content='<image>' * len(imgs) + text[0]), dict(role='assistant', content=a['content'])], images=imgs))
    (D / f'{name}_swift.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in out), encoding='utf-8')
    print(name, len(out))

"""OpenMedReason 후보 100건 사람 검수 앱 (로컬 전용).

보는 것: 이미지, 질문·보기(영어 + 한글 번역), 정답, 잘라낸 지각 단락(영어 + 번역).
묻는 것 2개:
  image_needed  그림을 봐야만 풀리는 문제인가?                     Y / N / ?
  leak          정답 보기의 핵심 단어가 지각 단락에 글자 그대로 있나? Y / N
                (정답 단어는 화면에서 노란색으로 자동 표시된다. 의학 지식 불필요)
결과: <out-dir>/review_omr.csv (저장 즉시 기록, 다시 열면 이어서).

사용:
  python review_omr.py --out-dir omr_out --port 8791
  (번역 파일 omr_out/review100_ko.json 이 있으면 같이 보여준다)
"""
import argparse
import csv
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

FIELDS = ["cand_id", "type", "image_needed", "note"]
LOCK = threading.Lock()

HTML = """<!doctype html><html lang=ko><meta charset=utf-8><title>OMR 검수</title>
<style>
body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;background:#fafafa;color:#222}
.wrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px;max-width:1500px;margin:auto}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:14px}
img{max-width:100%;max-height:520px;display:block;margin:auto;border:1px solid #eee}
.en{color:#333;white-space:pre-wrap;line-height:1.45}.ko{color:#0b5;white-space:pre-wrap;line-height:1.45;margin-top:4px}
.ko{color:#1a6b3a}.lbl{font-size:12px;color:#888;margin-top:10px;text-transform:uppercase;letter-spacing:.04em}
.top{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0}
.q{margin:10px 0}.q b{display:inline-block;width:260px}
button{padding:6px 12px;margin-right:6px;border:1px solid #bbb;background:#fff;border-radius:6px;cursor:pointer}
button.on{background:#222;color:#fff;border-color:#222}
textarea{width:100%;height:60px;margin-top:8px}
.nav button{font-size:14px}.ans{font-weight:700;color:#b00}
.prog{color:#666;font-size:13px}
mark{background:#ffe066;padding:0 2px}.hint{font-size:12px;color:#777;margin-top:4px}
</style>
<div class=top><div class=nav><button onclick="go(-1)">◀ 이전 (←)</button><button onclick="go(1)">다음 ▶ (→)</button>
<span id=pos></span> <a href="/pairs" style="margin-left:16px">pHash 쌍 검수 →</a></div><div class=prog id=prog></div></div>
<div class=wrap>
 <div class=card><img id=img><div class=lbl>type · cand_id</div><div id=meta></div></div>
 <div class=card>
  <div class=lbl>Question</div><div class=en id=stem></div><div class=ko id=stem_ko></div>
  <div class=lbl>Options</div><div class=en id=opts></div><div class=ko id=opts_ko></div>
  <div class=lbl>Answer</div><div class=ans id=ans></div>
  <div class=lbl>Perception paragraph (학습에 넣을 부분)</div><div class=en id=perc></div><div class=ko id=perc_ko></div>
  <hr>
  <div class=q><b>그림을 봐야만 풀리나? (1/2/3)</b><span id=b_image_needed></span>
   <div class=hint>질문과 보기만 읽고 판단. 1 = 그림 필요(Y), 2 = 글만으로 풀림(N), 3 = 모르겠음. 지각 문장은 참고용이라 안 읽어도 됨.</div></div>
  <textarea id=note placeholder="메모 (선택)"></textarea>
  <div style="margin-top:8px"><button onclick="save(1)">저장하고 다음 (Enter)</button></div>
 </div>
</div>
<script>
let ids=[],i=0,cur=null,rev={};
const OPT={image_needed:['Y','N','?']};
const KEYS={'1':['image_needed','Y'],'2':['image_needed','N'],'3':['image_needed','?']};
async function init(){const r=await (await fetch('/api/list')).json();ids=r.ids;rev=r.reviews;i=ids.findIndex(x=>!rev[x]);if(i<0)i=0;load();}
async function load(){cur=await (await fetch('/api/item?id='+ids[i])).json();
 img.src='/img/'+cur.image_file;meta.textContent=cur.type+' · #'+cur.cand_id+' · omr_row '+cur.omr_row;
 stem.textContent=cur.stem;stem_ko.textContent=cur.ko.stem||'';opts.textContent=cur.options;opts_ko.textContent=cur.ko.options||'';
 ans.textContent=cur.answer+'  —  '+cur.answer_text;perc.innerHTML=hl(cur.perception,cur.answer_words);perc_ko.textContent=cur.ko.perception||'';
 const r=rev[cur.cand_id]||{};note.value=r.note||'';
 for(const k in OPT){const el=document.getElementById('b_'+k);el.innerHTML='';OPT[k].forEach(v=>{const b=document.createElement('button');b.textContent=v;b.className=(r[k]===v)?'on':'';b.onclick=()=>pick(k,v);el.appendChild(b);});}
 pos.textContent=` ${i+1} / ${ids.length}`;const done=Object.keys(rev).length;prog.textContent=`저장됨 ${done} / ${ids.length}`;}
function esc(t){return t.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function hl(text,words){let h=esc(text);words.forEach(w=>{const re=new RegExp('\\\\b('+w+'\\\\w*)','gi');h=h.replace(re,'<mark>$1</mark>');});return h;}
function pick(k,v){rev[cur.cand_id]=Object.assign(rev[cur.cand_id]||{},{[k]:v});load();}
async function save(adv){const r=rev[cur.cand_id]||{};for(const k in OPT){if(!r[k]){alert(k+' 선택 안 됨');return;}}
 r.note=note.value;await fetch('/api/save',{method:'POST',body:JSON.stringify({cand_id:cur.cand_id,type:cur.type,...r})});if(adv)go(1);else load();}
function go(d){i=Math.min(ids.length-1,Math.max(0,i+d));load();}
document.addEventListener('keydown',e=>{if(e.target.tagName==='TEXTAREA')return;if(KEYS[e.key]){pick(...KEYS[e.key]);}else if(e.key==='Enter')save(1);else if(e.key==='ArrowRight')go(1);else if(e.key==='ArrowLeft')go(-1);});
init();
</script></html>"""


STOP = set("the a an of in on at to and or with without is are be by for from this that image images most likely which what".split())


def answer_words(options, letter):
    """정답 보기의 본문과, 지각 단락에서 찾을 핵심 단어(4자 이상, 불용어 제외)."""
    m = re.search(r"(?m)^\s*%s[\.\)]\s*(.+)$" % re.escape(letter), options)
    text = m.group(1).strip() if m else ""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text) if w.lower() not in STOP]
    return text, sorted(set(words), key=len, reverse=True)


PAIRS_HTML = """<!doctype html><html lang=ko><meta charset=utf-8><title>pHash 쌍 검수</title>
<style>
body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;background:#fafafa;color:#222}
.top{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid #ddd;position:sticky;top:0}
.pair{display:grid;grid-template-columns:1fr 1fr 220px;gap:12px;align-items:center;background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin:12px 16px}
.pair img{max-width:100%;max-height:300px;display:block;margin:auto;border:1px solid #eee}
.cap{font-size:12px;color:#666;text-align:center;margin-top:4px}
button{padding:8px 14px;margin:4px;border:1px solid #bbb;background:#fff;border-radius:6px;cursor:pointer;font-size:14px}
button.on{background:#222;color:#fff;border-color:#222}
.done{opacity:.55}
</style>
<div class=top><div><a href="/">← 100건 검수</a> &nbsp; <b>pHash 쌍 검수</b> — 왼쪽(OMR)과 오른쪽(MMMU)이 같은 그림인가?</div><div id=prog></div></div>
<div id=list></div>
<script>
let pairs=[],rev={};
async function init(){const r=await (await fetch('/api/pairs')).json();pairs=r.pairs;rev=r.reviews;render();}
function render(){list.innerHTML='';let done=0;pairs.forEach(p=>{const v=rev[p.cand_id];if(v)done++;
 const d=document.createElement('div');d.className='pair'+(v?' done':'');
 d.innerHTML=`<div><img src="/img/${p.omr_image}"><div class=cap>OMR #${p.cand_id}</div></div>
 <div><img src="/pimg/${p.mmmu_image}"><div class=cap>${p.source} ${p.nearest_mmmu} · 거리 ${p.hamming}</div></div>
 <div><div style="margin-bottom:6px">같은 그림?</div>
 <button class="${v==='Y'?'on':''}" onclick="save('${p.cand_id}','Y')">Y 같다</button>
 <button class="${v==='N'?'on':''}" onclick="save('${p.cand_id}','N')">N 다르다</button></div>`;
 list.appendChild(d);});prog.textContent=`저장됨 ${done} / ${pairs.length}`;}
async function save(id,v){rev[id]=v;await fetch('/api/pairs/save',{method:'POST',body:JSON.stringify({cand_id:id,same_image:v})});render();}
init();
</script></html>"""


class App:
    def __init__(self, out_dir):
        self.out = out_dir
        self.img_dir = os.path.join(out_dir, "images")
        rows = list(csv.DictReader(open(os.path.join(out_dir, "candidates.csv"), encoding="utf-8")))
        self.items = {r["cand_id"]: r for r in rows}
        self.ids = json.load(open(os.path.join(out_dir, "review_ids.json")))
        ko_path = os.path.join(out_dir, "review100_ko.json")
        self.ko = {str(x["cand_id"]): x for x in json.load(open(ko_path, encoding="utf-8"))} if os.path.exists(ko_path) else {}
        self.pairs_dir = os.path.join(out_dir, "phash_review")
        pp = os.path.join(self.pairs_dir, "pairs.csv")
        self.pairs = list(csv.DictReader(open(pp, encoding="utf-8"))) if os.path.exists(pp) else []
        self.pairs_review_path = os.path.join(self.pairs_dir, "pairs_review.csv")
        self.pairs_rev = {}
        if os.path.exists(self.pairs_review_path):
            for r in csv.DictReader(open(self.pairs_review_path, encoding="utf-8")):
                self.pairs_rev[r["cand_id"]] = r["same_image"]
        self.review_path = os.path.join(out_dir, "review_omr.csv")
        self.reviews = {}
        if os.path.exists(self.review_path):
            for r in csv.DictReader(open(self.review_path, encoding="utf-8")):
                self.reviews[r["cand_id"]] = {k: r.get(k, "") for k in FIELDS}

    def save(self, rec):
        with LOCK:
            self.reviews[rec["cand_id"]] = {k: rec.get(k, "") for k in FIELDS}
            with open(self.review_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                w.writeheader()
                for cid in self.ids:
                    if cid in self.reviews:
                        w.writerow(self.reviews[cid])


    def save_pair(self, cand_id, v):
        with LOCK:
            self.pairs_rev[cand_id] = v
            with open(self.pairs_review_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["cand_id", "omr_image", "hamming", "nearest_mmmu", "same_image"])
                for p in self.pairs:
                    if p["cand_id"] in self.pairs_rev:
                        w.writerow([p["cand_id"], p["omr_image"], p["hamming"], p["nearest_mmmu"], self.pairs_rev[p["cand_id"]]])


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, ctype="application/json"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self._send(HTML, "text/html; charset=utf-8")
            if u.path == "/pairs":
                return self._send(PAIRS_HTML, "text/html; charset=utf-8")
            if u.path == "/api/pairs":
                pp = os.path.join(app.pairs_dir, "pairs.csv")  # 매번 다시 읽어서 목록이 바뀌어도 재시작 불필요
                app.pairs = list(csv.DictReader(open(pp, encoding="utf-8"))) if os.path.exists(pp) else []
                return self._send(json.dumps({"pairs": app.pairs, "reviews": app.pairs_rev}))
            if u.path.startswith("/pimg/"):
                p = os.path.join(app.pairs_dir, os.path.basename(u.path))
                return self._send(open(p, "rb").read(), "image/jpeg")
            if u.path == "/api/list":
                return self._send(json.dumps({"ids": app.ids, "reviews": app.reviews}))
            if u.path == "/api/item":
                cid = parse_qs(u.query)["id"][0]
                it = dict(app.items[cid])
                it["ko"] = app.ko.get(cid, {})
                it["answer_text"], it["answer_words"] = answer_words(it["options"], it["answer"])
                return self._send(json.dumps(it, ensure_ascii=False))
            if u.path.startswith("/img/"):
                p = os.path.join(app.img_dir, os.path.basename(u.path))
                return self._send(open(p, "rb").read(), "image/jpeg")
            self.send_error(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            rec = json.loads(self.rfile.read(n))
            if self.path == "/api/pairs/save":
                app.save_pair(rec["cand_id"], rec["same_image"])
            else:
                app.save(rec)
            self._send("{}")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동 열기 끔")
    a = ap.parse_args()
    app = App(a.out_dir)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app))
    url = f"http://127.0.0.1:{a.port}/"
    print("open", url, "| Ctrl+C to stop")
    if not a.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

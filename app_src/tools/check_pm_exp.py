"""科目Bの独自解説（app_src/data/pm_exp/<試験ID>.json）の形式を確かめる。

  python app_src/tools/check_pm_exp.py 04_haru 04_aki

形式：{"04_haru-pm1": [{"s": "", "t": "導入"}, {"s": "設問1", "t": "本文\\n次の段落"}, ...], ...}
- 問題IDは data/pm.json にあるもの
- 解答例（pm.json の rows）にある設問がすべて解説にあること、余分な設問が無いこと
- 本文が空でないこと
"""
import json, re, sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
pm = {q["id"]: q for q in json.loads((DATA / "pm.json").read_text(encoding="utf-8"))}
ok = True
for eid in sys.argv[1:]:
    f = DATA / "pm_exp" / f"{eid}.json"
    if not f.exists():
        print(f"{eid}: ファイルがありません ({f})"); ok = False; continue
    d = json.loads(f.read_text(encoding="utf-8"))
    want_ids = [k for k in pm if pm[k]["eid"] == eid]
    missing = [k for k in want_ids if k not in d]
    extra = [k for k in d if k not in want_ids]
    if missing or extra:
        print(f"{eid}: 足りない問題 {missing} / 余分な問題 {extra}"); ok = False
    for k, secs in d.items():
        if k not in pm:
            continue
        want = sorted({r["s"] for r in pm[k]["rows"]}, key=lambda s: int(re.sub(r"\D", "", s) or 0))
        got = [x.get("s", "") for x in secs if x.get("s")]
        if got != want:
            print(f"{k}: 設問が解答例と合いません 解説={got} 解答例={want}"); ok = False
        if any(not x.get("t", "").strip() for x in secs):
            print(f"{k}: 本文が空の要素があります"); ok = False
    print(f"{eid}: {len(d)}/{len(want_ids)}問, {sum(len(x['t']) for v in d.values() for x in v)}字")
print("OK" if ok else "NG")
sys.exit(0 if ok else 1)

"""精度確認用：無作為に選んだ過去問について、元のPDFの該当ページ画像と、アプリでの表示テキストを並べて書き出す。
目で見比べて「問題文・選択肢・正解・解説に崩れがあるか」を数える（改良前後で同じ問題を使う）。

使い方: python app_src/tools/gt_sample.py <出力先フォルダ> [件数] [シード]
"""
import json, random, re, sys
from pathlib import Path
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 20
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 7
SCRATCH = Path(sys.argv[4]) if len(sys.argv) > 4 else None   # 秋期のIPA問題PDFの置き場所

html = (ROOT / "AP科目A対策.html").read_text(encoding="utf-8")
DATA = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
QS = [q for q in DATA["questions"] if q["eid"]]
spring = [q for q in QS if not q["eid"].endswith("aki") or q["eid"] == "01_aki"]
autumn = [q for q in QS if q["eid"].endswith("aki") and q["eid"] != "01_aki"]
rng = random.Random(SEED)
sample = rng.sample(spring, N // 2) + rng.sample(autumn, N - N // 2)

BOOK = {"25_haru": "25年春", "26_haru": "26年春", "27_haru": "27年春", "28_haru": "28年春", "29_haru": "29年春", "30_haru": "30年春",
        "31_haru": "31年春", "01_aki": "元年秋", "03_haru": "徹底攻略 応用情報技術者 令和4年度"}
IPA = {"26_aki": "2014h26a", "27_aki": "2015h27a", "28_aki": "2016h28a", "29_aki": "2017h29a", "30_aki": "2018h30a", "02_aki": "2020r02o", "03_aki": "2021r03a"}

def find_page(doc, no, start):
    pat = re.compile(rf"(^|\n)\s*問\s*{no}(?!\d)")
    for i in range(start, doc.page_count):
        t = doc[i].get_text()
        if pat.search(t) and ("《" not in t and "≪" not in t and "解答" not in t[:200]):
            return i
    return None

for q in sample:
    eid, no = q["eid"], q["no"]
    if eid in BOOK:
        doc = pymupdf.open(ROOT / "応用情報" / f"{BOOK[eid]}.pdf")
        start = 640 if eid == "03_haru" else 1
        pno = find_page(doc, no, start)
    else:
        doc = pymupdf.open(SCRATCH / "ipa" / f"{IPA[eid]}_ap_am_qs.pdf")
        ocr = json.loads((SCRATCH / "ipa" / f"{IPA[eid]}.json").read_text(encoding="utf-8-sig"))
        pno = None
        for p in ocr:
            for l in (p.get("lines") or []):
                ws = l["words"] if isinstance(l["words"], list) else [l["words"]]
                if re.match(rf"^[問間]\s*{no}(?!\d)", "".join(w["t"] for w in ws)) and p["page"] > 2:
                    pno = p["page"] - 1; break
            if pno is not None: break
    if pno is None:
        print("ページが見つからない:", q["id"]); continue
    doc[pno].get_pixmap(dpi=90 if eid in BOOK else 70).save(OUT / f"{q['id']}.png")
    if pno + 1 < doc.page_count and eid not in BOOK:
        doc[pno + 1].get_pixmap(dpi=70).save(OUT / f"{q['id']}_next.png")
    txt = f"{q['id']} 正解:{'アイウエ'[q['a']]}\n{q['q']}\n" + "\n".join(f"{'アイウエ'[i]} {c}" for i, c in enumerate(q["c"])) + "\n--- 解説\n" + "\n".join(q["e"])
    (OUT / f"{q['id']}.txt").write_text(txt, encoding="utf-8")
print("出力:", [q["id"] for q in sample])

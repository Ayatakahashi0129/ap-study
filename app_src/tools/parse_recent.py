"""令和4年度春期〜令和7年度秋期の午前問題を作る（解説PDFが無いので、解説は「正解は○」のみ）。

- 問題文・選択肢: IPA公開の問題PDFを Windows OCR した結果（ocr.ps1 の JSON, 応用情報/ipa_new/ocr/）
- 正解・分野    : IPA公開の解答例PDF（応用情報/ipa_new/*_ap_am_ans.pdf）
- 分類         : parse_autumn と同じく、春期の分類付き問題を手本に推定
- 図・表があってOCRで読めない問題は、問題PDFのその部分を画像にして img/q/<id>.png に置く

使い方: python parse_recent.py <scratchpad>   （<scratchpad> は parse_autumn と同じ。用語辞書に秋期の解説を使う）
出力: app_src/data/recent.json, img/q/*.png
"""
import json, re, sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse_autumn as pa  # noqa: E402  （BASE は sys.argv[1] から読まれる）

SRC = Path(__file__).resolve().parent.parent
ROOT = SRC.parent
DIR = ROOT / "応用情報" / "ipa_new"
IMG = ROOT / "img" / "q"

EXAMS = [  # (IPAファイル名, id, 表示名)
    ("2022r04h", "04_haru", "令和4年春期"), ("2022r04a", "04_aki", "令和4年秋期"),
    ("2023r05h", "05_haru", "令和5年春期"), ("2023r05a", "05_aki", "令和5年秋期"),
    ("2024r06h", "06_haru", "令和6年春期"), ("2024r06a", "06_aki", "令和6年秋期"),
    ("2025r07h", "07_haru", "令和7年春期"), ("2025r07a", "07_aki", "令和7年秋期"),
]
OCR_W = 2400   # ocr.ps1 の描画幅（座標の単位）


def fix(s):
    """parse_autumn.fix_text の後に残る読み違い"""
    s = re.sub(r"ニ(?=つ|人|重|分|進|次|回|度|台|個|者|値|乗|層|項)", "二", s)
    s = re.sub(r"(?<=及)ひ", "び", s)
    s = re.sub(r"(?<=[一-龥])ひ(?=[，。])", "び", s)
    return s


def answers(code):
    t = "".join(p.get_text() for p in fitz.open(DIR / f"{code}_ap_am_ans.pdf"))
    t = t.translate(pa.Z2H)
    if not t.strip():   # 令和4年春は画像だけのPDF。テンプレート照合で読んだ結果（応用情報/ipa_new/<code>_ans.json）を使う
        return {int(n): v for n, v in json.loads((DIR / f"{code}_ans.json").read_text()).items()}
    return {int(n): pa.KANA.index(k) for n, k in re.findall(r"問\s*(\d+)\s+([アイウエ])\s", t)}


def heads(rows):
    """各問の見出し行の位置（ページ, y）。split_questions と同じ規則で探す。"""
    # 表紙・表記ルールのページ（年度により2〜3ページ）を飛ばし、「問1から問50までは…」の行から始める
    st = next((i for i, r in enumerate(rows) if re.search(r"問\s*1\s*から\s*問|テクノロジ系の問題です", r["toks"][0])), 0)
    rows = rows[st:]
    out, n = {}, 1
    for r in rows:
        first = r["toks"][0]
        if re.search(r"問\s*\d+\s*から\s*問|系の問題です", first):
            continue
        hit = None
        for k in range(n, min(n + 3, 81)):
            if pa.num_pat(k).match(first):
                hit = k
                break
        if not hit and n <= 80 and r["x"] < 440 and re.match(r"^問(?![題い合])", first):
            hit = n
        if hit:
            out[hit] = (r["page"], r["y"])
            n = hit + 1
    # 見出しがOCRで落ちた問は、前後の見出しの間で上の行との間隔がいちばん広い行（問と問の間の余白）を見出しとみなす
    body = [r for r in rows if not re.fullmatch(r"[-－‐\s\dニロ]{1,6}", r["toks"][0])]
    for n in range(1, 81):
        if n in out:
            continue
        lo = out.get(n - 1, (3, -1)); hi = out.get(n + 1, (99, 0))
        best, prev = None, None
        for r in body:
            key = (r["page"], r["y"])
            if lo < key < hi and key != lo and not re.match(r"^[アイウエ工ェ](\s|$)", r["toks"][0]) and not re.search(r"系の問題です|から\s*問", r["toks"][0]):
                gap = r["y"] - prev["y"] if prev and prev["page"] == r["page"] else 0
                if prev and re.search(r"系の問題です|から\s*問", prev["toks"][0]):
                    gap = 1e4
                if best is None or gap > best[0]:
                    best = (gap, key)
            if key >= lo:
                prev = r
        if best:
            out[n] = best[1]
    return out


def load_rows_y(path):
    """pa.load_rows と同じだが、行の y 座標も残す。"""
    pages = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = []
    for p in pages:
        ls = p.get("lines") or []
        if isinstance(ls, dict):
            ls = [ls]
        for l in ls:
            ws = l["words"] if isinstance(l["words"], list) else [l["words"]]
            rows.append({"page": p["page"], "y": l["y"], "x": l["x"], "toks": [pa.join_words(ws)]})
    rows.sort(key=lambda r: (r["page"], r["y"], r["x"]))
    return rows


def crop(pdf, code, eid, n, hd, pages_y):
    """問 n の見出しから次の問の見出し（またはページ末）までを画像にする。ページをまたぐときは縦につなぐ。"""
    from PIL import Image
    p0, y0 = hd[n]
    p1, y1 = hd.get(n + 1, (p0, None))
    scale = 1.6
    parts = []
    for pg in range(p0, (p1 if y1 is not None else p0) + 1):
        page = pdf[pg - 1]
        k = page.rect.width / OCR_W
        top = (y0 - 30) * k if pg == p0 else pages_y[pg][0] * k - 10
        bot = (y1 - 30) * k if (pg == p1 and y1 is not None) else page.rect.height * 0.925   # ページ番号の少し上まで（余白は後で詰める）
        if bot - top < 20:
            continue
        clip = fitz.Rect(page.rect.width * 0.07, max(0, top), page.rect.width * 0.95, min(page.rect.height, bot))
        pix = page.get_pixmap(clip=clip, matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY)
        parts.append(Image.frombytes("L", (pix.width, pix.height), pix.samples))
    if not parts:
        return None
    w = max(p.width for p in parts)
    im = Image.new("L", (w, sum(p.height for p in parts)), 255)
    y = 0
    for p in parts:
        im.paste(p, (0, y)); y += p.height
    # 白い余白を詰め、16色に減色して軽くする
    from PIL import ImageOps
    bbox = ImageOps.invert(im).getbbox()
    if bbox:
        im = im.crop((max(0, bbox[0] - 8), max(0, bbox[1] - 8), min(w, bbox[2] + 8), min(im.height, bbox[3] + 8)))
    im = im.quantize(16)
    IMG.mkdir(parents=True, exist_ok=True)
    name = f"{eid}-{n}.png"
    im.save(IMG / name, optimize=True)
    return f"img/q/{name}"


def main():
    pa.VOCAB = pa.build_vocab()
    vecs, idf = pa.train()
    allq, report = [], []
    for code, eid, label in EXAMS:
        rows = pa.load_rows(DIR / "ocr" / f"{code}.json")
        qb = pa.split_questions(rows)
        rowsy = load_rows_y(DIR / "ocr" / f"{code}.json")
        hd = heads(rowsy)
        # ページごとの本文の上端・下端（ページ番号を除く）
        pages_y = {}
        for r in rowsy:
            if re.fullmatch(r"[-－‐\s\d]{1,6}", r["toks"][0]):
                continue
            a, b = pages_y.get(r["page"], (1e9, 0))
            pages_y[r["page"]] = (min(a, r["y"]), max(b, r["y"] + 40))
        pdf = fitz.open(DIR / f"{code}_ap_am_qs.pdf")
        ans = answers(code)
        items, stat = [], Counter()
        for n in range(1, 81):
            field = "T" if n <= 50 else ("M" if n <= 60 else "S")
            it = {"id": f"{eid}-{n}", "exam": label, "eid": eid, "no": n, "field": field, "ans": ans.get(n),
                  "exp": [], "q": "", "c": ["", "", "", ""], "flags": []}
            if n in qb:
                stem, cs = pa.build_question(qb[n])
                if stem is None:
                    it["flags"].append("nochoice")
                else:
                    it["q"], it["c"] = fix(pa.VOCAB.fix(stem)), [fix(pa.VOCAB.fix(c)) for c in cs]
                    if pa.FIG.search(stem):
                        it["flags"].append("fig")
                    if any(len(c) == 0 for c in cs) or any(len(c) > 170 for c in cs):
                        it["flags"].append("choice")
                    junk = re.findall(r"[■□●▲◆【】|｜\\_~^`]|[A-Za-z]{1,2}\d[A-Za-z]|(?<![A-Za-z])[a-z](?![A-Za-z])", stem + "".join(cs))
                    if len(junk) >= 2:
                        it["flags"].append("junk")
            else:
                it["flags"].append("noq")
            if it["ans"] is None:
                it["flags"].append("noans")
            first = re.split(r"。", it["q"])[0] if it["q"] else ""
            it["title"] = re.sub(r"(に関する記述|の説明|の特徴)?(として|のうち)?，?(最も)?(適切|適切でない)なものはどれか$|はどれか$", "", first)[:32]
            # 全問の画像を作る。OCRで読めない問題（図・表・選択肢の切り出し失敗）は画像だけで出し（imgonly），
            # 文字で出す問題も「問題冊子の画像で確認」から原本を見られるようにする（「図のシステムA，B」のように図の語が無い問題もあるため）
            if n in hd and it["ans"] is not None:
                it["img"] = crop(pdf, code, eid, n, hd, pages_y)
            it["imgonly"] = bool(it["flags"])
            it["ok"] = it["ans"] is not None and (not it["flags"] or bool(it.get("img")))
            stat["text" if not it["flags"] else ("img" if it.get("img") else it["flags"][0])] += 1
            items.append(it)
        # 分類には、選択肢を切り出せなかった問題もOCRの文字をそのまま使う
        keep = {it["id"]: it["q"] for it in items}
        for it in items:
            if not it["q"] and it["no"] in qb:
                it["q"] = "".join(t for r in qb[it["no"]] for t in r["toks"])
        pa.classify(items, vecs, idf)
        for it in items:
            it["q"] = keep[it["id"]]
        allq += items
        report.append(f"{label}: 見出し{len(hd)} 解答{len(ans)} " + " ".join(f"{k}={v}" for k, v in sorted(stat.items())))
    (SRC / "data/recent.json").write_text(json.dumps(allq, ensure_ascii=False, indent=0), encoding="utf-8")
    print("\n".join(report))
    print("採用:", sum(x["ok"] for x in allq), "/", len(allq))


if __name__ == "__main__":
    main()

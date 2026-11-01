"""科目B（午後）の問題を、IPA公開の午後問題冊子・解答例から作る。

入力（応用情報/ipa_pm/ … Gitに入れない）
- <code>_ap_pm_qs.pdf   問題冊子（文字データの無い画像PDF）
- <code>_ap_pm_ans.pdf  解答例（表になっている文字PDF）
- ocr/<code>.json       問題冊子を ocr.ps1 で読んだ結果（問題の区切りと問題一覧の分野・テーマに使う）

出力
- img/pm/<eid>/<page>.webp  問題冊子のページ画像（余白を切り落とした白黒）
- app_src/data/pm.json      問題ごとの分野・テーマ・ページ・出題趣旨・設問と解答例
"""
import io, json, re, sys, unicodedata
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app_src"
DIR = ROOT / "応用情報" / "ipa_pm"

# 冊子のファイル名 → アプリの試験ID・表示名
EXAMS = [
    ("2013h25h", "25_haru", "平成25年春期"), ("2014h26h", "26_haru", "平成26年春期"),
    ("2015h27h", "27_haru", "平成27年春期"), ("2016h28h", "28_haru", "平成28年春期"),
    ("2017h29h", "29_haru", "平成29年春期"), ("2018h30h", "30_haru", "平成30年春期"),
    ("2019h31h", "31_haru", "平成31年春期"), ("2019r01a", "01_aki", "令和元年秋期"),
    ("2021r03h", "03_haru", "令和3年春期"),
    ("2022r04h", "04_haru", "令和4年春期"), ("2022r04a", "04_aki", "令和4年秋期"),
    ("2023r05h", "05_haru", "令和5年春期"), ("2023r05a", "05_aki", "令和5年秋期"),
    ("2024r06h", "06_haru", "令和6年春期"), ("2024r06a", "06_aki", "令和6年秋期"),
    ("2025r07h", "07_haru", "令和7年春期"), ("2025r07a", "07_aki", "令和7年秋期"),
]
# OCRで問題の書き出しを拾えなかったページ（問番号 → 開始ページ）
START_FIX = {"2022r04a": {6: 32}}
FIELDS = ["情報セキュリティ", "経営戦略", "情報戦略", "プログラミング", "システムアーキテクチャ", "ネットワーク", "データベース",
          "組込みシステム開発", "情報システム開発", "プロジェクトマネジメント", "ITサービスマネジメント", "サービスマネジメント", "システム監査"]
# 問題一覧のOCRでよく出る読み違い
OCR_FIX = [("サーピス", "サービス"), ("工ッジ", "エッジ"), ("工ラー", "エラー"), ("ロポット", "ロボット"), ("オプジェクト", "オブジェクト"),
           ("ポード", "ボード"), ("ニつ", "二つ"), ("projectManagement", "Project Management"), ("(", "（"), (")", "）")]
# OCRで崩れたテーマの手直し（問題ID → テーマ。分野も崩れたものは (分野, テーマ)）。冊子の問題一覧と見比べて直した
THEME_FIX = {
    "25_haru-pm6": "テキストマイニングツールを活用したシステムへの機能追加における設計と実装",
    "25_haru-pm8": "プロビジョニングシステムの設計",
    "25_haru-pm10": "EVM（Earned Value Management）を用いたプロジェクト管理",
    "26_haru-pm5": "サブネットを活用したファイルの保護対策",
    "26_haru-pm6": "旅客船Web予約システムの構築",
    "27_haru-pm2": "ブランド戦略",
    "27_haru-pm3": "データ圧縮の前処理として用いられるBlock-sorting",
    "27_haru-pm7": "自動車用衝突被害軽減ブレーキシステム",
    "28_haru-pm4": "冗長構成をもつネットワーク",
    "29_haru-pm6": "稟議申請システム",
    "29_haru-pm10": ("サービスマネジメント", "サービスマネジメントにおけるマネジメントプロセスとサービスデスクの運用"),
    "30_haru-pm7": "児童の見守り機能付き防犯ブザー",
    "31_haru-pm11": "RPA（Robotic Process Automation）の監査",
    "01_aki-pm3": "ニューラルネットワーク",
    "03_haru-pm4": "IoT技術を活用した駐車場管理システム",
    "03_haru-pm9": "プロジェクトのコスト見積り",
    "04_haru-pm1": "通信販売サイトのセキュリティインシデント対応",
    "06_haru-pm4": "CRM（Customer Relationship Management）システムの改修",
    "07_haru-pm9": "CCPM（Critical Chain Project Management）を用いたプロジェクトのスケジュール管理",
    "07_aki-pm3": "二つの列の最長共通部分列（Longest Common Subsequence）の長さを求めるアルゴリズム",
    "07_aki-pm9": "ソフトウェア開発モデルが混在するプロジェクトのマネジメント",
    "07_aki-pm10": ("サービスマネジメント", "社内手続を扱うサービスデスク"),
}
# 冊子の前に綴じられた正誤表（冊子 → (ページ, 対象の問番号)）。横向きなので回して画像にする
ERRATA = {"2017h29h": (3, 2)}
IMG_W = 1100

N = lambda s: unicodedata.normalize("NFKC", s)
line_text = lambda l: N("".join(w["t"] for w in l["words"]))


def segment(code, pages):
    """問題ごとのページ範囲。問題の書き出し（「問N」「…に関する次の記述を読んで」）で区切り、メモ用紙は除く。"""
    starts, memo = set(), set()
    for p in pages:
        ls = sorted(p["lines"], key=lambda l: l["y"])
        allt = re.sub(r"[\W_]", "", "".join(line_text(l) for l in ls))
        if allt in ("", "メモ用紙") or ("メモ用紙" in allt and len(ls) <= 4):
            memo.add(p["page"])
        top = " ".join(line_text(l) for l in ls if l["y"] < 700)
        if "問題一覧" in top:
            continue
        if "次の記述を読んで" in top or any(re.match(r"^問\d{1,2}", line_text(l)) and l["x"] < 400 for l in ls[:6]):
            starts.add(p["page"])
    starts = sorted(starts)
    for no, pg in START_FIX.get(code, {}).items():
        starts.insert(no - 1, pg)
    starts = sorted(set(starts))
    # 最後の問題は、冊子末尾の注意事項の前のメモ用紙まで
    last = max(p["page"] for p in pages)
    while last in memo or last - 1 in memo and last > starts[-1] + 2:
        last -= 1
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] - 1 if i + 1 < len(starts) else last
        out.append([pg for pg in range(s, e + 1) if pg not in memo])
    return out


def topic_list(pages):
    """問題一覧のページから、問番号 → (分野, テーマ)。
    「問N」の行を目印にし、ほかの行は縦位置がいちばん近い目印の行に属するとみなす（2行にわたるテーマに対応）。"""
    for p in pages:
        ls = p["lines"]
        if "問題一覧" not in "".join(line_text(l) for l in sorted(ls, key=lambda l: l["y"])[:4]):
            continue
        anchors = []
        for l in ls:
            m = re.match(r"^問\s*(\d{1,2})\s*(.*)$", line_text(l))
            if m and l["x"] < 500:
                anchors.append((l["y"] + l["h"] / 2, int(m.group(1)), l))
        cells = {no: [] for _, no, _ in anchors}
        for l in ls:
            t = line_text(l)
            if re.search(r"問題一覧|出題分野|テーマ|番号|必須|選択|^-?\s*\d+\s*-?$", t):
                continue
            cy = l["y"] + l["h"] / 2
            no = min(anchors, key=lambda a: abs(a[0] - cy))
            if abs(no[0] - cy) < 70:
                cells[no[1]].append(l)
        def fix(t):
            t = re.sub(r"^問\s*\d{1,2}", "", t).replace(" ", "")
            for a, b in OCR_FIX:
                t = t.replace(a, b)
            return t
        res = {}
        for _, no, _ in anchors:
            f, theme = "", ""
            for l in sorted(cells[no], key=lambda l: (l["y"], l["x"])):
                t = fix(line_text(l))
                ff = next((x for x in FIELDS if t.startswith(x)), "")
                if ff and not f:
                    f, t = ff, t[len(ff):]
                theme += t
            res[no] = (f, theme)
        return res
    return {}


def answers(code):
    """解答例PDFの表から、問番号 → {aim: 出題趣旨, rows: [{s: 設問, k: 小問・空欄, a: 解答例, note: 備考}]}"""
    d = pymupdf.open(DIR / f"{code}_ap_pm_ans.pdf")
    res, no, pending_aim = {}, 0, ""
    for page in d:
        # ページ内の「問N」の見出しの位置で、表がどの問題のものかを決める
        heads = [(b[1], int(N(b[4]).strip()[1:])) for b in page.get_text("blocks") if re.fullmatch(r"問\s*\d{1,2}", N(b[4]).strip())]
        for t in page.find_tables().tables:
            rows = t.extract()
            above = [n for y, n in heads if y < t.bbox[1]]
            if above:
                no = above[-1]
            hdr = [N(c or "").strip() for c in rows[0]]
            if "出題趣旨" in hdr:
                body = "".join(N(c or "") for r in rows[1:] for c in r).replace("\n", "").strip()
                res.setdefault(no, {"aim": "", "rows": []})["aim"] = body
                continue
            if "設問" in hdr:
                bi = hdr.index("備考") if "備考" in hdr else len(hdr)
                rows = rows[1:]
            else:      # ページをまたいだ表の続き
                bi = len(rows[0]) - 1
            q = res.setdefault(no, {"aim": "", "rows": []})
            s = q["rows"][-1]["s"] if q["rows"] else ""
            sub = q["rows"][-1]["sub"] if q["rows"] else ""
            for r in rows:
                cells = [N(c or "").strip() for c in r[:bi]]
                note = N(r[bi] or "").strip() if bi < len(r) else ""
                cells = [c for c in cells if c]
                if not cells:
                    continue
                if re.fullmatch(r"設問\s*\d+", cells[0]):
                    s, sub = re.sub(r"\s", "", cells.pop(0)), ""
                if cells and re.fullmatch(r"\(\d+\)", cells[0]):
                    sub = cells.pop(0)
                if not cells:
                    continue
                k = cells.pop(0) if len(cells) >= 2 else ""
                a = "\n".join(cells).replace("\n_ _", "").strip()
                q["rows"].append({"s": s, "sub": sub, "k": k, "a": re.sub(r"[ \t]*\n[ \t]*", "", a) if len(a) > 20 else a, "note": note})
    # 新しい年度は出題趣旨が表ではなく本文なので、文章から取る
    text = N("".join(p.get_text() for p in d))
    for m in re.finditer(r"問\s*(\d{1,2})\s*\n\s*出題趣旨\s*\n(.*?)\n\s*設問\s*\n", text, re.S):
        q = res.get(int(m.group(1)))
        if q is not None and not q["aim"]:
            body = re.sub(r"\d+/\d+\s*\n©\d{4}.*?\n", "", m.group(2))
            q["aim"] = re.sub(r"\s*\n\s*", "", body).strip()
    return res


def comments(code):
    """採点講評PDFから、問番号 → 講評（段落ごとに改行）"""
    d = pymupdf.open(DIR / f"{code}_ap_pm_cmnt.pdf")
    lines = []
    for p in d:
        for l in N(p.get_text()).split("\n"):
            l = l.strip()
            if re.fullmatch(r"\d+/\d+|©.*|.*採点講評|午後試験", l):
                continue
            lines.append(l)
    res, no, buf = {}, 0, []
    def flush():
        if no:
            res[no] = "\n".join(p for p in "".join(buf).split("\x00") if p)
    for l in lines:
        m = re.fullmatch(r"問\s*(\d{1,2})", l)
        if m:
            flush(); no, buf = int(m.group(1)), []
            continue
        if not l:
            continue
        # 「問N では」「設問N」で始まる行は新しい段落
        if re.match(r"(問\s*\d{1,2}\s*では|設問\s*\d)", l) and buf:
            buf.append("\x00")
        buf.append(l)
    flush()
    return res


def page_image(doc, pno, out, rotate=0):
    pg = doc[pno - 1]
    s = IMG_W * 1.15 / pg.rect.width
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(s, s), colorspace=pymupdf.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if rotate:
        im = im.rotate(rotate, expand=True, fillcolor=255)
    box = ImageOps.invert(im).point(lambda v: 255 if v > 40 else 0).getbbox()
    if box:
        pad = 24
        im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
    if im.width > IMG_W:
        im = im.resize((IMG_W, round(im.height * IMG_W / im.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "WEBP", quality=50)


def main():
    only = set(sys.argv[1:])
    out, report = [], []
    for code, eid, src in EXAMS:
        pages = json.load(open(DIR / "ocr" / f"{code}.json", encoding="utf-8-sig"))
        seg, tl, ans, cm = segment(code, pages), topic_list(pages), answers(code), comments(code)
        doc = pymupdf.open(DIR / f"{code}_ap_pm_qs.pdf")
        report.append(f"{eid}: 問題 {len(seg)}  一覧 {len(tl)}  解答例 {len(ans)}")
        todo = lambda path: (not only or eid in only) and (not path.exists() or only)
        def img(pg, name=None, rotate=0):
            path = ROOT / "img" / "pm" / eid / f"{name or pg}.webp"
            if todo(path):
                page_image(doc, pg, path, rotate)
            return f"img/pm/{eid}/{path.name}"
        # 擬似言語の記述形式（令和6年度から冊子に付いた2ページ）は、プログラミングの問題から参照できるようにする
        ref = [p["page"] for p in pages if "擬似言語の記述形式" in "".join(line_text(l) for l in p["lines"][:3])]
        ref = [img(pg, f"ref{pg}") for r in ref[:1] for pg in (r, r + 1)]
        for i, pgs in enumerate(seg, 1):
            imgs = [img(pg) for pg in pgs]
            f, theme = tl.get(i, ("", ""))
            f = "サービスマネジメント" if f == "ITサービスマネジメント" else f   # 平成25年までの分野名
            fx = THEME_FIX.get(f"{eid}-pm{i}")
            if fx:
                f, theme = fx if isinstance(fx, tuple) else (f, fx)
            extra = {}
            if f == "プログラミング" and ref:
                extra["ref"] = ref
            if code in ERRATA and ERRATA[code][1] == i:
                extra["errata"] = img(ERRATA[code][0], "errata", rotate=-90)
            a = ans.get(i, {"aim": "", "rows": []})
            # 平成25年春までは 問1・2から1問、問3〜12から5問。以後は 問1必須、問2〜11から4問
            sel = ("問1・2から1問" if i <= 2 else "問3〜12から5問") if len(seg) == 12 else ("必須" if i == 1 else "問2〜11から4問")
            out.append({"id": f"{eid}-pm{i}", "src": src, "eid": eid, "no": i, "field": f, "theme": theme, "sel": sel,
                        "img": imgs, "aim": a["aim"], "rows": a["rows"], "cmnt": cm.get(i, ""), **extra})
    (SRC / "data" / "pm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(report))
    print("問題数:", len(out), " ページ画像:", sum(len(q["img"]) for q in out))


if __name__ == "__main__":
    main()

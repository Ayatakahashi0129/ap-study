"""画像だけのPDF（IPAの問題冊子など）を、Claude のマルチモーダル読み取りで問題データに書き起こす。

ページごとに画像にして（傾き補正・余白切り）Claude に渡し、決めたJSONスキーマで
  text / formula / code … 本文・数式・プログラム（アプリの書式 {sub:} {sup:} {ov:} {frac:a|b} {ul:} {dl:} 付き）
  choice              … 選択肢ア〜エ
  table               … 表（二次元配列。選択肢が表になっているものは label="選択肢"）
  figure              … 文字で表せない図（位置を返させ、その部分を画像で切り出す）
  noise               … ページ番号・白紙ページの断り書きなど
を返させる。結果はページ単位でキャッシュするので、同じページを二度読むことはない。

自動チェック
- 書式の括弧の対応・未知の書式名・分数の中の入れ子
- 選択肢ア〜エの欠け（--kind am）、問番号の飛び
- モデル自身が「自信がない」と書いたブロック → 該当部分を拡大して、もう一度読ませる（--no-verify で省略）
- --compare に ocr.ps1 の結果を渡すと、ページごとの文字の一致率を出し、低いページに印を付ける

使い方:
  python app_src/tools/pdf_ocr.py <PDF> [--pages 3-10] [--kind am|pm] [--dry-run] [--compare ocr.json]
出力（既定は 応用情報/ocr_cache/<PDF名>/ … Gitに入れない）
  pNNN.png / pNNN.json  ページ画像と読み取り結果（キャッシュ）
  fig/*.png             切り出した図
  questions.json        問ごとにまとめた結果（q / c / tb / figs / flags）
  report.html           ページ画像と読み取り結果を並べた確認用ページ

認証は ANTHROPIC_API_KEY（または ant auth login のプロファイル）を使う。
"""
import argparse, base64, hashlib, html, io, json, math, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_pm import skew_angle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODEL = "claude-opus-5-5"
PROMPT_VER = 1            # プロンプト・スキーマを変えたら上げる（キャッシュを読み直す）
MAX_EDGE = 2576           # Claude が縮小せずに読む長辺の上限（座標は画像の画素と1:1）
MAX_PIXELS = 4784 * 750   # 画像トークンの上限（4784）を超えると API 側で縮小され、座標がずれる
PRICE = (4.0, 20.0)       # claude-opus-5-5 の $/100万トークン（入力, 出力）。見積もり用
EST_OUT = 4000            # 1ページの出力（思考を含む）の見積もり。実測で直す
TAGS = ("sub", "sup", "ov", "ul", "dl", "frac")
KANA = "アイウエオカキク"

BLOCK = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["text", "formula", "code", "choice", "table", "figure", "noise"]},
        "question": {"type": "integer"},
        "label": {"type": "string"},
        "text": {"type": "string"},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "header_row": {"type": "boolean"},
        "bbox": {"type": "array", "items": {"type": "integer"}},
        "uncertain": {"type": "string"},
    },
    "required": ["type", "question", "label", "text", "rows", "header_row", "bbox", "uncertain"],
    "additionalProperties": False,
}
PAGE = {
    "type": "object",
    "properties": {"printed_page": {"type": "string"}, "blocks": {"type": "array", "items": BLOCK}},
    "required": ["printed_page", "blocks"],
    "additionalProperties": False,
}
FIX = {"type": "object", "properties": {"block": BLOCK}, "required": ["block"], "additionalProperties": False}

SYSTEM = """あなたは情報処理技術者試験（応用情報技術者試験）の問題冊子のスキャン画像を、学習アプリのデータに書き起こします。
目的は、元の画像を見なくても問題を解けるデータを作ることです。文字・数式・表は文字として正確に写し、文字では正確に表せない図だけを、画像で切り出す位置として返します。

# ブロック
ページの内容を、読む順に上から並べたブロックの列にします。
- text: 本文の段落・箇条書き。
- formula: 本文から独立して置かれた数式や、行をそろえて並べた式。
- code: プログラム・擬似言語。1行ごとに改行し、字下げは段ごとに半角スペース2つにする。▲ ■ ・ ｜ などの記号は見えるとおりに写す。
- choice: 選択肢1つ。label に「ア」「イ」などの記号、text にその中身を入れる（記号自体は text に入れない）。
- table: 表。rows に行ごとのセルの文字を入れる。見出し行があれば header_row を true にする。結合セルは左上のセルに文字を入れ、残りは空文字にする。選択肢が表の形で並んでいるとき（1列目がア〜エ）は label を「選択肢」にし、見出し行も rows に含める。それ以外の表の label は「」。
- figure: 図・グラフ・流れ図・回路図・状態遷移図・ネットワーク構成図・E-R図など、文字では正確に表せないもの。text には図の内容の要約（読み取れるラベルや数値を含める）を書く。中に絵や線が描かれた表も figure にする。
- noise: ページ番号（「− 5 −」など）、白紙ページの断り書き、「次ページに続く」などの案内。

# 各フィールド
- question: そのブロックが属する問の番号。「問3」の見出しがあれば以降は 3。ページの先頭が前のページから続く問題で、問番号が見えないときは 0。表紙・注意事項など問題でないところは -1。
- 「問3」という見出し自体は text に入れない（question で表す）。
- bbox: ブロックを囲む [左, 上, 右, 下]（画像の画素の座標）。figure は図番号やキャプション（「図1 …」）も含め、少し余白をとる。
- rows / header_row: table 以外は [] と false。
- uncertain: 読み取りに自信がない箇所があれば、その箇所と理由を書く（例:「3行目の添字が i か l か不明」）。自信があれば空文字。

# 書き方
- 文字は冊子のとおりに写す（読点「，」句点「。」、全角・半角の区別、カタカナの選択肢記号）。言い換え・要約・補足はしない。
- ふりがな（ルビ）は書かない。
- 改行は段落・箇条書き・式の行・表のセル内の改行だけに使い、紙面の折り返しでは改行しない。
- 書式（アプリが表示する記法）:
  - 下付き {sub:…}、上付き {sup:…}（例: x{sub:1}、2{sup:n}、10{sup:−3}、Σ{sub:i=1}{sup:n}）
  - 上線 {ov:…}（否定・補集合。例: {ov:A}・B）
  - 分数 {frac:分子|分母}（分子・分母の中には書式を入れない。入れ子が必要な式は figure にする）
  - 下線 {ul:…}、破線の下線 {dl:…}（関係スキーマの主キー・外部キーなど）
  - 平方根は √(…)。行列や、上の記法で表せない式は figure にする。
  - 書式の { } 以外に波括弧が紙面にあるときは ｛ ｝（全角）で写す。
- 縦に位置をそろえて並べた式は、行ごとに改行し、全角スペースで位置をそろえる。
- 四角で囲まれた空欄は ［a］ のように全角の角括弧で、中の記号を見えるとおりに写す。"""

VERIFY = """先ほどのページから、読み取りに不安があるブロックの部分を拡大した画像です。
最初の読み取り結果を下に示します。画像をよく見て、正しいブロックを返してください（type・書式のルールは同じ。bbox はそのまま返す）。
直したあとも不安が残るときだけ uncertain に理由を書いてください。

最初の読み取り結果:
"""


# ---------- 画像 ----------

def native_zoom(page):
    """スキャン画像の元の解像度で描画する倍率（それ以上細かくしても情報は増えない）"""
    imgs = page.get_images()
    if not imgs:
        return 3.0
    return max(1.0, imgs[0][2] / page.rect.width)


def page_image(doc, pno):
    """1始まりのページ番号 → 傾き補正・余白切り済みの元解像度の白黒画像"""
    pg = doc[pno - 1]
    z = native_zoom(pg)
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(z, z), colorspace=pymupdf.csGRAY)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    a = skew_angle(im)
    if abs(a) >= 0.05:
        im = im.rotate(a, resample=Image.BICUBIC, fillcolor=255)
    box = ImageOps.invert(im).point(lambda v: 255 if v > 40 else 0).getbbox()
    if box:
        pad = 24
        im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
    return im


def fit(im, edge=MAX_EDGE):
    """長辺 edge・画素数 MAX_PIXELS に収まる最大の大きさに拡大・縮小する（小さい添字を読みやすくするため拡大もする）"""
    s = min(edge / max(im.size), math.sqrt(MAX_PIXELS / (im.width * im.height)))
    return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)


def png_bytes(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def image_tokens(w, h):
    return min(4784, math.ceil(w * h / 750))


def crop(im, bbox, pad=16):
    x0, y0, x1, y1 = bbox
    return im.crop((max(0, x0 - pad), max(0, y0 - pad), min(im.width, x1 + pad), min(im.height, y1 + pad)))


# ---------- API ----------

def client():
    import anthropic
    try:
        return anthropic.Anthropic()
    except anthropic.AnthropicError as e:
        raise SystemExit(f"Claude API の認証情報がありません。ANTHROPIC_API_KEY を設定するか ant auth login してください（{e}）")


def ask(cl, content, schema, effort):
    """1回の問い合わせ。拒否・出力上限は例外にする。戻り値 (JSON, 使ったモデル, usage)"""
    with cl.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    ) as s:
        msg = s.get_final_message()
    if msg.stop_reason == "refusal":
        d = msg.stop_details
        raise RuntimeError(f"モデルが応答を拒否しました（{getattr(d, 'category', None)}: {getattr(d, 'explanation', '')}）")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("出力が max_tokens に達して途中で切れました")
    text = next(b.text for b in msg.content if b.type == "text")
    u = msg.usage
    usage = {"in": u.input_tokens, "out": u.output_tokens,
             "cache_w": u.cache_creation_input_tokens or 0, "cache_r": u.cache_read_input_tokens or 0}
    return json.loads(text), msg.model, usage


def image_block(png):
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()}}


KIND_HINT = {"am": "午前（科目A）の多肢選択式の問題冊子です。各問に選択肢ア〜エがあります。",
             "pm": "午後（科目B）の記述式の問題冊子です。1問が複数ページにわたり、設問・空欄・表・図・プログラムを含みます。"}


def read_page(cl, png, size, pno, kind, effort):
    note = f"{KIND_HINT[kind]}\nPDFの {pno} ページ目。画像の大きさは {size[0]}×{size[1]} 画素です。"
    return ask(cl, [image_block(png), {"type": "text", "text": note}], PAGE, effort)


def verify_block(cl, png, block, effort):
    data, model, usage = ask(cl, [image_block(png), {"type": "text", "text": VERIFY + json.dumps(block, ensure_ascii=False)}], FIX, effort)
    return {**data["block"], "bbox": block["bbox"], "question": block["question"]}, model, usage


# ---------- チェック（純粋関数） ----------

def markup_errors(s):
    """書式の誤り（括弧の対応・未知の書式名・分数の形）を返す"""
    errs, depth = [], 0
    for m in re.finditer(r"\{([a-z]*)(:?)|\}", s):
        if m.group(0) == "}":
            depth -= 1
            if depth < 0:
                errs.append("閉じ括弧 } が多い")
                depth = 0
        else:
            depth += 1
            if m.group(1) not in TAGS or not m.group(2):
                errs.append(f"未知の書式 {{{m.group(1)}")
    if depth > 0:
        errs.append("閉じ括弧 } が足りない")
    for m in re.finditer(r"\{frac:", s):
        body = s[m.end():s.find("}", m.end())]
        if "|" not in body or "{" in body:
            errs.append("分数は {frac:分子|分母} の形で、中に書式を入れない")
    return errs


def block_texts(b):
    return [b["text"]] + [c for r in b["rows"] for c in r]


def block_flags(b):
    out = [e for t in block_texts(b) for e in markup_errors(t)]
    if b["uncertain"]:
        out.append("不確か: " + b["uncertain"])
    if b["type"] == "figure" and len(b["bbox"]) != 4:
        out.append("図の位置が無い")
    return out


def plain(s):
    """比較用：書式を外し、NFKC で全角・半角をそろえ、空白を除く"""
    s = re.sub(r"\{(?:sub|sup|ov|ul|dl):|\{frac:|[{}|]", "", s)
    return re.sub(r"\s", "", unicodedata.normalize("NFKC", s))


def ocr_pages(path):
    """ocr.ps1 の結果 → {ページ番号: 本文}"""
    pages = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    pages = pages if isinstance(pages, list) else [pages]
    return {p["page"]: "".join(w["t"] for l in p["lines"] for w in l["words"]) for p in pages}


def similarity(ours, theirs):
    a, b = plain(ours), plain(theirs)
    return SequenceMatcher(None, a, b, autojunk=False).ratio() if a or b else 1.0


# ---------- 問ごとにまとめる（純粋関数。図の保存先の名前だけ決める） ----------

def assemble(pages, kind):
    """pages: [(ページ番号, 読み取り結果)] → (問のリスト, 問に入らなかったブロックの数)"""
    qs, cur, orphans = {}, None, 0
    for pno, res in pages:
        for i, b in enumerate(res["blocks"]):
            if b["type"] == "noise" or b["question"] < 0:
                continue
            if b["question"] > 0:
                cur = qs.setdefault(b["question"], {"no": b["question"], "pages": [], "lines": [], "c": {}, "tb": [], "th": [], "figs": [], "flags": []})
            if cur is None:
                orphans += 1
                continue
            if pno not in cur["pages"]:
                cur["pages"].append(pno)
            cur["flags"] += [f"p{pno}#{i}: {f}" for f in block_flags(b)]
            if b["type"] == "choice":
                cur["c"][b["label"]] = b["text"]
            elif b["type"] == "table" and b["label"] == "選択肢":
                head, body = (b["rows"][0], b["rows"][1:]) if b["header_row"] else ([], b["rows"])
                for r in body:
                    if r:
                        cur["c"][r[0].strip()] = "　".join(f"{h}：{v}" if h else v for h, v in zip(head[1:] or [""] * len(r), r[1:]))
                cur["lines"].append("{table:%d}" % len(cur["tb"]))
                cur["tb"].append(b["rows"])
                cur["th"].append(b["header_row"])
            elif b["type"] == "table":
                cur["lines"].append("{table:%d}" % len(cur["tb"]))
                cur["tb"].append(b["rows"])
                cur["th"].append(b["header_row"])
            elif b["type"] == "figure":
                name = f"p{pno:03d}_{i}.png"
                cur["lines"].append("{fig:%s}" % name)
                cur["figs"].append({"file": name, "page": pno, "bbox": b["bbox"], "alt": b["text"]})
            else:
                cur["lines"].append(b["text"])
    out = []
    for no in sorted(qs):
        q = qs[no]
        labels = sorted(q["c"], key=lambda k: KANA.find(k) if k in KANA else 99)
        if kind == "am" and labels[:4] != list("アイウエ"):
            q["flags"].append("選択肢がア〜エそろっていない: " + "".join(labels))
        out.append({"no": no, "pages": q["pages"], "q": "\n".join(q["lines"]), "c": [q["c"][k] for k in labels],
                    "tb": q["tb"], "th": q["th"], "figs": q["figs"], "flags": q["flags"]})
    nos = [q["no"] for q in out]
    for a, b in zip(nos, nos[1:]):
        if b != a + 1:
            next(q for q in out if q["no"] == b)["flags"].append(f"問{a}の次が問{b}（間が抜けている）")
    return out, orphans


# ---------- 確認用HTML ----------

def fmt(s):
    """アプリの qfmt と同じ書式を HTML にする"""
    h = html.escape(s)
    for _ in range(4):
        h = re.sub(r"\{(sub|sup):([^{}]*)\}", r"<\1>\2</\1>", h)
        h = re.sub(r"\{ov:([^{}]*)\}", r'<span style="text-decoration:overline">\1</span>', h)
        h = re.sub(r"\{ul:([^{}]*)\}", r"<u>\1</u>", h)
        h = re.sub(r"\{dl:([^{}]*)\}", r'<span style="text-decoration:underline dashed">\1</span>', h)
        h = re.sub(r"\{frac:([^|{}]*)\|([^{}]*)\}", r'<span class="frac"><span>\1</span><span>\2</span></span>', h)
    return h.replace("\n", "<br>")


COLOR = {"text": "#2563eb", "formula": "#9333ea", "code": "#0d9488", "choice": "#16a34a", "table": "#ea580c", "figure": "#db2777", "noise": "#9ca3af"}


def report(pages, sizes, questions, sims, out):
    parts = []
    for pno, res in pages:
        w, h = sizes[pno]
        rects, rows = [], []
        for i, b in enumerate(res["blocks"]):
            fl = block_flags(b)
            col = "#dc2626" if fl else COLOR[b["type"]]
            if len(b["bbox"]) == 4:
                x0, y0, x1, y1 = b["bbox"]
                rects.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="none" stroke="{col}" stroke-width="{4 if fl else 2}"/>'
                             f'<text x="{x0 + 4}" y="{y0 + 22}" fill="{col}" font-size="22">{i}</text>')
            if b["type"] == "table":
                body = "".join("<tr>" + "".join(f"<td>{fmt(c)}</td>" for c in r) + "</tr>" for r in b["rows"])
                content = f"<table>{body}</table>"
            elif b["type"] == "figure":
                content = f'<img class="fig" src="fig/p{pno:03d}_{i}.png"><div class="alt">{html.escape(b["text"])}</div>'
            elif b["type"] == "code":
                content = f"<pre>{html.escape(b['text'])}</pre>"
            else:
                content = (f"<b>{html.escape(b['label'])}</b> " if b["label"] else "") + fmt(b["text"])
            warn = "".join(f'<div class="warn">{html.escape(f)}</div>' for f in fl)
            rows.append(f'<div class="blk{" bad" if fl else ""}"><span class="tag" style="background:{COLOR[b["type"]]}">{i} {b["type"]} 問{b["question"]}</span>{content}{warn}</div>')
        sim = f'　OCRとの一致率 {sims[pno]:.0%}' if pno in sims else ""
        low = ' class="low"' if pno in sims and sims[pno] < 0.8 else ""
        parts.append(f'<section id="p{pno}"><h2{low}>p{pno}（冊子 {html.escape(res["printed_page"])}）{sim}</h2><div class="pair">'
                     f'<div class="pg"><img src="p{pno:03d}.png"><svg viewBox="0 0 {w} {h}">{"".join(rects)}</svg></div>'
                     f'<div class="res">{"".join(rows)}</div></div></section>')
    summary = "".join(f'<tr><td>問{q["no"]}</td><td>{", ".join(f"<a href=#p{p}>p{p}</a>" for p in q["pages"])}</td>'
                      f'<td>{len(q["c"])}</td><td>{len(q["tb"])}</td><td>{len(q["figs"])}</td>'
                      f'<td>{"<br>".join(html.escape(f) for f in q["flags"])}</td></tr>' for q in questions)
    css = """body{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}.pg{position:relative}.pg img,.pg svg{width:100%;display:block}
.pg svg{position:absolute;inset:0;height:100%}.blk{border-left:3px solid #ddd;padding:4px 8px;margin:6px 0;line-height:1.7}.blk.bad{border-color:#dc2626;background:#fef2f2}
.tag{color:#fff;font-size:11px;padding:1px 6px;border-radius:3px;margin-right:6px}.warn{color:#dc2626;font-size:13px}
table{border-collapse:collapse}td{border:1px solid #999;padding:2px 6px}.fig{max-width:100%;border:1px solid #ddd}.alt{color:#555;font-size:13px}
.frac{display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center}.frac>span:first-child{border-bottom:1px solid}
h2.low{color:#dc2626}pre{background:#f5f5f5;padding:6px;white-space:pre-wrap}section{border-top:2px solid #333;margin-top:24px}"""
    out.write_text(f'<!doctype html><meta charset="utf-8"><title>OCR確認</title><style>{css}</style>'
                   f'<h1>読み取り結果の確認</h1><table><tr><th>問</th><th>ページ</th><th>選択肢</th><th>表</th><th>図</th><th>要確認</th></tr>{summary}</table>'
                   + "".join(parts), encoding="utf-8")


# ---------- 実行 ----------

def parse_pages(spec, n):
    if not spec:
        return list(range(1, n + 1))
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += range(int(a), int(b or a) + 1)
    return [p for p in out if 1 <= p <= n]


def cache_key(png, kind, effort):
    return hashlib.sha256(png + f"|{MODEL}|{PROMPT_VER}|{kind}|{effort}".encode()).hexdigest()[:16]


def process(cl, doc, pno, out, kind, effort, verify):
    """1ページを読む（キャッシュがあればそれを返す）。戻り値 (ページ番号, 結果, 大きさ, usage)"""
    base = page_image(doc, pno)
    big = fit(base)
    png = png_bytes(big)
    (out / f"p{pno:03d}.png").write_bytes(png)
    key = cache_key(png, kind, effort)
    cache = out / f"p{pno:03d}.json"
    if cache.exists():
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("key") == key:
            return pno, c["result"], big.size, {}
    res, model, usage = read_page(cl, png, big.size, pno, kind, effort)
    log = []
    if verify:
        for i, b in enumerate(res["blocks"]):
            if b["type"] != "noise" and len(b["bbox"]) == 4 and block_flags(b):
                part = png_bytes(fit(crop(big, b["bbox"])))
                fixed, _, u = verify_block(cl, part, b, effort)
                log.append({"block": i, "before": b, "after": fixed})
                res["blocks"][i] = fixed
                usage = {k: usage[k] + u[k] for k in usage}
    cache.write_text(json.dumps({"key": key, "model": model, "usage": usage, "verified": log, "result": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    return pno, res, big.size, usage


def save_figures(pages, out):
    """図のブロックをページ画像から切り出す（名前は assemble と同じ pNNN_<ブロック番号>.png）"""
    (out / "fig").mkdir(exist_ok=True)
    for pno, res in pages:
        figs = [(i, b) for i, b in enumerate(res["blocks"]) if b["type"] == "figure" and len(b["bbox"]) == 4]
        if figs:
            im = Image.open(out / f"p{pno:03d}.png")
            for i, b in figs:
                crop(im, b["bbox"], pad=8).save(out / "fig" / f"p{pno:03d}_{i}.png")


def dry_run(doc, pages, out):
    tok = 0
    sys_tok = len(SYSTEM)   # 日本語はおおむね1文字1トークン
    for pno in pages:
        big = fit(page_image(doc, pno))
        big.save(out / f"p{pno:03d}.png")
        t = image_tokens(*big.size)
        tok += t + sys_tok + 100
        print(f"p{pno}: {big.size[0]}×{big.size[1]} 画像 約{t}トークン")
    cost = tok / 1e6 * PRICE[0] + len(pages) * EST_OUT / 1e6 * PRICE[1]
    print(f"{len(pages)}ページ  入力 約{tok:,}トークン  出力 約{len(pages) * EST_OUT:,}トークン（推定）  概算 ${cost:.2f}"
          "（キャッシュ・再読み取りを含まない目安）")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="例: 3-10,12（既定は全ページ）")
    ap.add_argument("--kind", choices=["am", "pm"], default="am", help="am=科目A（選択肢ア〜エ）, pm=科目B")
    ap.add_argument("--out", help="出力先（既定: 応用情報/ocr_cache/<PDF名>）")
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--workers", type=int, default=4, help="同時に読むページ数")
    ap.add_argument("--compare", help="ocr.ps1 の結果JSON（ページごとの一致率を出す）")
    ap.add_argument("--no-verify", action="store_true", help="不確かなブロックの読み直しをしない")
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、画像を作ってトークン数を見積もる")
    a = ap.parse_args()

    pdf = Path(a.pdf).resolve()
    doc = pymupdf.open(pdf)
    out = Path(a.out) if a.out else ROOT / "応用情報" / "ocr_cache" / pdf.stem
    out.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(a.pages, doc.page_count)
    if a.dry_run:
        return dry_run(doc, pages, out)

    cl = client()
    results, errors = {}, {}

    def run(pno):
        # PyMuPDF の Document はスレッド間で共有しない
        try:
            return process(cl, pymupdf.open(pdf), pno, out, a.kind, a.effort, not a.no_verify)
        except Exception as e:  # ページ単位で失敗を記録し、他のページは続ける
            errors[pno] = f"{type(e).__name__}: {e}"
            return None

    total = {"in": 0, "out": 0, "cache_w": 0, "cache_r": 0}
    with ThreadPoolExecutor(a.workers) as ex:
        for r in ex.map(run, pages):
            if r:
                pno, res, size, usage = r
                results[pno] = (res, size)
                total = {k: total[k] + usage.get(k, 0) for k in total}
                print(f"p{pno}: {len(res['blocks'])}ブロック" + ("（キャッシュ）" if not usage else f"（入力{usage['in']} 出力{usage['out']}）"))

    done = [(p, results[p][0]) for p in pages if p in results]
    questions, orphans = assemble(done, a.kind)
    save_figures(done, out)
    sims = {}
    if a.compare:
        theirs = ocr_pages(a.compare)
        sims = {p: similarity("".join(t for b in res["blocks"] for t in block_texts(b) if b["type"] != "figure"), theirs.get(p, ""))
                for p, res in done if p in theirs}
    (out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding="utf-8")
    report(done, {p: results[p][1] for p, _ in done}, questions, sims, out / "report.html")

    flagged = [q for q in questions if q["flags"]]
    cost = (total["in"] + total["cache_w"] * 1.25 + total["cache_r"] * 0.1) / 1e6 * PRICE[0] + total["out"] / 1e6 * PRICE[1]
    print(f"\n{len(done)}/{len(pages)}ページ  {len(questions)}問（要確認 {len(flagged)}問）  問に入らないブロック {orphans}")
    if total["out"]:
        print(f"今回の使用量: 入力{total['in']:,} キャッシュ書込{total['cache_w']:,} 読込{total['cache_r']:,} 出力{total['out']:,}  概算 ${cost:.2f}")
    low = [p for p, s in sims.items() if s < 0.8]
    if low:
        print("OCRとの一致率が低いページ:", ", ".join(f"p{p}({sims[p]:.0%})" for p in low))
    print("確認用:", out / "report.html")
    if errors:
        for p, e in sorted(errors.items()):
            print(f"p{p} 失敗: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

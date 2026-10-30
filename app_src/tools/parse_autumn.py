"""秋期（平成26〜30年秋・令和2年10月・令和3年秋）の午前問題を作る。

- 問題文・選択肢: IPA公開の問題PDFを Windows OCR した結果（ocr.ps1 の JSON）
- 正解・解説   : 手元の解説PDF（応用情報/◯年秋.pdf）を pdftotext したもの
- 正解の照合   : IPA公開の解答例PDF
- 分類         : 春期の分類付き問題を手本に、文字bigramの類似度＋出題順の制約で推定

使い方: python parse_autumn.py <scratchpad>   （出力: app_src/data/autumn.json）
"""
import json, math, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(sys.argv[1])
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import GROUPS, CAT2GROUP  # noqa: E402

EXAMS = [  # (IPAファイル名, 解説txt, id, 表示名)
    ("2014h26a", "26年秋", "26_aki", "平成26年秋期"),
    ("2015h27a", "27年秋", "27_aki", "平成27年秋期"),
    ("2016h28a", "28年秋", "28_aki", "平成28年秋期"),
    ("2017h29a", "29年秋", "29_aki", "平成29年秋期"),
    ("2018h30a", "30年秋", "30_aki", "平成30年秋期"),
    ("2020r02o", "2年秋", "02_aki", "令和2年10月"),
    ("2021r03a", "3年秋", "03_aki", "令和3年秋期"),
]
KANA = "アイウエ"
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
CJK = r"぀-ゟ一-鿿"
HIRA_KANJI = rf"[{CJK}々]"
KATA = r"[ァ-ヺー]"

# ---------------------------------------------------------------- OCR → 行
def load_rows(path):
    pages = json.loads(path.read_text(encoding="utf-8-sig"))
    out = []
    for p in pages:
        lines = p.get("lines") or []
        if isinstance(lines, dict):
            lines = [lines]
        rows = []
        for l in lines:
            ws = l["words"] if isinstance(l["words"], list) else [l["words"]]
            rows.append({"x": l["x"], "y": l["y"], "h": l["h"], "t": join_words(ws)})
        if not rows:
            continue
        hs = sorted(r["h"] for r in rows)
        tol = max(20, hs[len(hs) // 2] * 0.6)
        rows.sort(key=lambda r: r["y"])
        clusters = []
        for r in rows:
            if clusters and abs(r["y"] - clusters[-1][0]["y"]) <= tol:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for c in clusters:
            c.sort(key=lambda r: r["x"])
            toks = [r["t"] for r in c]
            # ページ番号（数字だけの短い行）を除く
            if len(toks) == 1 and re.fullmatch(r"[-－‐\s\d]{1,4}", toks[0]):
                continue
            out.append({"page": p["page"], "x": c[0]["x"], "toks": toks})
    return out


def join_words(ws):
    s, prev = "", None
    for w in ws:
        t = w["t"]
        if prev is not None:
            gap = w["x"] - (prev["x"] + prev["w"])
            a, b = prev["t"][-1], t[0]
            if re.match(rf"[{CJK}゠-ヿ　-〿＀-￯]", a) or re.match(rf"[{CJK}゠-ヿ　-〿＀-￯]", b):
                s += " " if gap > 80 else ""
            else:
                s += " " if gap > 10 else ""
        s += t
        prev = w
    return s


# ---------------------------------------------------------------- OCR補正
CONFUSE_KATA = {"力": "カ", "工": "エ", "口": "ロ", "二": "ニ", "夕": "タ", "卜": "ト", "八": "ハ", "一": "ー", "ェ": "エ", "へ": "ヘ", "べ": "ベ", "ぺ": "ペ", "り": "リ", "ぼ": "ボ"}
CONFUSE_HIRA = {"リ": "り", "ヘ": "へ", "ベ": "べ", "ペ": "ぺ"}
FIXES = [
    (r"状能", "状態"), (r"Scnpt", "Script"), (r"1YpeScript", "TypeScript"), (r"(?<![A-Za-z])Jav aScript", "JavaScript"),
    (r"ずっ(?=設置|配置|割り|増や|入力|処理)", "ずつ"), (r"パラメタ", "パラメタ"), (r"ネットワ一ク", "ネットワーク"),
    (r"\bl(?=\d)", "1"), (r"(?<=\d)O\b", "0"), (r"(?<=[0-9])，(?=[0-9]{3})", ","), (r"〜", "～"),
    (r"(?<=[A-Za-z])ー(?=[A-Za-z])", "-"), (r"一(?=[A-Za-z0-9])(?<=[A-Za-z0-9]一)", "-"),
]


def fix_text(s):
    # 日本語の文中の半角カンマ・ピリオドは全角に（IPAの問題文の表記）
    s = re.sub(rf"(?<=[{CJK}゠-ヿ）」])\s*,\s*", "，", s)
    s = re.sub(rf"(?<=[{CJK}゠-ヿ）」])\s*\.\s*(?=\s|$|[{CJK}])", "。", s)
    for _ in range(2):
        # カタカナ語の中に紛れた漢字・ひらがな → カタカナ
        s = re.sub(rf"(?<={KATA})([{''.join(CONFUSE_KATA)}])(?={KATA})", lambda m: CONFUSE_KATA[m.group(1)], s)
        s = re.sub(rf"(?<={KATA})([力工口二夕卜一ェ])(?=[\s，。,）)]|$)", lambda m: CONFUSE_KATA[m.group(1)], s)
        # ひらがな・漢字に挟まれたカタカナ → ひらがな（取リ出す → 取り出す）
        s = re.sub(rf"(?<={HIRA_KANJI})([リヘベペ])(?={HIRA_KANJI}|[，。、])", lambda m: CONFUSE_HIRA[m.group(1)], s)
        s = re.sub(rf"(?<=[぀-ゟ])([リヘベペ])(?=[぀-ゟ{CJK}])", lambda m: CONFUSE_HIRA[m.group(1)], s)
    for a, b in FIXES:
        s = re.sub(a, b, s)
    # 指数（5X10ー6 → 5×10⁻⁶）と掛け算記号
    sup = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
    s = re.sub(r"(?<=\d)\s*[X×x]\s*10\s*[ー\-−一]\s*(\d{1,2})(?!\d)", lambda m: "×10" + ("-" + m.group(1)).translate(sup), s)
    s = re.sub(r"(?<=\d)\s*X\s*(?=\d)", "×", s)
    s = re.sub(r"かっ(?=[，、])", "かつ", s)
    s = re.sub(r"(?<=[をが])もっ(?=こと|もの|[，。])", "もつ", s)
    s = re.sub(r"ば(?=どれか)", "は", s)
    s = re.sub(r"(?<![A-Za-z])1P(?=v[46]|アドレス|)", "IP", s)
    s = s.replace("盜", "盗")
    s = re.sub(r"ーっ", "一つ", s)
    for a, b in (("プロードキャスト", "ブロードキャスト"), ("ポップ数", "ホップ数"), ("テープル", "テーブル"), ("ノートプック", "ノートブック"),
                 ("リプート", "リブート"), ("ブロセス", "プロセス"), ("チエ", "チェ"), ("ジエ", "ジェ"), ("フエッ", "フェッ"), ("バッフア", "バッファ"),
                 ("ⅥP", "VIP"), ("M/M/I", "M/M/1"), ("()P", "(IP"), ("I。T", "IoT"), ("10T", "IoT"), ("セキュリテイ", "セキュリティ"),
                 ("かっ総合", "かつ総合"), ("工ッジ", "エッジ"), ("工コノミ", "エコノミ"), ("工ージエント", "エージェント"), ("工ージェント", "エージェント")):
        s = s.replace(a, b)
    s = re.sub(r"^\s*Ø\s*", "", s)
    s = re.sub(r"\s?><\s?", "×", s)
    s = re.sub(r"(?<=[ァ-ヺ])=(?=[ァ-ヺー])", "ュ", s)
    s = re.sub(r"(?<![A-Za-z])web(?=[A-Zァ-ヺ])", "Web", s)
    s = re.sub(r"(?<![A-Za-z])\s?b(?=サイト|サーバ|ページ|ブラウザ|で公開)", "Web", s)
    s = re.sub(r"(?<=[A-Za-z])\s?of(?=[A-Z][a-z])", " of ", s)
    s = re.sub(r"(?<![A-Za-z])L\s(?=[ぁ-んァ-ヺ一-龥])", "LAN", s)
    s = re.sub(r"(?<=[一-龥])カ(?=[，。、\s]|$)", "力", s)
    s = re.sub(r"どれか(?=ここで)", "どれか。", s)
    s = re.sub(r"(?<!か)どれ$", "どれか。", s)
    s = re.sub(r"(?<=。)\s*[^\s。）」)]{1,4}$", "", s) if not re.search(r"。ここで|。また", s[-8:]) else s
    s = s.replace("ァータ", "データ").replace("テータ", "データ")
    s = re.sub(r"(?<=[。])\s*こで，", "ここで，", s)
    s = re.sub(r"(?<=[>＞<＜=]) ?O", "0", s)
    s = re.sub(r"ずっ(?!と)", "ずつ", s)
    s = s.replace("ノヾ", "バ").replace("イ旨ロ", "信").replace("イ旨", "信").replace("Ⅷ", "XM").replace("ASCⅡ", "ASCII").replace("灯P", "UDP")
    s = re.sub(r"(?<=[ァ-ヺー])ノレ", "ル", s)
    s = re.sub(r"(^|[。，])\s*'\s*こで", r"ここで", s)
    s = re.sub(r"(?<=[A-Za-z0-9)）])\s*十\s*(?=[A-Za-z0-9(（])", "＋", s)
    # 難読漢字のふりがな（ルビ）がOCRで本文に混ざったものを除く
    for kanji, ruby in (("脆", "ぜい"), ("脆", "せい"), ("憑", "ひょう"), ("稟", "りん"), ("牽", "けん"), ("瑕疵", "かし"), ("頒", "はん"), ("毀", "き"), ("拗", "よう")):
        if kanji in s:
            s = re.sub(rf"(?<!し){ruby}(?![ゃゅょぁ-ゖ]{{0}}[たこら])" if ruby == "かし" else ruby, "", s) if ruby not in ("き", "せい", "よう") else re.sub(rf"(?<=[。ァ-ヺ]){ruby}|{ruby}(?=[ァ-ヺ]|$)", "", s)
    s = re.sub(r"(?<=[぀-ゟ])リ(?![ァ-ヺー])", "り", s)
    s = re.sub(rf"(?<=[{CJK}゠-ヿ。）])[\s\-ー－]*\d{{1,2}}[\s\-ー－]*$", "", s)   # ページ番号「- 17 -」の混入
    s = re.sub(rf"(?<=[{CJK}゠-ヿ＀-￯。，、）（「」])\s+(?=[{CJK}゠-ヿ＀-￯。，、）（「」])", "", s)
    return s.strip()


# ---------------------------------------------------------------- 用語辞書による補正
SMALL = str.maketrans("ァィゥェォッャュョヮヵヶ", "アイウエオツヤユヨワカケ")


def kana_key(w):
    import unicodedata
    w = unicodedata.normalize("NFD", w)
    w = "".join(ch for ch in w if ch not in "゙゚")   # 濁点・半濁点を無視
    return w.translate(SMALL).replace("ー", "")


class Vocab:
    """正しく書かれたテキスト（春期の問題・解説、カード、当該問題の解説）から
    カタカナ語・英字語を集め、OCR結果の語が辞書に無いとき、濁点違い等で一致する語に直す。"""
    def __init__(self, texts):
        self.kata, self.latin = {}, {}
        cnt = Counter()
        for t in texts:
            cnt.update(re.findall(r"[ァ-ヺー]{2,}", t))
        for w, c in cnt.most_common():
            self.kata.setdefault(kana_key(w), w)
        self.words = set(cnt)
        lc = Counter()
        for t in texts:
            lc.update(re.findall(r"[A-Za-z][A-Za-z0-9\-/.]*[A-Za-z0-9]", t))
        for w, c in lc.most_common():
            self.latin.setdefault(w.lower(), w)
        self.lwords = set(lc)

    def fix(self, s, ctx=""):
        local = {kana_key(w): w for w in re.findall(r"[ァ-ヺー]{2,}", ctx)}
        def kfix(m):
            w = m.group(0)
            if w in self.words and kana_key(w) not in local:
                return w
            k = kana_key(w)
            return local.get(k) or (w if w in self.words else self.kata.get(k, w))
        def head(m):
            w = m.group(0)
            alt = CONFUSE_KATA.get(w[0], w[0]) + w[1:]
            k = kana_key(alt)
            if w[1:] in self.words and len(w) > 3 and k not in self.kata and k not in local:
                return w
            return local.get(k) or self.kata.get(k) or w
        s = re.sub(r"[工力口二夕卜ェべぺへ](?=[ァ-ヺー])[ァ-ヺー]{2,}", head, s)
        s = re.sub(r"(?<=[ァ-ヺ])[べぺへ][ァ-ヺー]+", lambda m: CONFUSE_KATA[m.group(0)[0]] + m.group(0)[1:], s)
        s = re.sub(r"[ァ-ヺー]{2,}", kfix, s)
        def lfix(m):
            w = m.group(0)
            if w in self.lwords:
                return w
            cand = w.replace("1", "l") if re.search(r"[a-z]1|1[a-z]", w) else w
            for c in (cand, w.replace("0", "O"), w.replace("rn", "m"), w.replace("l", "I"), "I" + w[1:] if w[0] == "l" else w, w.replace("I", "l")):
                if c.lower() in self.latin:
                    return self.latin[c.lower()]
            return w
        return re.sub(r"[A-Za-z][A-Za-z0-9\-/.]*[A-Za-z0-9]", lfix, s)


def build_vocab():
    texts = []
    for x in json.loads((SRC / "data/past.json").read_text(encoding="utf-8")):
        texts += [x.get("q", ""), *x.get("c", []), *x.get("exp", []), x["title"]]
    for x in json.loads((SRC / "data/original.json").read_text(encoding="utf-8")):
        texts += [x["q"], *x["c"], *x["exp"]]
    for g, f, t, d in json.loads((SRC / "data/flashcards.json").read_text(encoding="utf-8")):
        texts += [t, d]
    for _, txt, _, _ in EXAMS:
        texts += [p for _, (a, ps) in load_explanations(txt).items() for p in ps]
    return Vocab(texts)


# ---------------------------------------------------------------- 問題の切り出し
MARK = {"ア": 0, "イ": 1, "ウ": 2, "エ": 3, "工": 3, "ェ": 3, "I": 3}


def num_pat(k):
    # OCRで「問1 5」のように数字の間に空白が入ることがある
    return re.compile(r"^[問間闇]\s*" + r"\s?".join(str(k)) + r"(?!\d)\s*")


def split_questions(rows):
    """問番号の行で区切る。番号が読み違えられた見出し（「問純」＝問10 など）は、
    左端の位置と連番から補い、後ろで番号が正しく読めた見出しに再同期する。"""
    qs, cur, n = {}, None, 1
    for r in rows:
        if r["page"] <= 2:          # 表紙（「問1〜問80」の表）と表記ルールのページ
            continue
        first = r["toks"][0]
        if re.search(r"問\s*\d+\s*から\s*問|系の問題です", first):   # 「問1から問50までは，テクノロジ系の問題です。」
            continue
        hit = None
        for k in range(n, min(n + 3, 81)):
            m = num_pat(k).match(first)
            if m:
                hit = (k, m.end())
                break
        if not hit and n <= 80 and r["x"] < 440 and re.match(r"^問(?![題い合])", first):
            m = re.match(r"^問\s*[\d\s、，,.のo〇純四l|I]{0,3}", first)
            hit = (n, m.end())
        if hit:
            cur, n = hit[0], hit[0] + 1
            qs[cur] = [{"x": r["x"], "toks": [first[hit[1]:]] + r["toks"][1:]}]
        elif cur:
            qs[cur].append(r)
    return qs


def build_question(lines):
    stem, choices, expect = [], [None] * 4, 0
    cur = None
    for li, ln in enumerate(lines):
        for ti, t in enumerate(ln["toks"]):
            t = t.strip()
            if not t:
                continue
            m = re.match(r"^([アイウエ工ェI])(?:\s+|$)(.*)$", t)
            stem_done = cur is not None or (stem and re.search(r"(か|。|？|\?)$", stem[-1][1]))
            if not m and expect < 4 and t[:1] in "アイウエ工ェ" and MARK[t[0]] == expect and stem_done and (ti == 0 or len(ln["toks"]) > 1):
                m = re.match(r"^(.)(.*)$", t)  # 「ウ神経回路網」のように記号の後に空白が無い場合
            if m and expect < 4 and MARK[m.group(1)] == expect and (expect > 0 or li > 0):
                cur = expect
                choices[cur] = [m.group(2)] if m.group(2) else []
                expect += 1
            elif cur is None:
                stem.append((ln["x"], t))
            else:
                choices[cur].append(t)
    if None in choices:
        return None, None
    # 本文は左端のx位置が揃っているので、行頭字下げを段落区切りとして扱わず結合する
    stem_txt = "".join(t if not re.match(r"^[〔(（①②③④⑤]", t) and not re.match(r"^\d+\s", t) else "\n" + t for _, t in stem).strip()
    return fix_text(stem_txt), [fix_text(" ".join(c) if all(re.search(r"[A-Za-z0-9]$", a) for a in c[:-1]) else "".join(c)) for c in choices]


# ---------------------------------------------------------------- 解説・解答
def load_explanations(name):
    t = (BASE / "txt" / f"{name}.txt").read_text(encoding="utf-8", errors="replace").translate(Z2H)
    lines = t.splitlines()
    res, cur, buf = {}, None, []
    for ln in lines:
        # 平成28年秋のPDFは数字が抜けて「問 解答 ウ」となるので、番号が無ければ連番とみなす
        m = re.match(r"^\s*[［\[]?\s*問\s*(\d*)\s*[］\]]?\s*解答\s*([アイウエ])", ln)
        if m:
            if cur:
                res[cur] = buf
            n = int(m.group(1)) if m.group(1) else (cur[0] + 1 if cur else 1)
            cur, buf = (n, KANA.index(m.group(2))), []
            continue
        if cur is None:
            continue
        if re.fullmatch(r"\s*\d{1,3}\s*", ln) or re.search(r"(付録|ಛయ)", ln):
            continue
        buf.append(ln)
    if cur:
        res[cur] = buf
    out = {}
    for (n, a), b in res.items():
        out[n] = (a, paragraphs(b))
    return out


def paragraphs(lines):
    paras, cur = [], []
    for ln in lines:
        s = ln.strip().replace("　", " ")
        if not s:
            if cur:
                paras.append(cur); cur = []
            continue
        cur.append(s)
    if cur:
        paras.append(cur)
    merged = []
    for p in paras:
        if merged and not re.search(r"[。．）)」：:]$", merged[-1][-1]) and not re.match(r"^[アイウエ][，,、 ]", p[0]):
            merged[-1].extend(p)
        else:
            merged.append(p)
    out = []
    for p in merged:
        t = ""
        for s in p:
            t += (" " if t and re.search(r"[A-Za-z0-9,.)]$", t) and re.match(r"[A-Za-z0-9(]", s) else "") + s
        out.append(re.sub(r"[ \t]{2,}", " ", t))
    return out


def load_ipa_answers(code):
    t = (BASE / "ipa" / f"{code}_ap_am_ans.txt").read_text(encoding="utf-8").translate(Z2H)
    # 平成26・27年の表は1列目（問1〜20）の行がずれているので、分野列のある形式のときだけ全問を使う
    allrows = re.findall(r"問\s*(\d+)\s+([アイウエ])\s*([ＴＭＳTMS])?", t)
    has_field = sum(1 for *_, f in allrows if f) >= 70
    return {int(n): KANA.index(k) for n, k, _ in allrows if has_field or int(n) > 20}


# ---------------------------------------------------------------- 分類の推定
def bigrams(s):
    s = re.sub(r"\s", "", s)
    return Counter(s[i:i + 2] for i in range(len(s) - 1))


def train():
    past = json.loads((SRC / "data/past.json").read_text(encoding="utf-8"))
    docs = [(x["field"], CAT2GROUP.get(x["cat"]), x["cat"], bigrams(x.get("q", "") + "".join(x.get("c", [])) + x["title"] * 3 + "".join(x.get("exp", [])[:1])))
            for x in past if x.get("q") or x.get("exp")]
    df = Counter(g for *_, v in docs for g in v)
    N = len(docs)
    idf = {g: math.log(N / (1 + c)) for g, c in df.items()}
    vecs = []
    for f, g, cat, v in docs:
        w = {k: c * idf.get(k, 0) for k, c in v.items()}
        nrm = math.sqrt(sum(x * x for x in w.values())) or 1
        vecs.append((f, g, cat, {k: x / nrm for k, x in w.items()}))
    return vecs, idf


PEN = 2.0   # 春期の分類済み問題で検証して決めた値（正答率 約90%）


def classify(items, vecs, idf):
    order = list(GROUPS)
    scores, cats = [], []
    for it in items:
        v = bigrams(it["q"] + "".join(it["c"]) + "".join(it["exp"][:2]))
        w = {k: c * idf.get(k, 0) for k, c in v.items()}
        nrm = math.sqrt(sum(x * x for x in w.values())) or 1
        w = {k: x / nrm for k, x in w.items()}
        sims = sorted(((sum(x * w.get(k, 0) for k, x in d.items()), g, cat) for f, g, cat, d in vecs if f == it["field"]), reverse=True)[:7]
        sc = defaultdict(float)
        for s, g, _ in sims:
            sc[g] += s
        scores.append(sc)
        cats.append(sims)
    # 出題順はおおむねシラバス順なので、分類が前に戻る並びにペナルティを掛けたDPで決める
    n, G = len(items), len(order)
    best = [[-1e9] * G for _ in range(n)]
    back = [[0] * G for _ in range(n)]
    for j in range(G):
        best[0][j] = scores[0].get(order[j], 0)
    for i in range(1, n):
        for j in range(G):
            cand = max(range(G), key=lambda k: best[i - 1][k] - (PEN if k > j else 0))
            best[i][j] = best[i - 1][cand] - (PEN if cand > j else 0) + scores[i].get(order[j], 0)
            back[i][j] = cand
    j = max(range(G), key=lambda k: best[-1][k])
    path = [j]
    for i in range(n - 1, 0, -1):
        j = back[i][j]
        path.append(j)
    path.reverse()
    for it, gi, sims in zip(items, path, cats):
        g = order[gi]
        it["g"] = g
        it["cat"] = next((c for _, gg, c in sims if gg == g), GROUPS[g][0])


def apply_manual(items):
    fx = json.loads((SRC / "data/autumn_fix.json").read_text(encoding="utf-8"))
    for it in items:
        i = it["id"]
        for fid, a, b in fx["replace"]:
            if fid == i:
                it["q"] = it["q"].replace(a, b)
                it["c"] = [c.replace(a, b) for c in it["c"]]
        if i in fx["q"]:
            it["q"] = fx["q"][i]
        if i in fx["choices"]:
            it["c"] = fx["choices"][i]
        if i in fx["drop"]:
            it["flags"].append("dropped")
            it["ok"] = False


def check_alignment(items):
    """問題文と解説の文字bigramの重なりが、隣の問題の解説との重なりより小さければ、切り出しのずれとみなす。"""
    bg = lambda s: (lambda t: {t[i:i + 2] for i in range(len(t) - 1)})(re.sub(r"\s", "", s))
    exps = [bg("".join(it["exp"])) for it in items]
    for i, it in enumerate(items):
        if not it["q"]:
            continue
        q = bg(it["q"] + "".join(it["c"]))
        ov = lambda j: len(q & exps[j]) / max(1, len(q)) if 0 <= j < len(items) else 0
        if max(ov(i - 1), ov(i + 1)) > ov(i) + 0.03:
            it["flags"].append("misalign")
            it["ok"] = False


# ---------------------------------------------------------------- main
FIG = re.compile(r"図|表[^すし現示記面計]|グラフ|流れ図|次の(プログラム|擬似|疑似|関数)|空欄|〔|［|\[")


VOCAB = None


def main():
    global VOCAB
    VOCAB = build_vocab()
    vecs, idf = train()
    allq, report = [], []
    for code, txt, eid, label in EXAMS:
        rows = load_rows(BASE / "ipa" / f"{code}.json")
        qb = split_questions(rows)
        ex = load_explanations(txt)
        ipa = load_ipa_answers(code)
        items = []
        stat = Counter()
        for n in range(1, 81):
            field = "T" if n <= 50 else ("M" if n <= 60 else "S")
            a, exp = ex.get(n, (None, []))
            it = {"id": f"{eid}-{n}", "exam": label, "eid": eid, "no": n, "field": field, "ans": a, "exp": exp, "q": "", "c": ["", "", "", ""], "flags": []}
            if n in ipa and a is not None and ipa[n] != a:
                it["exp"] = []            # 解説の対応がずれている可能性があるので使わない
            if n in ipa:
                it["ans"] = ipa[n]        # 正解はIPA公表の解答例を優先
            if eid == "28_aki" and it["exp"]:
                it["exp"] = ["（注：この回の解説PDFは数字が欠けて読み取られています。数値は問題文を参照してください）"] + it["exp"]
            if not it["exp"]:
                it["exp"] = [f"正解は{KANA[it['ans']]}（IPA公表の解答例）。"] if it["ans"] is not None else []
            if n in qb:
                stem, cs = build_question(qb[n])
                if stem is None:
                    it["flags"].append("nochoice")
                else:
                    ctx = "".join(exp)
                    it["q"], it["c"] = VOCAB.fix(stem, ctx), [VOCAB.fix(c, ctx) for c in cs]
                    if FIG.search(stem):
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
            it["ok"] = not it["flags"]
            stat["ok" if it["ok"] else it["flags"][0]] += 1
            items.append(it)
        apply_manual(items)
        check_alignment(items)
        classify(items, vecs, idf)
        allq += items
        report.append(f"{label}: 問題ブロック{len(qb)} 解説{len(ex)} " + " ".join(f"{k}={v}" for k, v in sorted(stat.items())))
    (SRC / "data/autumn.json").write_text(json.dumps(allq, ensure_ascii=False, indent=0), encoding="utf-8")
    print("\n".join(report))
    print("採用:", sum(x["ok"] for x in allq), "/", len(allq))


if __name__ == "__main__":
    main()

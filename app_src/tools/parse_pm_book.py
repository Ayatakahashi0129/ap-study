"""科目B（午後）の参考書の解説を、手持ちのPDF（応用情報/*.pdf）から取り出す。

各問題は「問N 分野 ≪出題趣旨≫ … ≪解答例≫ … ≪解説≫ …」の順に並んでいる。≪解説≫ から次の問題までを
解説として取り、「設問N」の見出しで分ける。解答例の表の文字はページの上の方にあるのに本文の後ろに出てくるので、
≪解説≫ の見出しより上にある文字は捨てる。

出力：app_src/data/pm_book.json（Gitに入れない）… {問題id: [{s: 設問, t: 本文（段落は改行）}]}
"""
import json, re, sys, unicodedata
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "応用情報"
OUT = ROOT / "app_src" / "data" / "pm_book.json"

# PDF → 試験ID（徹底攻略の本は令和3年春期の部分だけ）
BOOKS = [("25年春.pdf", "25_haru"), ("26年春.pdf", "26_haru"), ("27年春.pdf", "27_haru"), ("28年春.pdf", "28_haru"),
         ("29年春.pdf", "29_haru"), ("30年春.pdf", "30_haru"), ("31年春.pdf", "31_haru"), ("元年秋.pdf", "01_aki"),
         ("徹底攻略 応用情報技術者 令和4年度.pdf", "03_haru")]
N = lambda s: unicodedata.normalize("NFKC", s)
NOISE = re.compile(r"^(\d{1,4}|付|録|A|Q|午後\s*解答と解説|午後\s*問題|付録\s*.*試験|.*応用情報技術者試験\s*午後.*)$")


def blocks(page):
    h = page.rect.height
    for b in sorted(page.get_text("blocks"), key=lambda b: (round(b[1]), b[0])):
        t = b[4].strip()
        if not t or b[1] < 30 or b[3] > h - 25:
            continue
        # 制御文字（選択肢記号の後ろの \x07 など）を消す。段落の始まりの全角空白は残す
        lines = [re.sub(r"[\x00-\x1f]", "", l).rstrip() for l in t.split("\n")]
        lines = [l for l in lines if l.strip() and not NOISE.match(N(l.strip()))]
        if lines:
            yield b[1], lines


def extract(path, eid):
    d = pymupdf.open(path)
    res, no, mode, buf = {}, 0, None, []
    pending = None

    def flush():
        if no and buf:
            res[f"{eid}-pm{no}"] = sections(buf)

    in_pm = False
    for page in d:
        txt = N(page.get_text())
        if re.match(r"\s*\d*\s*(索引|■著者)", txt):   # 本の巻末
            break
        # 午後の解答と解説の章に入ってから処理する（午前の章にも《解答》がある。表紙の目次は「ページ番号＋見出し」で始まらないので除く）
        in_pm = in_pm or bool(re.match(r"\s*\d+\s*午後\s*解答と解説", txt)) or bool(re.search(r"[≪《]出題趣旨[≫》]", txt))
        if not in_pm:
            continue
        exp_y = None
        for y, lines in blocks(page):
            joined = N("".join(lines))
            if "≪解説≫" in joined or "《解説》" in joined:
                mode, exp_y = "exp", y
                rest = re.split(r"[≪《]解説[≫》]", joined, 1)[1]
                if rest: buf.append(rest)
                continue
            # 平成25〜30年ごろの本は「問N 分野 《解答》 解答例の一覧 …に関する問題です。…」の形（出題趣旨・解説の見出しが無い）
            if re.search(r"[≪《]解答[≫》]", joined):
                flush(); buf = []
                m = re.search(r"問\s*(\d{1,2})", joined) or (pending and re.search(r"(\d{1,2})", pending))
                no = int(m.group(1)) if m else no + 1
                mode, pending = "ans2", None
                continue
            if mode == "ans2" and "問題です" in joined:
                mode, exp_y = "exp", y
            if "≪出題趣旨≫" in joined or "《出題趣旨》" in joined:
                flush(); buf = []
                m = re.search(r"問\s*(\d{1,2})", joined) or (pending and re.search(r"(\d{1,2})", pending))
                no = int(m.group(1)) if m else no + 1
                mode, pending = "aim", None
                continue
            if "≪解答例≫" in joined or "《解答例》" in joined:
                mode = "ans"; continue
            if re.fullmatch(r"問\s*\d{1,2}[^。]{0,40}", joined.replace("　", "")):
                pending = joined; continue
            if mode != "exp":
                continue
            if exp_y is not None and y < exp_y:   # 解答例の表の中の文字
                continue
            # 次の問題の見出し（「問N」の後の「情報セキュリティ」などの分野名だけの行）は本文に入れない
            if pending and len(joined) <= 16 and not joined.endswith("。"):
                continue
            buf.extend(lines)
    flush()
    return res


def sections(lines):
    """行を段落にまとめ、「設問N」で区切る。全角空白で始まる行・見出しらしい行で段落を改める。"""
    out = [{"s": "", "t": []}]
    brk = True
    for l in lines:
        # 見出しは「設問N」だけの行。本文中の「設問2（2）で求めた…」で始まる行は見出しにしない。
        # 見出しの後ろに付録の見出し文字の数字が付くことがあるので、設問番号は1桁だけ取る
        m = re.fullmatch(r"\s*設問\s*(\d)\d?\s*", l)
        if m:
            out.append({"s": f"設問{m.group(1)}", "t": []}); brk = True
            continue
        head = re.match(r"^(設問\s*\d+|[(（]\d+[)）]|空欄\s*[a-zA-Zア-ン]|[ア-ン](\s*[，,]\s*[ア-ン])*[\s　]|したがって)", l)
        t = out[-1]["t"]
        if brk or l.startswith("　") or head:
            t.append(l.strip("　 "))
        else:
            t[-1] += l
        # 「（1）」「空欄a」だけの行は見出しなので、次の行と同じ段落にする（太字にして表示）
        brk = False
    return [{"s": x["s"], "t": "\n".join(x["t"])} for x in out if x["t"]]


def main():
    allres = {}
    for name, eid in BOOKS:
        if sys.argv[1:] and eid not in sys.argv[1:]:
            continue
        r = extract(PDF / name, eid)
        allres.update(r)
        print(eid, len(r), sorted(int(k.split("pm")[1]) for k in r), sum(len(x["t"]) for v in r.values() for x in v))
    OUT.write_text(json.dumps(allres, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

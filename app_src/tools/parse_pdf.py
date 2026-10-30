"""PDFから抽出したテキスト(午前問題+解答解説)をパースしてJSON化する。"""
import json, re, sys, html
sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

BASE = Path(sys.argv[1])          # scratchpad
TXT = BASE / "txt"
IDX = BASE / "idx"
OUT = BASE / "past.json"

EXAMS = [  # (txtファイル, ap-siken id, 表示名, 開始行ヒント)
    ("25年春", "25_haru", "平成25年春期", 0),
    ("26年春", "26_haru", "平成26年春期", 0),
    ("27年春", "27_haru", "平成27年春期", 0),
    ("28年春", "28_haru", "平成28年春期", 0),
    ("29年春", "29_haru", "平成29年春期", 0),
    ("30年春", "30_haru", "平成30年春期", 0),
    ("31年春", "31_haru", "平成31年春期", 0),
    ("元年秋", "01_aki", "令和元年秋期", 0),
    ("徹底攻略 応用情報技術者 令和4年度", "03_haru", "令和3年春期", 0),
]

KANA = "アイウエ"
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")

NOISE = [
    re.compile(r"^\s*午前\s*(問題|解答と解説)\s*\d+\s*$"),
    re.compile(r"^\s*\d+\s*付?\s*録.*$"),
    re.compile(r"^\s*(録付|付録)\s*$"),
    re.compile(r"^\s*\d{1,3}\s*$"),
    re.compile(r"^\s*問\s*\d+\s*から\s*問\s*\d+\s*まで"),     # 「問51から問60までは，…」
]


def load_index(eid):
    h = (IDX / f"{eid}.html").read_text(encoding="utf-8", errors="ignore")
    rows = re.findall(r'<a href="q(\d+)\.html">問\d+</a><td[^>]*>(.*?)<td[^>]*>(.*?)<td', h)
    return {int(n): (html.unescape(re.sub("<[^>]+>", "", t)).strip(), html.unescape(c).strip()) for n, t, c in rows}


def clean_lines(lines):
    out = []
    for ln in lines:
        s = ln.rstrip().replace("​", "").replace("‌", "")
        # 右端に付く「午前 問題 583」等のページヘッダ
        s = re.sub(r"\s{2,}(午前\s*(問題|解答と解説)\s*\d+)\s*$", "", s)
        s = re.sub(r"\s{2,}(録付|付録|付|録)\s*$", "", s)
        s = re.sub(r"\s+(付|録)\s*$", "", s) if re.search(r"[。か]\s+(付|録)\s*$", s) else s
        if re.match(r"^\s*(付|録)\s*$", s):
            continue
        if any(p.match(s) for p in NOISE):
            continue
        out.append(s)
    return out


def section(lines, start_hint):
    q0 = next(i for i in range(start_hint, len(lines)) if re.match(r"^\s*Q\s*午前", lines[i]))
    a0 = next(i for i in range(q0, len(lines)) if re.match(r"^\s*A\s*午前", lines[i]))
    p0 = next((i for i in range(a0, len(lines)) if re.match(r"^\s*Q\s*午後", lines[i])), len(lines))
    # Q午後の直前に「午後 問題」の目次ページがあることがあるので余分は後で問番号で切る
    return lines[q0 + 1:a0], lines[a0 + 1:p0]


def merge_answer_heads(lines):
    """「問23   録」の次行に《解答》が来る崩れを1行に戻す。"""
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r"^\s*(問\s*\d+)[​‌]*\s*(録|付)?\s*$", ln)
        if m:
            j = i + 1
            while j < len(lines) and j <= i + 3 and not lines[j].strip():
                j += 1
            if j < len(lines) and re.match(r"^\s*[《≪]\s*解\s*答\s*[》≫]", lines[j]):
                out.append(m.group(1) + " " + lines[j].strip())
                i = j + 1
                continue
        out.append(ln)
        i += 1
    return out


def split_numbered(lines, pat_fn, maxn=80):
    """行頭に「問N」が順番に現れる位置で分割する。"""
    blocks, cur, n = {}, None, 1
    buf = []
    for ln in lines:
        m = pat_fn(n).match(ln) if n <= maxn else None
        if m:
            if cur is not None:
                blocks[cur] = buf
            cur, buf, n = n, [ln[m.end():]], n + 1
            continue
        if cur is not None:
            buf.append(ln)
    if cur is not None:
        blocks[cur] = buf
    return blocks


def q_pat(n):
    return re.compile(rf"^\s*問\s*{n}(?!\d)[​‌]*\s*")


def a_pat(n):
    return re.compile(rf"^\s*問\s*{n}(?!\d)[​‌]*\s*[《≪]\s*解\s*答\s*[》≫]\s*")


def join_para(lines):
    """改行で分断された日本語を段落単位に結合する。"""
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
    # 1行ごとに空行が入る組版では段落が細切れになるので、文の途中で切れたものは結合する
    merged = []
    for p in paras:
        if merged and not re.search(r"[。．）)」：:]$", merged[-1][-1]) and not re.match(r"^[アイウエ][，,、 ]", p[0]):
            merged[-1].extend(p)
        else:
            merged.append(p)
    paras = merged
    res = []
    for p in paras:
        t = ""
        for s in p:
            if t and re.search(r"[A-Za-z0-9,.)]$", t) and re.match(r"[A-Za-z0-9(]", s):
                t += " " + s
            else:
                t += s
        t = re.sub(r"[ \t]{2,}", " ", t)
        res.append(t)
    return res


GARBLE = re.compile(r"[ɐ-˿Ͱ-οЀ-ۿݐ-ݿᴀ-᷿①-⓿⼀-⿟ﬀ-﻿￰-￿\U0001D400-\U0001D7FF฀-๿ऀ-ॿ-]")
FIG = re.compile(r"図|表[^すし現示記面計]|グラフ|流れ図|次の(プログラム|擬似|疑似|式|関数)|空欄|〔|［|\[|‘|’|⋮|…")


def stem_text(stem):
    """問題文：ふつうの文は1段落につなげ、プログラムや表のように桁をそろえた行（大きな空白を含む行）は改行と字下げを残す。"""
    out, prose = [], []
    for ln in stem.split("\n"):
        if re.search(r"\S {3,}\S|^ {4,}\S|\t", ln) or re.match(r"^\{table:\d+\}$", ln.strip()):
            if prose: out += join_para(prose); prose = []
            out.append(ln.rstrip().replace("\t", "  ") if not ln.strip().startswith("{table:") else ln.strip())
        else:
            prose.append(ln)
    if prose: out += join_para(prose)
    return "\n".join(l for l in out if l.strip())


def table_rows_text(rows):
    """解説中の表は「a ｜ b ｜ c」の行にして段落として入れる。"""
    return "\n\n" + "\n".join(" ｜ ".join(c for c in r) for r in rows) + "\n\n"


def choices_from_table(body, tables):
    """選択肢が表（1列目がア〜エ）になっている組合せ問題を、文章の選択肢に直す。"""
    text = "\n".join(body)
    for m in re.finditer(r"\{tableref:([^}]+)\}", text):
        rows = tables.get(m.group(1), [])
        lab = {r[0].strip(): r for r in rows if r and r[0].strip() in tuple(KANA)}
        if len(lab) == 4:
            head = next((r for r in rows if r and r[0].strip() not in tuple(KANA)), None)
            cs = []
            for k in KANA:
                r = lab[k]
                if head and len(head) == len(r) and all(h.strip() for h in head[1:]):
                    cs.append("，".join(f"{h.strip()}：{v.strip()}" for h, v in zip(head[1:], r[1:])))
                else:
                    cs.append("　".join(v.strip() for v in r[1:]))
            return text[:m.start()], cs
    return None, None


# 「次の回路」「次のアローダイアグラム」のように、図や表が無いと解けない問題
NEEDS_FIGURE = re.compile(r"次の[^。，]{0,14}(回路|図|表|プログラム|流れ図|グラフ|状態遷移|ネットワーク|アローダイアグラム|E-R|UML|モデル|SQL|関係|クラス|木|ツリー|構成|手順|処理|擬似|疑似|仕様|条件|式|データ|ファイル|リスト|マトリクス|チャート|決定表)")


def parse_choices(body):
    text = "\n".join(body)
    # 選択肢マーカー: 行頭 or 空白の後の ア/イ/ウ/エ + 空白
    marks = []
    for k in KANA:
        marks.append([m.start() for m in re.finditer(rf"(?:(?<=^)|(?<=\n)|(?<=\s)){k}[\s　]", text)])
    # 最後のアから、順にイ・ウ・エが続く組を探す
    for a in reversed(marks[0]):
        try:
            i = min(x for x in marks[1] if x > a)
            u = min(x for x in marks[2] if x > i)
            e = min(x for x in marks[3] if x > u)
        except ValueError:
            continue
        stem = text[:a]
        cs = [text[a + 1:i], text[i + 1:u], text[u + 1:e], text[e + 1:]]
        return stem, cs
    return None, None


def norm(s):
    s = s.replace("\t", "")       # 斜体の文字の前に入るタブ（「2\tx」→「2x」）
    s = re.sub(r"(（\s*）\s*)+$", "", s)   # 大きなかっこが別の行に分かれて残ったもの
    s = re.sub(r"\s*\n\s*", "", s.strip()) if "\n" in s else s.strip()
    s = s.replace("　", " ")
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def main():
    allq = []
    stats = {}
    for fname, eid, label, hint in EXAMS:
        lines = (TXT / f"{fname}.txt").read_text(encoding="utf-8").splitlines()
        qs, ans = section(lines, hint)
        qs, ans = clean_lines(qs), merge_answer_heads(clean_lines(ans))
        qb = split_numbered(qs, q_pat)
        ab = split_numbered(ans, a_pat)
        idx = load_index(eid)
        tf = TXT / f"{fname}.tables.json"
        tables = json.loads(tf.read_text(encoding="utf-8")) if tf.exists() else {}
        ok = bad = 0
        for n in range(1, 81):
            title, cat = idx.get(n, ("", ""))
            item = {"id": f"{eid}-{n}", "exam": label, "eid": eid, "no": n, "title": title, "cat": cat,
                    "field": "T" if n <= 50 else ("M" if n <= 60 else "S")}
            a = ab.get(n)
            if a:
                m = re.match(r"\s*([アイウエ])", a[0])
                item["ans"] = KANA.index(m.group(1)) if m else None
                item["exp"] = join_para(a[1:] if m and not a[0][m.end():].strip() else [a[0][m.end():] if m else a[0]] + a[1:])
            if item.get("exp"):
                item["exp"] = join_para(re.sub(r"\{tableref:([^}]+)\}", lambda m: table_rows_text(tables.get(m.group(1), [])), "\n\n".join(item["exp"])).split("\n"))
            b = qb.get(n)
            flags = []
            tb = []
            if b:
                stem, cs = parse_choices(b)
                if stem is None:
                    stem, cs = choices_from_table(b, tables)
                if stem is None:
                    flags.append("nochoice")
                else:
                    def put(m):
                        rows = tables.get(m.group(1))
                        if not rows: return ""
                        tb.append(rows); return "\n{table:%d}\n" % (len(tb) - 1)
                    stem = re.sub(r"\{tableref:([^}]+)\}", put, stem)
                    item["q"] = stem_text(stem)
                    if tb: item["tb"] = tb
                    if re.search(r"(?m)^\s*(?:[A-Za-z0-9]{1,3}[ 　]+)+[A-Za-z0-9]{1,3}\s*$", stem):   # 図の中の文字だけが残った行
                        flags.append("fig")
                    item["c"] = [norm(re.sub(r"\{tableref:[^}]+\}", "", c)) for c in cs]
                    blob = item["q"] + "".join(item["c"])
                    if GARBLE.search(blob):
                        flags.append("garble")
                    fig_q = re.sub(r"表[^すし現示記面計]", "", item["q"]) if tb else item["q"]
                    if NEEDS_FIGURE.search(fig_q) and not tb:
                        flags.append("fig")
                    if FIG.search(fig_q) or re.search(r"(?m)^(?:[A-Za-z0-9]{1,3}[ 　]+){1,}[A-Za-z0-9]{1,3}$", item["q"]):
                        flags.append("fig")
                    if len(set(item["c"])) < 4:          # 選択肢が図で、文字だけ同じものが残った
                        flags.append("dupchoice")
                    if any(len(c) == 0 for c in item["c"]):
                        flags.append("empty")
                    if any(len(c) > 160 for c in item["c"]):
                        flags.append("long")
                    if len(item["q"]) < 6:
                        flags.append("short")
            else:
                flags.append("noq")
            if item.get("ans") is None:
                flags.append("noans")
            if item.get("exp") and GARBLE.search("".join(item["exp"])):
                flags.append("expgarble")
            item["flags"] = flags
            clean = not (set(flags) - {"expgarble"})
            item["ok"] = clean
            ok += clean; bad += (not clean)
            allq.append(item)
        stats[label] = (ok, bad, len(qb), len(ab))
    OUT.write_text(json.dumps(allq, ensure_ascii=False, indent=0), encoding="utf-8")
    for k, v in stats.items():
        print(k, "clean=%d flagged=%d qblocks=%d ablocks=%d" % v)


if __name__ == "__main__":
    main()

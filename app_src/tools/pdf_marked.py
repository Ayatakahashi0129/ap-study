"""PyMuPDF で PDF の文字を位置・大きさ付きで読み、書式の印を付けたテキストに変換する。
  {sup:…}／{sub:…} … 周りより小さく、上（下）にずれた文字（べき乗・添字）
  {ov:…}            … 文字のすぐ上に引かれた短い横線（否定・補集合の横棒）
  {tableref:ID}     … 罫線で囲まれた表（中身は別の JSON に保存）
出力は pdftotext -layout と同じく「見た目の1行＝1行」なので、parse_pdf.py / parse_autumn.py がそのまま読める。

使い方: python pdf_marked.py <PDF> <出力txt> <表のJSON> [開始ページ]
"""
import json, re, sys
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")


# 数式フォントの文字コードが壊れているPDF（秋期の解説）で、見た目どおりの文字に戻す
GLYPH = {"ఘ": "ρ", "ଵ": "1", "ଶ": "2"}
DASHED = set()   # 破線として描かれた横線 (x0, x1, y)


def hlines(page):
    """横線（線分・細い四角形）を集める。破線は DASHED にも記録する。"""
    out = []
    for d in page.get_drawings():
        dashed = bool(d.get("dashes")) and d.get("dashes") not in ("[] 0", "[]0", "")
        for it in d["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.y - q.y) < 0.6 and abs(q.x - p.x) >= 2:
                    seg = (min(p.x, q.x), max(p.x, q.x), (p.y + q.y) / 2)
                    out.append(seg)
                    if dashed: DASHED.add(seg)
            elif it[0] == "re":
                r = it[1]
                if r.height < 1.3 and r.width >= 2:
                    out.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
    return out


OV_OK = __import__("re").compile(r"[A-Za-z0-9０-９Ａ-Ｚ∪∩・+＋()（）\s\-−*×'′⊕¬]+")
SCRIPT_OK = __import__("re").compile(r"[A-Za-z0-9+\-−＋*()（）.,'′ ]{1,6}")


def page_text(page, pid, tables_out):
    # 表：罫線から検出し、範囲内の文字は本文から外す
    tbls = []
    try:
        for k, t in enumerate(page.find_tables().tables):
            rows = [[re.sub(r"\s+", " ", (c or "")).strip() for c in r] for r in t.extract()]
            rows = [r for r in rows if any(r)]
            flat = " ".join(c for r in rows for c in r)
            if __import__("re").search(r"解\s*答|問\s*\d", flat):   # 解答の見出しを巻き込んだ誤検出は捨てる
                continue
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                tid = f"{pid}_{k}"
                tables_out[tid] = rows
                tbls.append((pymupdf.Rect(t.bbox), tid))
    except Exception:
        pass
    lines = hlines(page)
    raw = page.get_text("rawdict")
    allsz = sorted(c_sp["size"] for b in raw["blocks"] for l in b.get("lines", []) for c_sp in l["spans"] for ch_ in c_sp["chars"] if ch_["c"].strip())
    body = allsz[len(allsz) // 2] if allsz else 10
    vis = []   # 見た目の行: [baseline, size, [chars]]
    small = [] # 小さい文字だけの行（上付き・下付き）。後で近くの行にくっつける
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            chars = []
            for sp in l["spans"]:
                for c in sp["chars"]:
                    x0, y0, x1, y1 = c["bbox"]
                    if c["c"] in "付録" and (x1 > page.rect.width - 45 or x0 < 45):
                        continue      # ページ端のつまみ見出し「付録」
                    if any(r.contains(pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)) for r, _ in tbls):
                        continue
                    chars.append({"c": GLYPH.get(c["c"], c["c"]), "x0": x0, "x1": x1, "y0": y0, "y1": y1, "size": sp["size"], "oy": c["origin"][1]})
            if not chars:
                continue
            if max(ch["size"] for ch in chars) < body * 0.8:
                small.append(chars); continue
            sizes = sorted(ch["size"] for ch in chars)
            main = sizes[len(sizes) // 2]
            base = sorted(ch["oy"] for ch in chars if ch["size"] >= main * 0.9)[0] if any(ch["size"] >= main * 0.9 for ch in chars) else chars[0]["oy"]
            for v in vis:
                if abs(v[0] - base) < max(2.5, main * 0.35):
                    v[2].extend(chars); v[1] = max(v[1], main); break
            else:
                vis.append([base, main, chars])
    for chars in small:
        oy = chars[0]["oy"]; x = (chars[0]["x0"] + chars[-1]["x1"]) / 2
        best = None
        for v in vis:
            d = v[0] - oy          # 正なら小さい文字の方が上（上付き）
            near = any(c["x0"] - v[1] * 3 <= x <= c["x1"] + v[1] * 3 for c in v[2])
            if near and -v[1] * 0.6 <= d <= v[1] * 0.9 and (best is None or abs(d) < abs(best[0])):
                best = (d, v)
        if best: best[1][2].extend(chars)
        else: vis.append([oy, max(c["size"] for c in chars), chars])
    for r, tid in tbls:
        vis.append([r.y0 + 1, 10, [{"c": "{tableref:%s}" % tid, "x0": r.x0, "x1": r.x1, "y0": r.y0, "y1": r.y0 + 8, "size": 10, "oy": r.y0 + 1, "tb": 1}]])
    vis.sort(key=lambda v: v[0])

    # 太字を「同じ文字をわずかにずらして2回描く」方式で表しているPDFがあるので、重なった同じ文字は1つにする
    for v in vis:
        v[2].sort(key=lambda ch: ch["x0"])
        kept = []
        for ch in v[2]:
            dup = next((k for k in kept[-3:] if k["c"] == ch["c"] and abs(k["x0"] - ch["x0"]) < ch["size"] * 0.35 and abs(k["oy"] - ch["oy"]) < ch["size"] * 0.35), None)
            if not dup: kept.append(ch)
        v[2] = kept
    # 分数：横線のすぐ上に分子、すぐ下に分母がある → {frac:分子|分母} を1文字として、数式の高さの行に置く
    allc = [c for v in vis for c in v[2] if not c.get("tb") and c["c"].strip()]
    for x0, x1, y in lines:
        if x1 - x0 < 3 or x1 - x0 > 160:
            continue
        inside = lambda c: x0 - 1.5 <= (c["x0"] + c["x1"]) / 2 <= x1 + 1.5 and not c.get("gone")
        num = [c for c in allc if inside(c) and 0.3 <= y - c["oy"] <= c["size"] * 0.45]
        den = [c for c in allc if inside(c) and c["size"] * 0.6 <= c["oy"] - y <= c["size"] * 1.3]
        if not num or not den:
            continue
        wn = max(c["x1"] for c in num) - min(c["x0"] for c in num); wd = max(c["x1"] for c in den) - min(c["x0"] for c in den)
        if (x1 - x0) < max(wn, wd) * 0.6 or (x1 - x0) > max(wn, wd) * 1.8 + 4:
            continue      # 線の長さが分子・分母の幅と合わないものは分数ではない
        lone = lambda grp: not any(abs(c["oy"] - grp[0]["oy"]) < 0.8 and not inside(c) and abs((c["x0"] + c["x1"]) / 2 - (x0 + x1) / 2) < (x1 - x0) / 2 + c["size"] * 1.2 for c in allc)
        if not (lone(num) and lone(den)):
            continue      # 分子・分母と同じ高さに隣の文字が続いている＝下線付きの文などで、分数ではない
        num.sort(key=lambda c: c["x0"]); den.sort(key=lambda c: c["x0"])
        for c in num + den: c["gone"] = True
        sz = max(c["size"] for c in num + den)
        tok = {"c": "{frac:%s|%s}" % ("".join(c["c"] for c in num), "".join(c["c"] for c in den)),
               "x0": x0, "x1": x1, "y0": y - sz, "y1": y + sz, "size": sz, "oy": y + sz * 0.3, "tb": 1}
        tgt = min(vis, key=lambda v: abs(v[0] - tok["oy"]) if any(not ch.get("gone") for ch in v[2]) else 1e9)
        tgt[2].append(tok)
    for v in vis:
        v[2] = [c for c in v[2] if not c.get("gone")]
    vis = [v for v in vis if v[2]]
    page_chars = [c for v in vis for c in v[2] if not c.get("tb") and c["c"].strip()]
    out_lines = []
    for base, main, chars in vis:
        chars.sort(key=lambda ch: ch["x0"])
        toks = []
        for ch in chars:
            kind = ""
            if not ch.get("tb") and ch["size"] < main * 0.8 and ch["c"].strip():
                if ch["oy"] < base - main * 0.15: kind = "sup"
                elif ch["oy"] > base + main * 0.08: kind = "sub"
            toks.append([ch, kind])
        i = 0
        while i < len(toks):
            if toks[i][1]:
                j = i
                while j + 1 < len(toks) and toks[j + 1][1] == toks[i][1]: j += 1
                if not SCRIPT_OK.fullmatch("".join(t[0]["c"] for t in toks[i:j + 1])):
                    for t in toks[i:j + 1]: t[1] = ""
                i = j + 1
            else:
                i += 1
        # 上線：文字の上端のすぐ上（0〜4pt）にあり、覆う文字の幅とほぼ同じ長さの横線
        ov_ranges = []
        top = min(ch["y0"] for ch, _ in toks)
        for x0, x1, y in lines:
            idx = [i for i, (ch, _) in enumerate(toks) if x0 - 1 <= (ch["x0"] + ch["x1"]) / 2 <= x1 + 1]
            while idx and not toks[idx[0]][0]["c"].strip(): idx.pop(0)      # 両端の空白は除く
            while idx and not toks[idx[-1]][0]["c"].strip(): idx.pop()
            if not idx:
                continue
            oy = min(toks[i][0]["oy"] for i in idx); sz = max(toks[i][0]["size"] for i in idx)
            span = toks[idx[-1]][0]["x1"] - toks[idx[0]][0]["x0"]
            # ベースラインから文字の高さ（0.75〜1.35倍）だけ上にある線を上線とみなす
            if any(x0 - 1 <= (c["x0"] + c["x1"]) / 2 <= x1 + 1 and -0.5 <= y - c["oy"] <= c["size"] * 0.6 for c in page_chars):
                continue     # 線の直上に文字がある＝分数の横線
            covered = "".join(toks[i][0]["c"] for i in idx)
            if not OV_OK.fullmatch(covered):
                continue
            if sz * 0.75 <= oy - y <= sz * 1.35 and abs((x1 - x0) - span) <= max(3, sz * 0.5) and idx == list(range(idx[0], idx[-1] + 1)):
                ov_ranges.append((idx[0], idx[-1]))
        ov_ranges = sorted(set(ov_ranges), key=lambda r: r[1] - r[0])
        ul_ranges = []
        segs = sorted([(x0, x1, y) for x0, x1, y in lines if 0.3 <= y - base <= main * 0.45], key=lambda s: (round(s[2], 1), s[0]))
        merged = []
        for x0, x1, y in segs:      # 同じ高さで隙間が小さい線分は1本の破線としてまとめる
            dash = 3 if (x0, x1, y) in DASHED else 1
            if merged and abs(merged[-1][2] - y) < 0.4 and x0 - merged[-1][1] < main * 0.5:
                merged[-1][1] = max(merged[-1][1], x1); merged[-1][3] += dash
            else:
                merged.append([x0, x1, y, dash])
        for x0, x1, y, n in merged:
            idx = [i for i, (ch, _) in enumerate(toks) if x0 - 1 <= (ch["x0"] + ch["x1"]) / 2 <= x1 + 1]
            while idx and not toks[idx[0]][0]["c"].strip(): idx.pop(0)
            while idx and not toks[idx[-1]][0]["c"].strip(): idx.pop()
            if not idx or __import__("re").search(r"[{問《》]|解答", "".join(toks[i][0]["c"] for i in idx)):
                continue      # 見出し（問N・《解答》）の枠線は下線ではない
            span = toks[idx[-1]][0]["x1"] - toks[idx[0]][0]["x0"]
            if abs((x1 - x0) - span) <= max(3, main * 0.6) and idx == list(range(idx[0], idx[-1] + 1)):
                ul_ranges.append((idx[0], idx[-1], "{dl:" if n >= 3 else "{ul:"))
        opens, closes = {}, {}
        for a, b in ov_ranges:
            opens.setdefault(a, []).append("{ov:"); closes.setdefault(b, []).append("}")
        for a, b, tag in ul_ranges:
            opens.setdefault(a, []).insert(0, tag); closes.setdefault(b, []).append("}")
        s, prev, cur = "", None, ""
        for i, (ch, kind) in enumerate(toks):
            if prev is not None:
                gap = ch["x0"] - prev["x1"]
                if gap > main * 1.5: sep = "   "
                elif gap > main * 0.3: sep = " "
                else: sep = ""
            else:
                sep = ""
            if kind != cur:
                if cur: s += "}"
                s += sep
                sep = ""
                if kind: s += "{%s:" % kind
                cur = kind
            s += sep + "".join(opens.get(i, [])) + ch["c"] + "".join(closes.get(i, []))
            prev = ch
        if cur: s += "}"
        out_lines.append(s.rstrip())
    return "\n".join(out_lines)


def main():
    pdf, out_txt, out_tbl = sys.argv[1:4]
    start = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    doc = pymupdf.open(pdf)
    tables = {}
    pages = [page_text(doc[i], f"p{i}", tables) for i in range(start, doc.page_count)]
    open(out_txt, "w", encoding="utf-8").write(("\n\f\n").join(pages))
    json.dump(tables, open(out_tbl, "w", encoding="utf-8"), ensure_ascii=False)
    print(pdf, "pages", len(pages), "tables", len(tables))


if __name__ == "__main__":
    main()

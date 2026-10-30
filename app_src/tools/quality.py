"""出題中の過去問の品質チェック。崩れていそうな問題を理由つきで洗い出し、件数を集計する。

使い方: python app_src/tools/quality.py [--list] [--json 出力先]
  改良前後で同じスクリプトを実行し、件数の変化で精度を確認する。
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent.parent
html = (ROOT / "AP科目A対策.html").read_text(encoding="utf-8")
DATA = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
QS = [q for q in DATA["questions"] if q["eid"]]

MARKUP = re.compile(r"\{(ov|sup|sub):[^{}]*\}")          # 修正後の書式（上線・上付き・下付き）
RULES = {
    # 否定・補集合の横棒が失われた疑い：「X はX の否定」のように同じ文字が並ぶ／否定を含む論理式
    "上線の欠落": lambda q, t: bool(re.search(r"([A-Za-z])\s*は\s*\1\s*の(否定|補集合)", t)) or
        (bool(re.search(r"否定|補集合|NOT", q["q"])) and bool(re.search(r"[A-Z]\s*[・∪∩+＋⊕]\s*[A-Z]", t)) and "{ov:" not in t),
    # 上付き文字（べき乗）が失われた疑い：2n, a2, 10−3, (1−X)2 など
    "べき乗の欠落": lambda q, t: bool(re.search(r"(?<![A-Za-z0-9])(2[nk]|[a-z]2|10\s*[−-]\s*\d|[)）]\s*\d(?![\d,.]))(?![A-Za-z])", re.sub(MARKUP, "", t)))
        and q["g"] in ("基礎理論", "アルゴリズムとプログラミング", "コンピュータ構成要素", "システム構成要素", "ソフトウェア", "ネットワーク"),
    # 表や図の中身が問題文から抜けている疑い
    "表・図の欠落": lambda q, t: bool(re.search(r"次の(表|図|条件|仕様|とおり|ような)|表の|図の|下表|〔[^〕]*〕\s*$", q["q"])) and not q.get("tb"),
    # OCR・文字化けの痕跡
    "文字化け": lambda q, t: bool(re.search(r"[ɐ-˿Ͱ-ϿЀ-ӿ؀-ۿ①-⓿⼀-⿟-ﬀ-﻿�]|ʢ|ᶃ|[ぁ-ん]{1}[A-Za-z]{1}[ぁ-ん]", t)),
    # 解説の数字・記号が抜けている（「＝  ）」のような空白の並び）
    "解説の欠落": lambda q, t: bool(re.search(r"[＝（(]\s{2,}[）)]|＝\s{2,}|\s{3,}[。，）]", "".join(q["e"]))),
    # 選択肢が空・極端に短い
    "選択肢の異常": lambda q, t: any(len(c.strip()) == 0 for c in q["c"]) or len(set(q["c"])) < 4,
}

def check(q):
    t = q["q"] + "\n" + "\n".join(q["c"])
    return [name for name, f in RULES.items() if f(q, t)]

if __name__ == "__main__":
    res = {q["id"]: check(q) for q in QS}
    bad = {k: v for k, v in res.items() if v}
    cnt = Counter(r for v in bad.values() for r in v)
    by_exam = defaultdict(int)
    for q in QS:
        if res[q["id"]]: by_exam[q["src"]] += 1
    print(f"過去問 {len(QS)}問中、要確認 {len(bad)}問（{len(bad)*100/len(QS):.1f}%）")
    for k, v in cnt.most_common(): print(f"  {k}: {v}")
    if "--list" in sys.argv:
        for q in QS:
            if res[q["id"]]: print(q["id"], res[q["id"]], q["q"][:50].replace("\n", " "))
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")

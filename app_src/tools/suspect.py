"""autumn.json の採用候補のうち、OCRの誤りが残っていそうな箇所を洗い出す（目視確認用）。"""
import json, re, sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SRC = Path(__file__).resolve().parent.parent
texts = []
for x in json.loads((SRC / "data/past.json").read_text(encoding="utf-8")):
    texts += [x.get("q", ""), *x.get("c", []), *x.get("exp", [])]
for x in json.loads((SRC / "data/original.json").read_text(encoding="utf-8")):
    texts += [x["q"], *x["c"], *x["exp"]]
aut = json.loads((SRC / "data/autumn.json").read_text(encoding="utf-8"))
for x in aut:
    texts += x["exp"]
big = Counter()
for t in texts:
    t = re.sub(r"\s", "", t)
    big.update(t[i:i + 2] for i in range(len(t) - 1))

out = []
for x in aut:
    if not x["ok"]:
        continue
    bad = []
    for part in [x["q"], *x["c"]]:
        t = re.sub(r"\s", "", part)
        for i in range(len(t) - 1):
            bg = t[i:i + 2]
            if big[bg] == 0 and re.search(r"[぀-ヿ一-鿿]", bg):
                bad.append(t[max(0, i - 3):i + 5])
        bad += re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z0-9])|[^\w\s，。、：；（）「」『』“”\"'・／/％%＝=＋+－\-×÷<>＜＞≦≧～~〔〕\[\]［］{}①-⑳.,:;!?？！*＊#＃&＆→←↑↓…ー─々〇○●◯^⁰¹²³⁴⁵⁶⁷⁸⁹⁻√|$￥\\]", part)
    if bad:
        out.append((x["id"], bad))
print(len(out), "件に要確認箇所")
for i, b in out:
    print(i, " / ".join(dict.fromkeys(b))[:200])

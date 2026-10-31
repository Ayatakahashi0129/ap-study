"""data/*.json と template.html から、単体で動く AP科目A対策.html を生成する。

使い方: python app_src/tools/build.py
"""
import json, random, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
SRC = Path(__file__).resolve().parent.parent
ROOT = SRC.parent
KANA = "アイウエ"

GROUPS = {
    "基礎理論": ["離散数学", "応用数学", "情報に関する理論", "通信に関する理論", "計測・制御に関する理論"],
    "アルゴリズムとプログラミング": ["データ構造", "アルゴリズム", "プログラミング", "プログラム言語", "その他の言語"],
    "コンピュータ構成要素": ["プロセッサ", "メモリ", "バス", "入出力デバイス", "入出力装置"],
    "システム構成要素": ["システムの構成", "システムの評価指標"],
    "ソフトウェア": ["オペレーティングシステム", "ミドルウェア", "ファイルシステム", "開発ツール", "オープンソースソフトウェア"],
    "ハードウェア": ["ハードウェア"],
    "ヒューマンインタフェース・マルチメディア": ["ユーザーインタフェース技術", "UX/UIデザイン", "マルチメディア技術", "マルチメディア応用"],
    "データベース": ["データベース方式", "データベース設計", "データ操作", "トランザクション処理", "データベース応用"],
    "ネットワーク": ["ネットワーク方式", "データ通信と制御", "通信プロトコル", "ネットワーク管理", "ネットワーク応用"],
    "セキュリティ": ["情報セキュリティ", "情報セキュリティ管理", "セキュリティ技術評価", "情報セキュリティ対策", "セキュリティ実装技術"],
    "システム開発技術": ["システム要件定義", "ソフトウェア要件定義", "システム方式設計", "ソフトウェア方式設計・詳細設計", "ソフトウェア構築", "統合テスト", "導入", "受入れ支援", "保守・廃棄"],
    "ソフトウェア開発管理技術": ["開発プロセス・手法", "知的財産適用管理", "開発環境管理", "構成管理・変更管理"],
    "プロジェクトマネジメント": ["プロジェクトマネジメント", "プロジェクトの統合", "プロジェクトのステークホルダ", "プロジェクトのスコープ", "プロジェクトの資源", "プロジェクトの時間", "プロジェクトのコスト", "プロジェクトのリスク", "プロジェクトの品質", "プロジェクトの調達", "プロジェクトのコミュニケーション"],
    "サービスマネジメント": ["サービスマネジメント", "サービスマネジメントシステム", "サービスマネジメントプロセス", "サービスの設計・移行", "サービスの運用", "ファシリティマネジメント"],
    "システム監査": ["システム監査", "内部統制"],
    "システム戦略": ["情報システム戦略", "業務プロセス", "ソリューションビジネス", "システム活用促進・評価"],
    "システム企画": ["システム化計画", "要件定義", "調達計画・実施"],
    "経営戦略": ["経営戦略手法", "マーケティング", "ビジネス戦略と目標・評価", "経営管理システム", "技術開発戦略の立案", "技術開発計画"],
    "ビジネスインダストリ": ["ビジネスシステム", "エンジニアリングシステム", "e-ビジネス", "民生機器", "産業機器"],
    "企業活動": ["経営・組織論", "業務分析・データ利活用", "会計・財務"],
    "法務": ["知的財産権", "セキュリティ関連法規", "労働関連・取引関連法規", "その他の法律・ガイドライン", "標準化関連"],
}
CAT2GROUP = {c: g for g, cs in GROUPS.items() for c in cs}


def group_of(cat):
    g = CAT2GROUP.get(cat)
    if not g:
        print("  ! 未分類のカテゴリ:", cat)
    return g or "その他"


def shuffle_original(q, rng):
    """オリジナル問題の正解位置が偏らないよう選択肢を並べ替え、解説中の記号も付け替える。"""
    perm = list(range(4))
    nums = [re.fullmatch(r"[\d,.]+(?:万円|円|%|個|倍)?", c) for c in q["c"]]
    if all(nums):                     # 数値の選択肢は本試験と同じく小さい順に並べる
        val = lambda c: float(re.sub(r"[^\d.]", "", c))
        perm.sort(key=lambda i: val(q["c"][i]))
    else:
        rng.shuffle(perm)             # perm[新位置] = 元の位置
    new_of = {old: new for new, old in enumerate(perm)}
    remap = lambda s: "".join(KANA[new_of[KANA.index(ch)]] if ch in KANA else ch for ch in s)
    q["c"] = [q["c"][o] for o in perm]
    q["ans"] = new_of[q["ans"]]
    exp = []
    for line in q["exp"]:
        line = re.sub(r"^([アイウエ](?:・[アイウエ])*)：", lambda m: remap(m.group(1)) + "：", line)
        line = re.sub(r"([アイウエ])(が正解)", lambda m: remap(m.group(1)) + m.group(2), line)
        line = re.sub(r"（([アイウエ])）", lambda m: "（" + remap(m.group(1)) + "）", line)
        exp.append(line)
    head = [l for l in exp if not re.match(r"^[アイウエ](・[アイウエ])*：", l)]
    tail = sorted([l for l in exp if re.match(r"^[アイウエ](・[アイウエ])*：", l)], key=lambda l: KANA.index(l[0]))
    q["exp"] = head[:1] + tail + head[1:]
    return q


def main():
    past = json.loads((SRC / "data/past.json").read_text(encoding="utf-8"))
    orig = json.loads((SRC / "data/original.json").read_text(encoding="utf-8"))
    cards = json.loads((SRC / "data/flashcards.json").read_text(encoding="utf-8"))

    qs = []
    for x in past:
        if not x["ok"]:
            continue
        qs.append({"id": x["id"], "src": x["exam"], "eid": x["eid"], "no": x["no"], "title": x["title"],
                   "cat": x["cat"], "g": group_of(x["cat"]), "f": x["field"],
                   "q": x["q"], "c": x["c"], "a": x["ans"], "e": x["exp"], **({"tb": x["tb"]} if x.get("tb") else {})})
    # 秋期（問題文はIPA公開PDFのOCR，分類は推定。tools/parse_autumn.py で生成）
    autumn = SRC / "data/autumn.json"
    if autumn.exists():
        for x in json.loads(autumn.read_text(encoding="utf-8")):
            if not x["ok"]:
                continue
            qs.append({"id": x["id"], "src": x["exam"], "eid": x["eid"], "no": x["no"], "title": x["title"],
                       "cat": x["cat"], "g": x["g"], "f": x["field"],
                       "q": x["q"], "c": x["c"], "a": x["ans"], "e": x["exp"]})
    # 令和4年春〜（IPA公開PDFのOCR＋解答例のみ。tools/parse_recent.py で生成）。図表で読めない問題は画像で出す
    recent = SRC / "data/recent.json"
    if recent.exists():
        for x in json.loads(recent.read_text(encoding="utf-8")):
            if not x["ok"]:
                continue
            img, only = x.get("img"), x.get("imgonly")
            qs.append({"id": x["id"], "src": x["exam"], "eid": x["eid"], "no": x["no"], "title": x["title"] if not only or len(x["title"]) > 4 else f"{x['exam']} 問{x['no']}",
                       "cat": x["cat"], "g": x["g"], "f": x["field"], "q": "" if only else x["q"], "c": ["", "", "", ""] if only else x["c"], "a": x["ans"],
                       "e": [f"正解は{KANA[x['ans']]}（IPA公表の解答例）。この年度は解説がないので，詳しくは下の「サイトで原文・解説を見る」で確認してください。"],
                       "free": 1, **({"img": img} if img else {}), **({"io": 1} if only else {})})
    # 目視確認による修正（data/corrections.json）：置換・差し替え・除外
    corr = json.loads((SRC / "data/corrections.json").read_text(encoding="utf-8"))
    for q in qs:
        c = corr.get(q["id"])
        if not c: continue
        for old, new in c.get("replace", []):
            q["q"] = q["q"].replace(old, new); q["title"] = q["title"].replace(old, new); q["c"] = [x.replace(old, new) for x in q["c"]]; q["e"] = [x.replace(old, new) for x in q["e"]]
        for k in ("q", "c", "e", "tb"):
            if k in c: q[k] = c[k]
    qs = [q for q in qs if not corr.get(q["id"], {}).get("exclude")]
    for q in qs:   # OCRで句点が落ちた「どれかここで」などを直す
        q["q"] = re.sub(r"(どれか|幾らか|何%か|何秒か|何秒後か|何サイクル必要となるか)(ここで)", r"\1。\2", q["q"])
        # 斜体の t がかっこの後ろに回った「fac（t n）」「in（t r）」を「fact（n）」「int（r）」に戻す
        fx = lambda x: re.sub(r"\b(fac|nex|in)（t\s*", r"\1t（", x)
        q["q"] = fx(q["q"]); q["c"] = [fx(x) for x in q["c"]]; q["e"] = [fx(x) for x in q["e"]]
        # PDFの合字（ll・fi）が抜けたりずれたりした英単語と，「::」の間に入った空白を戻す
        lig = lambda x: re.sub(r": :(?=[＝=0-9A-Fa-f])", "::", re.sub(r"fci ", "fic", re.sub(r"\bFirewal\b", "Firewall", re.sub(r"\bShel\b", "Shell",
              x.replace("cal by ", "call by ").replace("Chal enge", "Challenge").replace("El iptic", "Elliptic").replace("Ofcfi e", "Office")
               .replace("Matematical", "Mathematical").replace("Intelig ence", "Intelligence").replace("Inteligence", "Intelligence")))))
        q["q"] = lig(q["q"]); q["c"] = [lig(x) for x in q["c"]]; q["e"] = [lig(x) for x in q["e"]]; q["title"] = lig(q["title"])
        cc = lambda x: re.sub(r"[\x00-\x08\x0b-\x1f]", "", x)
        q["q"] = cc(q["q"]); q["c"] = [cc(x) for x in q["c"]]; q["e"] = [cc(x) for x in q["e"]]
    # 出典を試験の実施順に並べる（平成は1988＋年，令和は2018＋年）
    year = lambda eid: (int(eid[:2]) + (2018 if eid.startswith("0") else 1988), eid.endswith("aki"))
    qs.sort(key=lambda q: (year(q["eid"]), q["no"]))
    rng = random.Random(20251019)
    for i, x in enumerate(orig, 1):
        x = shuffle_original(dict(x), rng)
        qs.append({"id": f"orig-{i}", "src": "オリジナル（新傾向）", "eid": "", "no": i, "title": x["title"],
                   "cat": x["cat"], "g": group_of(x["cat"]), "f": x["field"],
                   "q": x["q"], "c": x["c"], "a": x["ans"], "e": x["exp"]})
    fc = [{"g": g, "f": f, "t": t, "d": d} for g, f, t, d in cards]

    guide = json.loads((SRC / "data/guide.json").read_text(encoding="utf-8"))
    data = {"questions": qs, "cards": fc, "guide": guide,"groups": {f: [g for g in GROUPS if any(q["g"] == g and q["f"] == f for q in qs)] for f in "TMS"}}
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = (SRC / "template.html").read_text(encoding="utf-8")
    out = ROOT / "AP科目A対策.html"
    out.write_text(tpl.replace("/*__DATA__*/null", js), encoding="utf-8")

    from collections import Counter
    print("問題数:", len(qs), Counter(q["f"] for q in qs), " オリジナル正解位置:", Counter(q["a"] for q in qs if q["id"].startswith("orig")))
    print("カード数:", len(fc), " 出力:", out, f"({out.stat().st_size // 1024} KB)")
    build_public(data, tpl)


def build_public(data, tpl):
    """GitHub Pages 用の公開版（リポジトリ直下の index.html）を作る。
    過去問の解説は参考書・解説PDFの文章なので、合言葉から作った鍵で AES-GCM 暗号化して埋め込む。
    合言葉は app_src/.passphrase（Gitに入れない）に置く。無ければランダムに作る。"""
    import base64, hashlib, os, secrets
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    pf = SRC / ".passphrase"
    if not pf.exists():
        alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
        pf.write_text("-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)), encoding="utf-8")
        print("合言葉を新しく作りました:", pf)
    # アプリ側の normPass と同じ規則でそろえる（全角→半角、各種ハイフン→「-」、空白除去）。BOM付き保存にも対応
    import unicodedata
    passphrase = unicodedata.normalize("NFKC", pf.read_text(encoding="utf-8-sig"))
    passphrase = re.sub(r"\s+", "", re.sub("[‐‑‒–—―−ーｰ－﹣]", "-", passphrase))

    pub = json.loads(json.dumps(data, ensure_ascii=False))
    hidden = {}
    for q in pub["questions"]:
        if q.pop("free", 0):               # 解説が「正解は○」だけの問題は暗号化しない
            continue
        if q["eid"]:                       # 過去問（解説が参考書・解説PDF由来）
            hidden[q["id"]] = q["e"]
            q["e"], q["lk"] = [], 1
    salt, iv, iters = os.urandom(16), os.urandom(12), 600_000
    key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iters, dklen=32)
    ct = AESGCM(key).encrypt(iv, json.dumps(hidden, ensure_ascii=False).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    pub["locked"] = {"salt": b64(salt), "iv": b64(iv), "iter": iters, "ct": b64(ct)}
    pub["public"] = 1

    js = json.dumps(pub, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = ROOT / "index.html"
    out.write_text(tpl.replace("/*__DATA__*/null", js), encoding="utf-8")
    print("公開版:", out, f"({out.stat().st_size // 1024} KB, 暗号化した解説 {len(hidden)}問)")


if __name__ == "__main__":
    main()

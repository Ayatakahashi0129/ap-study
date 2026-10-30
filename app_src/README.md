# 応用情報 科目A対策アプリ（ソース）

完成品は 1 つ上のフォルダの `AP科目A対策.html`（ダブルクリックでブラウザが開き、オフラインで使えます）。

## 構成
- `data/past.json` … `応用情報/*.pdf`（平成25〜31年春・令和元年秋・令和3年春）から抽出した午前問題・正解・解説。`ok:false` は図表あり/読取り不良のため出題対象外
- `data/autumn.json` … 秋期（平成26〜30年秋・令和2年10月・令和3年秋）。問題文はIPA公開の問題PDFをWindows OCRで読み取ったもの、正解はIPAの解答例、解説は `応用情報/◯年秋.pdf`。`tools/parse_autumn.py` で生成
- `data/autumn_fix.json` … 秋期OCR結果の目視校正（除外・置換）
- `data/original.json` … 令和4〜7年度の出題テーマを踏まえたオリジナル問題（`ans` は 0=ア … 3=エ）
- `data/guide.json` … 「要点解説」ページのテーマ。`b` は表示ブロックの配列（`key` これだけ覚える / `svg` 図 / `eg` たとえると / `p` 段落 / `table` 表 / `list` 箇条書き / `f` 公式 / `trap` ひっかけ注意 / `tip` 覚え方）。図は `["svg", 幅, 高さ, [部品...], 説明]` で、部品の書き方は template.html の `diagram()` のコメントを参照。
  図を足すときの決まり：説明文は図の中に書かずキャプションへ／矢印には何が流れるかを書く／色は注目点（a）と良し悪し（ok・ng）だけ。
  グラフは系列色 `s1`〜`s3`（データ可視化スキルの検証スクリプトで明暗両方の背景に対し合格済み）を順番どおりに使い、`dot`・`bar` の最後の引数にホバー時の説明を書き、2系列以上なら `key` で凡例を付ける、`kw` は関連問題を探すキーワード
- `data/flashcards.json` … 暗記カード `[分類, 分野(T/M/S), 用語, 説明]`
- `template.html` … アプリ本体
- `tools/build.py` … 上記を埋め込んで `AP科目A対策.html` を生成
- `tools/parse_pdf.py` … PDF→JSON 抽出スクリプト（pdftotext の出力と ap-siken.com の年度別一覧を入力に使用）

## 問題やカードを追加したら
```
python app_src/tools/build.py
```

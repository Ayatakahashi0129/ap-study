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
- `tools/parse_pdf.py` … PDF→JSON 抽出スクリプト（下の書式付きテキストと ap-siken.com の年度別一覧を入力に使用）
- `tools/pdf_marked.py`・`tools/extract_all.py` … PyMuPDF で PDF を読み、文字の大きさ・位置と罫線から書式を復元したテキストを作る。
  `{sup:}` 上付き、`{sub:}` 下付き、`{ov:}` 否定・補集合の横棒、`{ul:}`／`{dl:}` 実線／破線の下線（主キー／外部キー）、`{frac:分子|分母}` 分数、`{tableref:}` 表
- `data/corrections.json` … 元PDFの画像と見比べて直した問題（置換・差し替え・除外）
- `tools/quality.py`・`tools/gt_sample.py`・`tools/ui_test.js` … 品質チェック、元PDF画像との見比べ用サンプル出力、ブラウザでの動作テスト（全問を解いて判定・表示を確認）

## 端末間の同期
記録画面で Google ログインすると、学習記録を Firebase（Firestore）の `users/{uid}` 文書（`state` にJSON文字列、`pass` に合言葉）に保存し、同じアカウントの端末どうしで自動的にマージする（解答は新しい方、カードは更新時刻が新しい方、履歴は和集合）。他端末の書き込みは onSnapshot で即時に取り込む。

Firebase コンソール（プロジェクト `ap-study-f809d`）で必要な設定：
1. Authentication → ログイン方法 → Google を有効にする
2. Authentication → 設定 → 承認済みドメイン に `ayatakahashi0129.github.io` を追加
3. Firestore Database を作成し、ルールに `app_src/firestore.rules` の内容を貼って公開

## 問題やカードを追加したら
```
python app_src/tools/build.py
```

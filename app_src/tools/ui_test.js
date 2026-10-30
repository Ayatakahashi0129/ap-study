// ブラウザの開発者ツール（またはテスト用ブラウザ）で実行する動作テスト。
// 指定した問題を「学習モード」で順に解き、正解の判定・解説の表示・表示崩れの兆候を集計する。
// 使い方: await runUiTest(["25_haru-1", ...])
async function runUiTest(ids){
  window.alert = ()=>{}; window.confirm = ()=>true;
  const rows = [];
  const list = ids.map(id=>QBY[id]).filter(Boolean);
  startQuiz(list, {mode:"study", title:"動作テスト"});
  for (let i = 0; i < list.length; i++) {
    const q = QBY[session.list[session.i]];
    const wrong = (q.a + 1) % 4, pick = i % 2 ? wrong : q.a;          // 正解と不正解を交互に選ぶ
    document.querySelector(`.choice[data-i="${pick}"]`).click();
    const app = document.querySelector("#app");
    const verdict = app.querySelector(".verdict")?.textContent || "";
    const stem = app.querySelector(".stem"), choices = [...app.querySelectorAll(".choice span:last-child")].map(e=>e.innerHTML);   // 上付き等の書式も含めて比べる
    rows.push({
      id: q.id,
      判定OK: (pick === q.a) === verdict.startsWith("正解"),
      解説あり: (app.querySelector(".exp")?.textContent || "").trim().length > 10,
      上線: stem.querySelectorAll(".ov").length + app.querySelectorAll(".choice .ov").length,
      上付き: app.querySelectorAll(".stem sup, .choice sup").length,
      表: app.querySelectorAll(".stem table").length,
      書式残り: /\{(ov|sup|sub|table):/.test(app.textContent),          // 書式記号がそのまま見えている
      選択肢重複: new Set(choices).size < 4,
    });
    if (i < list.length - 1) next();
  }
  next();                                                                // 結果画面へ
  const score = document.querySelector(".score")?.textContent;
  return {出題: rows.length, 判定一致: rows.filter(r=>r.判定OK).length, 解説あり: rows.filter(r=>r.解説あり).length,
          書式残り: rows.filter(r=>r.書式残り).length, 選択肢重複: rows.filter(r=>r.選択肢重複).map(r=>r.id),
          上線あり: rows.filter(r=>r.上線).map(r=>r.id), 上付きあり: rows.filter(r=>r.上付き).map(r=>r.id), 表あり: rows.filter(r=>r.表).map(r=>r.id), 結果画面の得点: score};
}

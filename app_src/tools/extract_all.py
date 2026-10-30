"""応用情報/ の全PDFを pdf_marked.py で書式付きテキストに変換する（parse_pdf.py / parse_autumn.py の入力）。
使い方: python extract_all.py <出力先(scratch)>   → <出力先>/txt/*.txt と *.tables.json
"""
import subprocess, sys
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(sys.argv[1]) / "txt"; OUT.mkdir(parents=True, exist_ok=True)
for pdf in sorted((ROOT / "応用情報").glob("*.pdf")):
    start = 0
    if "徹底攻略" in pdf.name:       # 本は付録の令和3年度春期だけを使う
        doc = pymupdf.open(pdf)
        start = next(i for i in range(600, doc.page_count) if "Q" in doc[i].get_text() and "午前" in doc[i].get_text() and "問1" in doc[i].get_text()) - 2
    name = pdf.stem
    subprocess.run([sys.executable, str(Path(__file__).with_name("pdf_marked.py")), str(pdf), str(OUT / f"{name}.txt"), str(OUT / f"{name}.tables.json"), str(start)], check=True)

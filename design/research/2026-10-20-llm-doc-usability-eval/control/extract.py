import sys
from pathlib import Path

sys.path.insert(0, "tools/docs")
from extract_doc_page import extract_page

src, out = Path(sys.argv[1]), Path(sys.argv[2])
for f in sorted(src.glob("*.html")):
    lines = extract_page(f)
    (out / (f.stem + ".txt")).write_text("\n".join(f"LINE {i}: {line}" for i, line in enumerate(lines, 1)) + "\n")
    print(f.stem, len(lines))

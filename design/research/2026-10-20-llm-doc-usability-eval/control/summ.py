import collections
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
rows = collections.defaultdict(list)
for f in sorted(out.glob("*.json")):
    cond, prod, *rest = f.stem.split("--")
    page = "/".join(rest[:-1])
    d = json.loads(f.read_text())
    types = collections.Counter(x["type"] for x in d["findings"])
    rows[(prod, page, cond)].append((d["overall_verdict"], len(d["findings"]), dict(types)))
for k in sorted(rows):
    print(*k, "|", " ; ".join(f"{v} n={n}" for v, n, _ in rows[k]))

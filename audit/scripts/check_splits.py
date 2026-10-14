"""Random spot-check: split DXFs open, hold geometry, bbox plausible."""
import hashlib
import json
import random
import sys
from pathlib import Path

import ezdxf

run = Path(sys.argv[1])
sample_n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
feats = json.loads((run / "intermediate" / "features.json").read_text(encoding="utf-8"))
random.seed(8)
ids = random.sample(sorted(feats), min(sample_n, len(feats)))
bad = []
for cid in ids:
    digest = hashlib.sha1(cid.encode()).hexdigest()
    path = run / "splits_all" / f"{digest}.dxf"
    doc = ezdxf.readfile(str(path))
    ents = list(doc.modelspace())
    if not ents:
        bad.append((cid, "empty modelspace"))
        continue
    types = {e.dxftype() for e in ents}
    if not types & {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "SPLINE", "INSERT"}:
        bad.append((cid, f"no geometry types: {sorted(types)}"))
    f = feats[cid]
    print(f"{cid}: ents={len(ents)} types={sorted(types)[:6]} "
          f"W={f['width']:.0f} H={f['height']:.0f} layers={sorted({e.dxf.layer for e in ents})[:4]}")
print(f"--- checked {len(ids)}, bad {len(bad)}")
for entry in bad:
    print("BAD:", entry)

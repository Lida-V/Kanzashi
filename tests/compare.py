# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Compares two results of tests/regress.py. Exit code 0 when they are the same.

python tests/compare.py before.json after.json"""

import json
import sys


def walk(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s/%s: only in %s" % (path, k, "the first" if k in a else "the second"))
            else:
                walk(a[k], b[k], path + "/" + str(k), out)
    elif a != b:
        out.append("%s: %r != %r" % (path, a, b))


a = json.load(open(sys.argv[1], encoding="utf-8"))
b = json.load(open(sys.argv[2], encoding="utf-8"))
diff = []
walk(a.get("steps"), b.get("steps"), "", diff)
errors = [k for k, v in b["steps"].items() if isinstance(v, dict) and "error" in v]
print("steps", len(b["steps"]), "differences", len(diff), "steps with an error", errors)
for d in diff[:40]:
    print(" ", d.encode("ascii", "backslashreplace").decode())
sys.exit(1 if diff or errors else 0)

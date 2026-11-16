# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Tells whether the hair that got the strand UV from Kanzashi is still whole and still has that UV:

    blender -b model.blend --python scripts/kanzashi_guard.py -- [--report guard.json]

Run it before and after any step of another tool that touches the hair (splitting into parts, joining, unwrapping,
retexturing). The last line is KANZASHI_GUARD {...}; the exit code is 1 when a hair was split, changed, or lost its
strand UV. Nothing is saved."""

import argparse
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "..")):
    if os.path.isfile(os.path.join(cand, "kanzashi", "guard.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break
from kanzashi import guard  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])
    r = guard.check(list(bpy.data.objects))
    if not r["marked"]:
        r["note"] = "no hair with the mark of the strand UV in this file"
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
    print("KANZASHI_GUARD " + json.dumps(r, ensure_ascii=False))
    sys.exit(0 if r["ok"] else 1)


main()

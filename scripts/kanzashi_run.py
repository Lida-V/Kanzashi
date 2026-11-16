# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Kanzashi without the panel: strands -> UV per strand -> check -> (export) -> saved as a NEW file.

    blender -b model.blend --python kanzashi_run.py -- --out model_kanzashi.blend
    blender -b model.blend --python kanzashi_run.py -- --hair Hair --hair Bangs --out out.blend --export hair.fbx --report r.json

The opened file is never saved; --out must not exist yet. Without --hair, meshes whose name (or whose materials'
names) say hair are taken. The package "kanzashi" is looked for next to this file and one folder up (the repository)."""

import argparse
import json
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "..")):
    if os.path.isfile(os.path.join(cand, "kanzashi", "tree.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break
from kanzashi import rewire as R  # noqa: E402
from kanzashi import strand_uv as UV  # noqa: E402
from kanzashi import swap as SW  # noqa: E402
from kanzashi import tree as TR  # noqa: E402

WORDS = ("hair", "bangs", "braid", "ponytail", "sidelock", "ahoge", "髪", "前髪", "毛")
NOT_WORDS = ("flower", "acc_", "pin", "ribbon", "tiara", "outline", "hairband", "chain", "飾")


def looks_like_hair(ob):
    if ob.type != "MESH" or len(ob.data.polygons) == 0:
        return False
    name = ob.name.lower()
    if any(w in name for w in NOT_WORDS):
        return False
    if any(w in name for w in WORDS):
        return True
    slots = {
        i for i, s in enumerate(ob.material_slots) if s.material and any(w in s.material.name.lower() for w in WORDS)
    }
    if not slots:
        return False
    mi = np.empty(len(ob.data.polygons), dtype=np.int32)
    ob.data.polygons.foreach_get("material_index", mi)
    return float(np.isin(mi, list(slots)).mean()) >= 0.6


def fail(msg, code=1):
    print("KANZASHI " + json.dumps(dict(ok=False, error=msg), ensure_ascii=False))
    sys.exit(code)


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="kanzashi_run.py")
    ap.add_argument("--hair", action="append", default=[], help="name of a hair mesh (repeat); default: found by name")
    ap.add_argument("--out", help="new .blend to save the result to (must not exist)")
    ap.add_argument("--export", help="FBX or GLB of the hair with the strand UV only")
    ap.add_argument("--report", help="JSON report")
    ap.add_argument("--cap-len", type=float, default=0.40, help="rings longer than this (m) count as the melted cap")
    ap.add_argument("--no-uv", action="store_true", help="strands only")
    a = ap.parse_args(argv)
    for p in (a.out, a.export, a.report):
        if p and os.path.exists(p):
            fail("already exists (nothing is overwritten): %s" % p)
    if not a.out and not a.export and not a.report:
        fail("give --out, --export or --report (otherwise nothing would be kept)")
    view = bpy.context.view_layer
    if a.hair:
        missing = [n for n in a.hair if n not in bpy.data.objects]
        if missing:
            fail("no such object: %s" % ", ".join(missing))
        hairs = [bpy.data.objects[n] for n in a.hair]
    else:
        hairs = [o for o in view.objects if looks_like_hair(o)]
    if not hairs:
        fail("no hair mesh found; name them with --hair")
    crown = None  # the highest point of the hairs
    for h in hairs:
        co = np.empty(len(h.data.vertices) * 3, dtype=np.float32)
        h.data.vertices.foreach_get("co", co)
        M = np.array(h.matrix_world)
        w = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
        i = int(np.argmax(w[:, 2]))
        if crown is None or w[i, 2] > crown[2]:
            crown = w[i]
    rep = dict(ok=True, hairs=[], crown=[float(x) for x in crown])
    done = []
    for h in hairs:
        name = "LS_Wires_" + h.name
        h["lw_wires"] = name
        wires = R.ensure_wires(name, bpy.context.scene.collection)
        one = dict(name=h.name)
        try:
            st = TR.detect_and_bind(h, wires, tuple(float(x) for x in crown), cap_len=a.cap_len)
            one["wires"] = int(st["wires"])
            one["filled_faces"] = int(UV.fill_strandless(h.data))
            one["rest_shift_mm"] = round(TR.rest_shift(h) * 1000, 4)
            if not a.no_uv:
                uv = UV.strand_uv_auto(h, wires)
                one["uv"] = dict(
                    islands=uv["strips"],
                    way=uv["way"],
                    folded=uv["folded"],
                    squashed=uv["squashed"],
                    trouble_share=round(uv["share"], 5),
                )
            done.append(h)
        except Exception as e:  # this hair is left out; the others go on
            one["error"] = repr(e)
            rep["ok"] = False
        rep["hairs"].append(one)
    UV.drop_unused_groups()
    if done and not a.no_uv:
        UV.pack_together(done)
        c = UV.uv_check(done)
        rep["check"] = c
        if a.export:
            if c["ok"]:
                rep["export"] = SW.export_for_texture(done, os.path.abspath(a.export))
            else:
                rep["export"] = "skipped: the UV check failed"
                rep["ok"] = False
    if a.out:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.out), copy=True)
        rep["saved"] = os.path.abspath(a.out)
    if a.report:
        json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("KANZASHI " + json.dumps(rep, ensure_ascii=True, default=str))
    sys.exit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()

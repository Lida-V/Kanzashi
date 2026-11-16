# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Runs the whole of Kanzashi on a .blend and writes what came out as numbers and hashes, so that two versions of the
code can be compared on the same file (tests/compare.py). The opened file is never saved.

    blender -b hair.blend --python tests/regress.py -- --out result.json

Steps: register hair, detect (when not detected yet), repaint some faces, bend one wire, strand UV, check, swap and
back, export, apply the shape. A step that fails is recorded with its error and the next ones still run."""
import argparse
import hashlib
import importlib
import json
import os
import sys
import tempfile

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import kanzashi  # noqa: E402

MODULES = [m for name, m in sorted(sys.modules.items()) if name.startswith(("kanzashi", "lida_hair")) and m is not None]


def find(name):
    """The function or value of that name, in whichever module of Kanzashi has it."""
    for extra in ("kanzashi.panel", "kanzashi.tree", "kanzashi.rewire", "kanzashi.i18n"):
        try:
            importlib.import_module(extra)
        except ImportError:
            pass
    for mod_name, mod in sorted(sys.modules.items()):
        if mod is not None and mod_name.startswith(("kanzashi", "lida_hair", "panel")) and hasattr(mod, name):
            return getattr(mod, name)
    raise AttributeError(name)


def op(*names):
    """The operator, by its new name or its old one."""
    for group, name in names:
        ns = getattr(bpy.ops, group)
        if hasattr(getattr(bpy.types, "%s_OT_%s" % (group.upper(), name), None), "bl_idname") or name in dir(ns):
            return getattr(ns, name)
    raise AttributeError(str(names))


def md5(a, digits=None):
    a = np.asarray(a)
    if digits is not None:
        a = np.round(a.astype(np.float64), digits) + 0.0
    return hashlib.md5(np.ascontiguousarray(a).tobytes()).hexdigest()[:12]


def co_of(me):
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def face_attr(me, name):
    a = np.empty(len(me.polygons), dtype=np.int32)
    me.attributes[name].data.foreach_get("value", a)
    return a


def mesh_state(h):
    me = h.data
    out = dict(verts=len(me.vertices), faces=len(me.polygons), co=md5(co_of(me), 5))
    if "lw_strand" in me.attributes:
        s = face_attr(me, "lw_strand")
        out.update(strands=int(len(np.unique(s))), strand_hash=md5(s))
    if "LW_StrandUV" in me.uv_layers:
        uv = np.empty(len(me.loops) * 2, dtype=np.float32)
        me.uv_layers["LW_StrandUV"].data.foreach_get("uv", uv)
        out.update(uv_hash=md5(uv, 4), uv_mean=[round(float(x), 4) for x in uv.reshape(-1, 2).mean(0)])
    wires = bpy.data.objects.get(h.get("lw_wires", ""))
    if wires is not None:
        out["wires"] = len(wires.data.splines)
    return out


def shown_state(h):
    ev = h.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    co = co_of(ev)
    return dict(verts=len(co), co=md5(co, 4), mean=[round(float(x), 5) for x in co.mean(0)])


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        lang = find("set_choice")
        lang("JA", save=False)
    except Exception:
        pass
    kanzashi.register()
    ctx = bpy.context
    sc = ctx.scene
    rep = dict(file=os.path.basename(bpy.data.filepath), steps={})

    def step(name, fn):
        try:
            rep["steps"][name] = fn()
        except Exception as e:
            rep["steps"][name] = dict(error=repr(e)[:300])
        print("REGRESS", name, json.dumps(rep["steps"][name], ensure_ascii=True, default=str)[:400])

    registered = find("registered")

    def hairs():
        return registered(ctx)

    def s_register():
        r = op(("kanzashi", "auto"), ("lida", "hs_auto"))()
        return dict(result=sorted(r), hairs=[h.name for h in hairs()])

    def s_detect():
        if all("lw_strand" in h.data.attributes for h in hairs()):
            return dict(skipped="already detected", hairs={h.name: mesh_state(h) for h in hairs()})
        r = op(("kanzashi", "detect"), ("lida", "hs_detect"))("EXEC_DEFAULT")
        return dict(result=sorted(r), hairs={h.name: mesh_state(h) for h in hairs()})

    def s_repaint():
        out = {}
        PAL = find("PAL")
        apply_hair = find("apply_hair")
        for h in hairs():
            me = h.data
            s = face_attr(me, "lw_strand")
            ids, counts = np.unique(s[s >= 0], return_counts=True)
            order = ids[np.argsort(-counts, kind="stable")]
            src, dst = int(order[0]), int(order[1])
            faces = np.flatnonzero(s == src)[:20]
            ca = me.color_attributes["lw_strand_col"]
            rgb = tuple(float(x) for x in PAL[dst]) + (1.0,)
            for fi in faces:
                p = me.polygons[int(fi)]
                for li in range(p.loop_start, p.loop_start + p.loop_total):
                    ca.data[li].color = rgb
            me.update()
            r = apply_hair(ctx, h)
            out[h.name] = dict(src=src, dst=dst, result={k: (int(v) if isinstance(v, (int, np.integer)) else str(v)[:60]) for k, v in dict(r or {}).items()},
                               state=mesh_state(h))
        return out

    def s_bend():
        out = {}
        for h in hairs():
            wires = bpy.data.objects.get(h.get("lw_wires", ""))
            before = shown_state(h)
            sp = wires.data.splines[0]
            pts = sp.bezier_points if len(sp.bezier_points) else sp.points
            p = pts[len(pts) - 1]
            p.co[0] += 0.02
            wires.data.update_tag()
            ctx.view_layer.update()
            out[h.name] = dict(before=before, after=shown_state(h))
        return out

    def s_uv():
        r = op(("kanzashi", "uv"), ("lida", "hs_uv"))("EXEC_DEFAULT")
        return dict(result=sorted(r), check=sc.get("lida_hs_uvcheck", sc.get("kanzashi_uvcheck", "")), hairs={h.name: mesh_state(h) for h in hairs()})

    def s_check():
        c = find("uv_check")(hairs())
        return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in c.items() if isinstance(v, (int, float, bool, str))}

    def s_swap():
        f = op(("kanzashi", "uvswap"), ("lida", "hs_uvswap"))
        r = f("EXEC_DEFAULT", on=True)
        mats = {h.name: [m.name if m else None for m in h.data.materials] for h in hairs()}
        text = sc.get("lida_hs_swapcheck", sc.get("kanzashi_swapcheck", ""))
        active = {h.name: h.data.uv_layers.active.name for h in hairs()}
        r2 = f("EXEC_DEFAULT", on=False)
        mats2 = {h.name: [m.name if m else None for m in h.data.materials] for h in hairs()}
        return dict(on=sorted(r), check=text, materials=mats, active=active, off=sorted(r2), materials_back=mats2)

    def s_export():
        path = os.path.join(tempfile.mkdtemp(prefix="kanzashi_regress_"), "hair.fbx")
        info = find("export_for_texture")([h for h in hairs() if "LW_StrandUV" in h.data.uv_layers], path)
        return dict(faces=int(info["faces"]), exists=os.path.isfile(path), left_objects=len(bpy.data.objects))

    def s_apply():
        r = op(("kanzashi", "finalize"), ("lida", "hs_finalize"))("EXEC_DEFAULT")
        return dict(result=sorted(r), hairs={h.name: dict(state=mesh_state(h), modifiers=[m.type for m in h.modifiers],
                                                          attrs=sorted(x.name for x in h.data.attributes if x.name.startswith("lw_"))) for h in hairs()})

    for name, fn in (("register", s_register), ("detect", s_detect), ("repaint", s_repaint), ("bend", s_bend), ("uv", s_uv),
                     ("check", s_check), ("swap", s_swap), ("export", s_export), ("apply", s_apply)):
        step(name, fn)
    kanzashi.unregister()
    rep["steps"]["unregister"] = "ok"
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)
    print("REGRESS written", a.out)


main()

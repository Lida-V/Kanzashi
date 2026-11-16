# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""For agents: which strands of a Kanzashi hair pass into the body, and a careful repair by the wires.

This is not part of the add-on. It needs a hair whose strands are detected (kanzashi_run.py) and still have their
wires (not applied yet). The opened file is never saved; outputs must be new paths.

    blender -b k.blend --python hair_penetration.py -- list
    blender -b k.blend --python hair_penetration.py -- check --against Body --report pen.json --render-dir pen_img
    blender -b k.blend --python hair_penetration.py -- fix --against Body --out k_fixed.blend --report fix.json

list   the meshes of the file with their sizes, to choose what the hair is tested against.
check  per strand: how deep and how much of it lies inside the meshes given by --against, where along the strand,
       and whether it is the tip, the middle (the strand passes through) or the root side. Pictures with the
       buried strands in red when --render-dir is given.
fix    moves the wire of each buried strand outward, a little more than the depth, smoothly along the wire, and
       checks again (a few rounds). Only strands no deeper than --max-depth-mm are touched; the others are listed
       for the user. Saves a NEW file. The strands move as if the user had dragged their handles.

Method. Points on every face of the bent hair (4 per triangle) are tested against each partner: the nearest
surface point gives the distance, and rays in several directions vote on inside or outside (the count of surface
crossings is odd inside a closed mesh). The first centimetres at the root are left out (--root-cm), because the root
sits on the scalp on purpose and the wires do not move it. The partner should be a closed mesh; for an open one the
vote is unreliable and the report says so. Only the pose and frame of the file are tested."""

import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

DIRS = [Vector(d).normalized() for d in ((0.31, 0.22, 0.92), (-0.83, 0.41, -0.37), (0.45, -0.86, 0.23))]
BARY = np.array([[1 / 3, 1 / 3, 1 / 3], [0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]])
KEEP_MODIFIERS = {"ARMATURE", "NODES", "HOOK"}


def fail(msg):
    print("KANZASHI " + json.dumps(dict(ok=False, error=msg), ensure_ascii=False))
    sys.exit(1)


def new_path(p, folder=False):
    if not p:
        return None
    p = os.path.abspath(p)
    if folder:
        if os.path.isdir(p) and os.listdir(p):
            fail("the folder is not empty (nothing is overwritten): %s" % p)
        os.makedirs(p, exist_ok=True)
    elif os.path.exists(p):
        fail("already exists (nothing is overwritten): %s" % p)
    return p


def detected_hairs(names):
    obs = [bpy.data.objects.get(n) for n in names] if names else list(bpy.context.view_layer.objects)
    return [o for o in obs if o is not None and o.type == "MESH" and "lw_strand" in o.data.attributes]


def wires_of(hair):
    return bpy.data.objects.get(hair.get("lw_wires", ""))


def plain_modifiers(hair, on):
    """Modifiers that change the faces (outline shells and the like) are switched off while measuring."""
    changed = []
    for m in hair.modifiers:
        if m.type not in KEEP_MODIFIERS and m.show_viewport and not on:
            m.show_viewport = False
            changed.append(m.name)
    return changed


def evaluated_world(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.data
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    M = np.array(ev.matrix_world, dtype=np.float64)
    return me, co.reshape(-1, 3).astype(np.float64) @ M[:3, :3].T + M[:3, 3]


def partner_tree(obj):
    me, P = evaluated_world(obj)
    polys = [tuple(p.vertices) for p in me.polygons]
    tree = BVHTree.FromPolygons([Vector(p) for p in P], polys)
    edges = {}
    for p in polys:
        for i in range(len(p)):
            e = (min(p[i], p[i - 1]), max(p[i], p[i - 1]))
            edges[e] = edges.get(e, 0) + 1
    open_edges = sum(1 for n in edges.values() if n == 1)
    return dict(name=obj.name, tree=tree, faces=len(polys), open_edges=open_edges)


def hair_samples(hair):
    """Points on the faces of the hair as it is shown now: position, strand, place along the strand (0 root, 1 tip),
    the area each point stands for."""
    me, P = evaluated_world(hair)
    src = hair.data
    if len(me.polygons) != len(src.polygons) or len(me.vertices) != len(src.vertices):
        fail("the shown mesh of %s has other faces than the mesh itself; a modifier changes the faces" % hair.name)
    strand = np.empty(len(src.polygons), dtype=np.int32)
    src.attributes["lw_strand"].data.foreach_get("value", strand)
    along = np.zeros(len(src.vertices), dtype=np.float32)
    if "lw_f" in src.attributes:
        src.attributes["lw_f"].data.foreach_get("value", along)
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    tri = np.empty(n * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    poly = np.empty(n, dtype=np.int32)
    me.loop_triangles.foreach_get("polygon_index", poly)
    A, B, C = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(B - A, C - A), axis=1)
    pts = (
        BARY[None, :, 0, None] * A[:, None] + BARY[None, :, 1, None] * B[:, None] + BARY[None, :, 2, None] * C[:, None]
    )
    f = along[tri]
    t = f @ BARY.T
    k = len(BARY)
    return dict(
        points=pts.reshape(-1, 3),
        strand=np.repeat(strand[poly], k),
        t=np.clip(t.reshape(-1), 0.0, 1.0),
        area=np.repeat(area / k, k),
        verts=P,
    )


def wire_lengths(wires):
    out = []
    Mw = wires.matrix_world
    for sp in wires.data.splines:
        pts = [Mw @ bp.co for bp in sp.bezier_points]
        out.append(sum((pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)))
    return np.array(out) if out else np.zeros(0)


def inside_vote(tree, p):
    """True when the point lies inside a closed surface: odd crossings in most directions."""
    votes = 0
    for d in DIRS:
        n = 0
        o = p
        for _ in range(64):
            hit = tree.ray_cast(o, d)
            if hit[0] is None:
                break
            n += 1
            o = hit[0] + d * 1e-5
        votes += n % 2
    return votes * 2 > len(DIRS)


def measure(hair, partners, opt):
    """Per sample: depth inside (0 when outside), the partner, and the way out (nearest surface point - point)."""
    S = hair_samples(hair)
    wires = wires_of(hair)
    length = wire_lengths(wires) if wires is not None else np.zeros(0)
    n = len(S["points"])
    depth = np.zeros(n)
    who = np.full(n, -1, dtype=np.int32)
    out = np.zeros((n, 3))
    wl = np.where(
        S["strand"] >= 0, length[np.clip(S["strand"], 0, max(len(length) - 1, 0))] if len(length) else 0.0, 0.0
    )
    rooted = S["t"] * wl < opt["root_cm"] / 100.0
    reach = opt["reach_mm"] / 1000.0
    tol = opt["tolerance_mm"] / 1000.0
    for pi, part in enumerate(partners):
        tree = part["tree"]
        for i in range(n):
            if rooted[i] or S["strand"][i] < 0:
                continue
            p = Vector(S["points"][i])
            loc, _nrm, _idx, dist = tree.find_nearest(p, reach)
            if loc is None or dist <= tol or dist <= depth[i]:
                continue
            if inside_vote(tree, p):
                depth[i] = dist
                who[i] = pi
                out[i] = np.array(loc - p)
    S.update(depth=depth, who=who, out=out, rooted=rooted, wire_length=length)
    return S


def strand_findings(hair, S, partners, opt):
    items = []
    for k in np.unique(S["strand"][S["depth"] > 0]):
        m = (S["strand"] == k) & (S["depth"] > 0)
        area_cm2 = float(S["area"][m].sum() * 1e4)
        dmax = float(S["depth"][m].max() * 1000)
        if area_cm2 < opt["min_area_cm2"] and dmax < opt["deep_mm"]:
            continue
        t0, t1 = float(S["t"][m].min()), float(S["t"][m].max())
        own = (S["strand"] == k) & ~S["rooted"]
        beyond = bool(((S["t"] > t1 + 0.03) & own & (S["depth"] == 0)).any())
        kind = "tip" if not beyond else "through"
        i = int(np.flatnonzero(m)[np.argmax(S["depth"][m])])
        total = float(S["area"][S["strand"] == k].sum() * 1e4)
        names = sorted({partners[j]["name"] for j in np.unique(S["who"][m])})
        items.append(
            dict(
                hair=hair.name,
                wire=int(k),
                kind=kind,
                depth_max_mm=round(dmax, 2),
                buried_cm2=round(area_cm2, 2),
                buried_share=round(area_cm2 / max(total, 1e-9), 3),
                along=[round(t0, 3), round(t1, 3)],
                partners=names,
                deepest=[round(float(x), 4) for x in S["points"][i]],
                way_out=[round(float(x), 4) for x in S["out"][i]],
            )
        )
    items.sort(key=lambda d: -d["depth_max_mm"] * (1 + d["buried_cm2"]))
    return items


def move_wires(hair, S, items, opt):
    """One round: every wire in `items` is moved outward where its strand is buried. Returns {wire: moved mm}."""
    wires = wires_of(hair)
    inv = np.array(wires.matrix_world.inverted().to_3x3(), dtype=np.float64)
    margin = opt["margin_mm"] / 1000.0
    moved = {}
    for it in items:
        k = it["wire"]
        sp = wires.data.splines[k]
        pts = sp.bezier_points
        n = len(pts)
        if n < 2:
            continue
        m = (S["strand"] == k) & (S["depth"] > 0)
        ts = S["t"][m]
        d = S["depth"][m]
        push = S["out"][m] / np.maximum(d[:, None], 1e-9) * (d[:, None] + margin)
        w_area = S["area"][m] * (0.3 + d / d.max())
        seg = np.array([(pts[i + 1].co - pts[i].co).length for i in range(n - 1)])
        tj = np.concatenate([[0.0], np.cumsum(seg) / max(seg.sum(), 1e-9)])
        sigma = max(1.5 / (n - 1), 0.06)
        length = float(S["wire_length"][k]) if k < len(S["wire_length"]) else 0.0
        best = 0.0
        for j, bp in enumerate(pts):
            if tj[j] * length < opt["root_cm"] / 100.0:
                continue
            w = np.exp(-(((ts - tj[j]) / sigma) ** 2)) * w_area
            if w.sum() <= 1e-12:
                continue
            near = np.exp(-((np.abs(ts - tj[j]).min() / sigma) ** 2))  # 1 at the buried stretch, fading away from it
            delta = (push * w[:, None]).sum(0) / w.sum() * near
            if np.linalg.norm(delta) < 1e-5:
                continue
            dv = Vector(inv @ delta)
            bp.co += dv
            bp.handle_left += dv
            bp.handle_right += dv
            best = max(best, float(np.linalg.norm(delta)))
        if best > 0:
            moved[k] = moved.get(k, 0.0) + best * 1000
    wires.data.update_tag()
    bpy.context.view_layer.update()
    return moved


def render(hairs, partners_obs, flagged, folder, size=1100, moved=(), spots=None):
    """Four views of the hair on the partners (buried strands red, strands moved by fix blue, partners brown), and
    close views of the worst places. Call it after saving: it leaves colours and a camera in the scene."""
    sc = bpy.context.scene
    show = set(hairs) | set(partners_obs)
    for o in bpy.data.objects:
        o.hide_render = o not in show
    for h in hairs:
        me = h.data
        strand = np.empty(len(me.polygons), dtype=np.int32)
        me.attributes["lw_strand"].data.foreach_get("value", strand)
        bad = np.isin(strand, [it["wire"] for it in flagged if it["hair"] == h.name])
        ca = me.color_attributes.get("kz_buried") or me.color_attributes.new("kz_buried", "FLOAT_COLOR", "CORNER")
        col = np.empty((len(me.loops), 4), dtype=np.float32)
        col[:] = (0.75, 0.78, 0.85, 1.0)
        per_loop = np.repeat(bad, [p.loop_total for p in me.polygons])
        was = np.isin(strand, [k for name, k in moved if name == h.name])
        col[np.repeat(was, [p.loop_total for p in me.polygons])] = (0.1, 0.45, 1.0, 1.0)
        col[per_loop] = (1.0, 0.05, 0.05, 1.0)
        ca.data.foreach_set("color", col.ravel())
        me.color_attributes.active_color = ca
        me.color_attributes.render_color_index = list(me.color_attributes).index(ca)
    for o in partners_obs:
        me = o.data
        ca = me.color_attributes.get("kz_buried") or me.color_attributes.new("kz_buried", "FLOAT_COLOR", "CORNER")
        col = np.empty((len(me.loops), 4), dtype=np.float32)
        col[:] = (0.42, 0.30, 0.26, 1.0)
        ca.data.foreach_set("color", col.ravel())
        me.color_attributes.active_color = ca
        me.color_attributes.render_color_index = list(me.color_attributes).index(ca)
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "VERTEX"
    sh.show_object_outline = True
    sc.world = bpy.data.worlds.new("kanzashi_pen")
    sc.world.color = (0.12, 0.12, 0.12)
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "PNG"
    P = np.concatenate([evaluated_world(h)[1] for h in hairs])
    lo, hi = P.min(0), P.max(0)
    centre = Vector((lo + hi) / 2)
    cam_data = bpy.data.cameras.new("kanzashi_pen")
    cam_data.type = "ORTHO"
    cam_data.clip_end = 100.0
    cam = bpy.data.objects.new("kanzashi_pen", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    files = []

    def shoot(name, target, direction, span, aspect):
        d = Vector(direction).normalized()
        sc.render.resolution_y = size
        sc.render.resolution_x = max(int(size * aspect), 64)
        cam_data.ortho_scale = span * max(aspect, 1.0)
        cam.location = Vector(target) - d * 10.0
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        path = os.path.join(folder, name + ".png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        files.append(path)

    height = float(hi[2] - lo[2]) * 1.08
    for name, d in (
        ("all_front", (0, 1, 0)),
        ("all_back", (0, -1, 0)),
        ("all_left", (-1, 0, 0)),
        ("all_right", (1, 0, 0)),
    ):
        width = float(hi[1] - lo[1]) if abs(d[0]) > 0.5 else float(hi[0] - lo[0])
        shoot(name, centre, d, height, float(np.clip(width * 1.08 / height, 0.3, 2.0)))
    for i, it in enumerate((flagged if spots is None else spots)[:6]):
        out = Vector(it["way_out"])
        d = -out.normalized() if out.length > 1e-6 else Vector((0, 1, 0))  # look from outside toward the place
        shoot("spot%02d_wire%d_%s" % (i + 1, it["wire"], it["hair"]), Vector(it["deepest"]), d, 0.30, 1.0)
    return files


def options(a):
    return dict(
        root_cm=a.root_cm,
        reach_mm=a.reach_mm,
        tolerance_mm=a.tolerance_mm,
        min_area_cm2=a.min_area_cm2,
        deep_mm=a.deep_mm,
        margin_mm=getattr(a, "margin_mm", 3.0),
    )


def prepare(a):
    hairs = detected_hairs(a.hair)
    if not hairs:
        fail("no detected hair (run kanzashi_run.py first)")
    for h in hairs:
        if wires_of(h) is None:
            fail("%s has no wires any more (the shape was applied); detect again to measure by strands" % h.name)
    missing = [n for n in a.against if n not in bpy.data.objects or bpy.data.objects[n].type != "MESH"]
    if missing:
        fail("no such mesh: %s (see the command 'list')" % ", ".join(missing))
    partners_obs = [bpy.data.objects[n] for n in a.against if bpy.data.objects[n] not in hairs]
    if not partners_obs:
        fail("give the meshes to test against with --against (see the command 'list')")
    switched = {h.name: plain_modifiers(h, False) for h in hairs}
    bpy.context.view_layer.update()
    partners = [partner_tree(o) for o in partners_obs]
    return hairs, partners_obs, partners, switched


def cmd_list(a):
    rows = []
    for o in bpy.context.view_layer.objects:
        if o.type != "MESH":
            continue
        box = [Vector(c) for c in o.bound_box]
        size = [round(max(b[i] for b in box) - min(b[i] for b in box), 3) for i in range(3)]
        rows.append(
            dict(
                name=o.name,
                faces=len(o.data.polygons),
                size_m=size,
                visible=bool(o.visible_get()),
                detected_hair="lw_strand" in o.data.attributes,
                materials=[m.name for m in o.data.materials if m][:4],
            )
        )
    rows.sort(key=lambda r: -r["faces"])
    print("KANZASHI " + json.dumps(dict(ok=True, meshes=rows), ensure_ascii=True))


def cmd_check(a):
    report = new_path(a.report)
    folder = new_path(a.render_dir, folder=True)
    hairs, partners_obs, partners, _sw = prepare(a)
    opt = options(a)
    items = []
    for h in hairs:
        items += strand_findings(h, measure(h, partners, opt), partners, opt)
    rep = dict(
        ok=True,
        command="check",
        file=bpy.data.filepath,
        hairs=[h.name for h in hairs],
        against=[dict(name=p["name"], faces=p["faces"], open_edges=p["open_edges"]) for p in partners],
        options=opt,
        strands=items,
        buried_strands=len(items),
        warnings=[
            "%s is not closed (%d open edges): inside/outside is unreliable near its openings"
            % (p["name"], p["open_edges"])
            for p in partners
            if p["open_edges"]
        ],
        not_checked=[
            "other poses and frames",
            "hair against hair",
            "whether a buried place can be seen in the final look",
        ],
    )
    if folder:
        rep["pictures"] = render(hairs, partners_obs, items, folder)
    if report:
        json.dump(rep, open(report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("KANZASHI " + json.dumps(rep, ensure_ascii=True))


def cmd_fix(a):
    out = new_path(a.out)
    report = new_path(a.report)
    folder = new_path(a.render_dir, folder=True)
    if not out:
        fail("fix needs --out (a new .blend)")
    hairs, partners_obs, partners, switched = prepare(a)
    opt = options(a)
    rep = dict(ok=True, command="fix", file=bpy.data.filepath, options=opt, max_depth_mm=a.max_depth_mm, hairs=[])
    before_all, after_all = [], []
    for h in hairs:
        rest = evaluated_world(h)[1].copy()
        S = measure(h, partners, opt)
        before = strand_findings(h, S, partners, opt)
        chosen = [it for it in before if it["depth_max_mm"] <= a.max_depth_mm and (not a.wire or it["wire"] in a.wire)]
        left = [it for it in before if it not in chosen]
        ids = {it["wire"] for it in chosen}
        moved = {}
        rounds = 0
        while chosen and rounds < a.rounds:
            rounds += 1
            for k, mm in move_wires(h, S, chosen, opt).items():
                moved[k] = moved.get(k, 0.0) + mm
            S = measure(h, partners, opt)
            chosen = [it for it in strand_findings(h, S, partners, opt) if it["wire"] in ids]
        after = strand_findings(h, S, partners, opt)
        now = evaluated_world(h)[1]
        shift = np.linalg.norm(now - rest, axis=1) * 1000
        rep["hairs"].append(
            dict(
                name=h.name,
                rounds=rounds,
                tried=sorted(ids),
                wire_moved_mm={str(k): round(v, 1) for k, v in sorted(moved.items())},
                hair_moved_max_mm=round(float(shift.max()), 1),
                vertices_moved=int((shift > 0.1).sum()),
                still_buried=[it["wire"] for it in after if it["wire"] in ids],
                new_buried=[it["wire"] for it in after if it["wire"] not in {b["wire"] for b in before}],
                left_for_the_user=[
                    dict(wire=it["wire"], depth_max_mm=it["depth_max_mm"], kind=it["kind"]) for it in left
                ],
            )
        )
        before_all += before
        after_all += after
    rep["before"] = before_all
    rep["after"] = after_all
    rep["buried_before"] = len(before_all)
    rep["buried_after"] = len(after_all)
    for h in hairs:  # what was switched off for measuring comes back before saving
        for name in switched[h.name]:
            h.modifiers[name].show_viewport = True
    bpy.ops.wm.save_as_mainfile(filepath=out, copy=True)
    rep["saved"] = out
    if folder:  # after saving: the picture colours do not go into the file
        for h in hairs:
            plain_modifiers(h, False)
        tried = [(h["name"], k) for h in rep["hairs"] for k in h["tried"]]
        spots = [it for it in before_all if (it["hair"], it["wire"]) in set(tried)]
        rep["pictures"] = render(hairs, partners_obs, after_all, folder, moved=tried, spots=spots)
    rep["not_checked"] = ["other poses and frames", "hair against hair", "how the moved strands look"]
    if report:
        json.dump(rep, open(report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("KANZASHI " + json.dumps(rep, ensure_ascii=True))


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="hair_penetration.py")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for name in ("check", "fix"):
        p = sub.add_parser(name)
        p.add_argument("--against", action="append", nargs="+", default=[], help="meshes the hair is tested against")
        p.add_argument("--hair", action="append", default=[], help="hair meshes (default: all detected)")
        p.add_argument("--report", help="new JSON report")
        p.add_argument("--render-dir", help="new folder for pictures")
        p.add_argument("--root-cm", type=float, default=5.0, help="this much of every strand at the root is left out")
        p.add_argument(
            "--reach-mm", type=float, default=80.0, help="points farther than this from a partner are outside"
        )
        p.add_argument("--tolerance-mm", type=float, default=1.0, help="shallower than this does not count")
        p.add_argument("--min-area-cm2", type=float, default=0.3, help="smaller buried patches are left out ...")
        p.add_argument("--deep-mm", type=float, default=6.0, help="... unless they are deeper than this")
        if name == "fix":
            p.add_argument("--out", help="new .blend for the result")
            p.add_argument("--wire", type=int, action="append", default=[], help="only these wires (repeat)")
            p.add_argument("--max-depth-mm", type=float, default=25.0, help="deeper strands are left for the user")
            p.add_argument("--margin-mm", type=float, default=3.0, help="how far outside the surface a strand is put")
            p.add_argument("--rounds", type=int, default=5)
    a = ap.parse_args(argv)
    if a.command == "list":
        return cmd_list(a)
    a.against = [n for group in a.against for n in group]
    return cmd_check(a) if a.command == "check" else cmd_fix(a)


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""What is done to a detected hair afterwards: repainting (faces move to the wire of the colour they were painted with),
hiding strands, new wires, and writing the bent shape into the mesh."""

import numpy as np

from .tree import PAL, smooth_line


def face_strands(me):
    s = np.empty(len(me.polygons), dtype=np.int32)
    me.attributes["lw_strand"].data.foreach_get("value", s)
    return s


def set_face_colours(me, strand, name="lw_strand_col"):
    total = np.array([p.loop_total for p in me.polygons])
    ca = me.color_attributes.get(name) or me.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
    fc = np.where((strand >= 0)[:, None], PAL[np.maximum(strand, 0)], 0.35)
    c = np.ones((len(me.loops), 4), dtype=np.float32)
    c[:, :3] = np.repeat(fc, total, axis=0)
    ca.data.foreach_set("color", c.reshape(-1))
    me.update()


def apply_repaint(hair, wires_obj, tol=0.12, changed_min=0.04, keep_min=6):
    """Reads the face colours. A face painted with the colour of another wire moves to that wire: the face, its
    vertices (they are tied to the new wire where it is now) and so its place in the strand UV. Painted faces are
    locked. Small pieces a wire is left with, cut off from the rest of it, join what surrounds them. Faces painted
    only partly, or with no wire's colour, go back to their own colour."""
    from . import strands as S

    R = S.R
    me = hair.data
    strand = face_strands(me)
    nf = len(strand)
    ca = me.color_attributes["lw_strand_col"]
    col = np.empty(len(me.loops) * 4, dtype=np.float32)
    ca.data.foreach_get("color", col)
    col = col.reshape(-1, 4)[:, :3]
    start = np.array([p.loop_start for p in me.polygons])
    total = np.array([p.loop_total for p in me.polygons])
    mean = np.add.reduceat(col, start, axis=0) / total[:, None]
    own = PAL[np.maximum(strand, 0)]
    n_w = len(wires_obj.data.splines)
    cand = [int(k) for k in hair.get("lw_picked", []) if 0 <= int(k) < n_w] or list(range(n_w))
    touched = np.nonzero((np.linalg.norm(mean - own, axis=1) > changed_min) & (strand >= 0))[0]
    moved = []
    reverted = 0
    if len(touched):
        d = np.linalg.norm(mean[touched][:, None, :] - PAL[cand][None, :, :], axis=2)
        best = np.argmin(d, axis=1)
        for fi, b, dd in zip(touched, best, d[np.arange(len(touched)), best]):
            k = cand[int(b)]
            if dd < tol and k != strand[fi]:
                moved.append((int(fi), int(strand[fi]), k))
            else:
                reverted += 1
    lock = np.empty(nf, dtype=np.int32)
    me.attributes["lw_lock"].data.foreach_get("value", lock)
    for fi, _o, k in moved:
        strand[fi] = k
        lock[fi] = 1
    # pieces a wire is left with
    ek = {}
    for pg in me.polygons:
        for key in pg.edge_keys:
            ek.setdefault(key, []).append(pg.index)
    adj = [[] for _ in range(nf)]
    for fs in ek.values():
        for a_ in fs:
            for b_ in fs:
                if a_ != b_:
                    adj[a_].append(b_)
    rejoined = 0
    if moved:
        seen = np.zeros(nf, dtype=bool)
        comps = {}
        for s in range(nf):
            if seen[s] or strand[s] < 0:
                continue
            k = strand[s]
            stack = [s]
            seen[s] = True
            comp = [s]
            while stack:
                v = stack.pop()
                for u in adj[v]:
                    if not seen[u] and strand[u] == k:
                        seen[u] = True
                        stack.append(u)
                        comp.append(u)
            comps.setdefault(int(k), []).append(comp)
        hit = {o for _f, o, _k in moved}
        for k in hit:
            cs = sorted(comps.get(k, []), key=len, reverse=True)
            for comp in cs[1:]:
                if len(comp) >= keep_min or lock[comp].any():
                    continue
                around = [int(strand[u]) for v in comp for u in adj[v] if strand[u] != k and strand[u] >= 0]
                if around:
                    vals, cnt = np.unique(around, return_counts=True)
                    strand[comp] = vals[int(np.argmax(cnt))]
                    rejoined += len(comp)
    me.attributes["lw_strand"].data.foreach_set("value", strand)
    me.attributes["lw_lock"].data.foreach_set("value", lock)
    # vertices follow their faces
    ids = R._get(me, "lw_id").astype(np.int64)
    nv = len(ids)
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    per = [[] for _ in range(nv)]
    for pg in me.polygons:
        for li in range(pg.loop_start, pg.loop_start + pg.loop_total):
            per[lvi[li]].append(int(strand[pg.index]))
    change = np.zeros(nv, dtype=bool)
    for v in range(nv):
        ks = [k for k in per[v] if k >= 0]
        if ks and ids[v] not in ks:
            vals, cnt = np.unique(ks, return_counts=True)
            ids[v] = int(vals[int(np.argmax(cnt))])
            change[v] = True
    if change.any():
        _P, _T, _inv, world = R.gather(hair)
        fv = R._get(me, "lw_f")
        for k in np.unique(ids[change]):
            vs = np.nonzero(change & (ids == k))[0]
            fv[vs] = R.nearest_on_polyline(R.spline_polyline(wires_obj, int(k)), world[vs])[0]
        R._set(me, "lw_id", ids.astype(np.int32))
        R._set(me, "lw_f", fv)
        R.refresh_rest(hair, wires_obj, which=change)
    fitted = 0
    for k in [int(x) for x in hair.get("lw_new", [])]:
        if (strand == k).sum() >= 3 and fit_wire(hair, wires_obj, k, strand):
            fitted += 1
    set_face_colours(me, strand)
    have = set(np.unique(strand).tolist())
    hair["lw_picked"] = []
    return dict(
        wires_fitted=fitted,
        faces_moved=len(moved),
        faces_reverted=int(reverted),
        faces_rejoined=int(rejoined),
        vertices_moved=int(change.sum()),
        wires_without_faces=[k for k in range(n_w) if k not in have],
    )


def set_hidden(hair, hidden):
    """Hides the faces of the wires in `hidden` (a list of wire ids), shows the rest."""
    me = hair.data
    strand = face_strands(me)
    hide = np.isin(strand, list(hidden)) if len(hidden) else np.zeros(len(strand), dtype=bool)
    me.polygons.foreach_set("hide", hide)
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    total = np.array([p.loop_total for p in me.polygons])
    vis = np.zeros(len(me.vertices), dtype=bool)
    vis[lvi[np.repeat(~hide, total)]] = True
    me.vertices.foreach_set("hide", ~vis)
    ev = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    me.edges.foreach_set("hide", ~(vis[ev[:, 0]] & vis[ev[:, 1]]))
    me.polygons.foreach_set("select", ~hide)
    me.use_paint_mask = bool(hide.any())
    hair["lw_hidden"] = [int(x) for x in hidden]
    at = me.attributes.get("lw_hide") or me.attributes.new("lw_hide", "BOOLEAN", "FACE")
    at.data.foreach_set("value", hide)
    me.update()
    return int(hide.sum())


HIDE_GROUP = "LidaHairHide"


def hide_modifier(hair, show):
    """In Object Mode hidden faces are drawn all the same. This modifier leaves out the faces marked hidden;
    it is switched on only while bending (in the paint mode Blender's own hiding is used)."""
    import bpy

    me = hair.data
    if "lw_hide" not in me.attributes:
        me.attributes.new("lw_hide", "BOOLEAN", "FACE")
    g = bpy.data.node_groups.get(HIDE_GROUP)
    if g is None:
        g = bpy.data.node_groups.new(HIDE_GROUP, "GeometryNodeTree")
        g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
        g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
        gi = g.nodes.new("NodeGroupInput")
        go = g.nodes.new("NodeGroupOutput")
        na = g.nodes.new("GeometryNodeInputNamedAttribute")
        na.data_type = "BOOLEAN"
        na.inputs["Name"].default_value = "lw_hide"
        dl = g.nodes.new("GeometryNodeDeleteGeometry")
        dl.domain = "FACE"
        g.links.new(gi.outputs[0], dl.inputs["Geometry"])
        g.links.new(na.outputs["Attribute"], dl.inputs["Selection"])
        g.links.new(dl.outputs["Geometry"], go.inputs[0])
    md = hair.modifiers.get(HIDE_GROUP)
    if md is None:
        md = hair.modifiers.new(HIDE_GROUP, "NODES")
        md.node_group = g
        md.show_render = False
        want = hair.modifiers.find("LidaHairRewire") + 1
        while hair.modifiers.find(HIDE_GROUP) > want:
            hair.modifiers.move(hair.modifiers.find(HIDE_GROUP), hair.modifiers.find(HIDE_GROUP) - 1)
    md.show_viewport = bool(show)
    return md


def wire_table(hair, wires_obj):
    """[(wire id, faces, kind)] for every wire of the hair."""
    strand = face_strands(hair.data)
    cnt = np.bincount(strand[strand >= 0], minlength=len(wires_obj.data.splines))
    kinds = list(wires_obj.get("lw_kinds", []))
    return [(k, int(cnt[k]), kinds[k] if k < len(kinds) else "new") for k in range(len(wires_obj.data.splines))]


def new_wire(hair, wires_obj):
    """A new, empty wire (a new colour). Paint faces with it; when the painting is applied the wire's line is
    laid through those faces. Returns its id."""
    from . import strands as S

    k = len(wires_obj.data.splines)
    S.R.add_spline(wires_obj, np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -0.01]]), np.array([0.005, 0.005]))
    wires_obj["lw_kinds"] = list(wires_obj.get("lw_kinds", [])) + ["new"]
    wires_obj["lw_parent"] = list(wires_obj.get("lw_parent", [])) + [-1]
    hair["lw_new"] = [int(x) for x in hair.get("lw_new", [])] + [k]
    hair["lw_current"] = k
    hair["lw_picked"] = [int(x) for x in hair.get("lw_picked", [])] + [k]
    return k


def replace_spline(wires_obj, index, pos, rad):
    """Gives spline `index` new points and keeps every other spline, and the order, as it is."""
    from . import strands as S

    cu = wires_obj.data
    keep = []
    for sp in cu.splines:
        keep.append(
            [
                (
                    bp.co.copy(),
                    bp.handle_left.copy(),
                    bp.handle_right.copy(),
                    bp.handle_left_type,
                    bp.handle_right_type,
                    bp.radius,
                )
                for bp in sp.bezier_points
            ]
        )
    while len(cu.splines):
        cu.splines.remove(cu.splines[0])
    for i, pts in enumerate(keep):
        if i == index:
            S.R.add_spline(wires_obj, pos, rad)
            continue
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(pts) - 1)
        sp.resolution_u = 8
        for bp, (co, hl, hr, tl, tr, r) in zip(sp.bezier_points, pts):
            bp.co = co
            bp.handle_left_type = tl
            bp.handle_right_type = tr
            bp.handle_left = hl
            bp.handle_right = hr
            bp.radius = r


def fit_wire(hair, wires_obj, k, strand=None):
    """Lays wire k through the middle of its faces, from the crown side to the tip side, and ties their vertices
    to it where it now lies."""
    from . import strands as S

    R = S.R
    me = hair.data
    strand = face_strands(me) if strand is None else strand
    if "lw_d" not in me.attributes:
        return False
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    total = np.array([p.loop_total for p in me.polygons])
    vs = np.unique(lvi[np.repeat(strand == k, total)])
    if len(vs) < 3:
        return False
    _P, _T, _inv, world = R.gather(hair)
    d = R._get(me, "lw_d")[vs]
    p = world[vs]
    step = 0.01
    b = np.floor((d - d.min()) / step).astype(np.int64)
    cen = []
    rad = []
    for s in range(int(b.max()) + 1):
        m = b == s
        if m.any():
            c = p[m].mean(axis=0)
            cen.append(c)
            rad.append(max(float(np.linalg.norm(p[m] - c, axis=1).max()), 0.003))
    if len(cen) < 2:  # painted across, not along: a short line along its longest side
        c = p.mean(axis=0)
        sv = np.linalg.svd(p - c, full_matrices=False)
        ax = sv[2][0] * max(float(sv[1][0]) / max(len(p), 1) ** 0.5, 0.005)
        cen = [c - ax, c + ax]
        rad = [0.005, 0.005]
    line = smooth_line(np.array(cen))
    rr = np.interp(np.linspace(0, 1, len(line)), np.linspace(0, 1, len(rad)), rad)
    if len(line) >= 3:
        line, rr = R.simplify(line, rr, tolerance=0.004)[:2]
    replace_spline(wires_obj, k, line, rr)
    ids = R._get(me, "lw_id").astype(np.int64)
    fv = R._get(me, "lw_f")
    mine = np.zeros(len(ids), dtype=bool)
    mine[vs] = True
    mine &= ids == k
    if mine.any():
        fv[mine] = R.nearest_on_polyline(R.spline_polyline(wires_obj, k), world[mine])[0]
        R._set(me, "lw_f", fv)
        R.refresh_rest(hair, wires_obj, which=mine)
    hair["lw_new"] = [int(x) for x in hair.get("lw_new", []) if int(x) != k]
    return True


BIND_ATTRS = (
    "lw_id",
    "lw_f",
    "lw_w",
    "lw_r0",
    "lw_p0",
    "lw_t0",
    "lw_n0",
    "lw_ext",
    "lw_d",
    "lw_hide",
    "lw_lock",
    "lw_cut",
)


def finalize(hair, wires_obj, keep_colours=True):
    """Writes the bent shape into the mesh and takes the machinery away: the bend and hide modifiers, the wires,
    the attributes that tie vertices to wires. The colour per strand (lw_strand, lw_strand_col) and the strand UV
    stay unless keep_colours is off. After this the hair is an ordinary mesh; to bend again, detect again."""
    import bpy

    from . import strands as S

    R = S.R
    me = hair.data
    if me.shape_keys is not None:
        raise RuntimeError("the mesh has shape keys; the bent shape cannot be written into it")
    if me.users > 1:
        raise RuntimeError("the mesh is used by %d objects" % me.users)
    dm = hair.modifiers.get(R.GROUP)
    moved = 0.0
    if dm is not None:
        others = [(m, m.show_viewport) for m in hair.modifiers if m is not dm]
        for m, _s in others:
            m.show_viewport = False
        was = dm.show_viewport
        dm.show_viewport = True
        try:
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            ev = hair.evaluated_get(dg).data
            if len(ev.vertices) != len(me.vertices):
                raise RuntimeError("the bent mesh has another number of vertices")
            co = np.empty(len(ev.vertices) * 3, dtype=np.float32)
            ev.vertices.foreach_get("co", co)
            old = np.empty(len(me.vertices) * 3, dtype=np.float32)
            me.vertices.foreach_get("co", old)
        finally:
            dm.show_viewport = was
            for m, s in others:
                m.show_viewport = s
        if not np.isfinite(co).all():
            raise RuntimeError("the bent shape has invalid numbers")
        moved = float(np.abs(co - old).max())
        me.vertices.foreach_set("co", co)
        hair.modifiers.remove(dm)
    hm = hair.modifiers.get(HIDE_GROUP)
    if hm is not None:
        hair.modifiers.remove(hm)
    me.polygons.foreach_set("hide", np.zeros(len(me.polygons), dtype=bool))
    me.vertices.foreach_set("hide", np.zeros(len(me.vertices), dtype=bool))
    me.edges.foreach_set("hide", np.zeros(len(me.edges), dtype=bool))
    me.use_paint_mask = False
    names = list(BIND_ATTRS) + ([] if keep_colours else ["lw_strand", "lw_strand_col"])
    for nm in names:
        a = me.attributes.get(nm)
        if a is not None:
            me.attributes.remove(a)
    if wires_obj is not None:
        cu = wires_obj.data
        bpy.data.objects.remove(wires_obj, do_unlink=True)
        if cu is not None and cu.users == 0:
            bpy.data.curves.remove(cu)
    for key in ("lw_wires", "lw_current", "lw_picked", "lw_hidden", "lw_new"):
        if key in hair:
            del hair[key]
    me.update()
    return dict(moved_mm=moved * 1000, vertices=len(me.vertices), kept_colours=bool(keep_colours))

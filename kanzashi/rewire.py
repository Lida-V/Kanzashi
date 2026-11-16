# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Lida
# Prototype: give an existing hair mesh one guide wire per strand, so the strands can be bent by the wires.
#   detect()        find strands in the mesh and build one wire (spline) for each
#   bind_manual()   tie the mesh near a hand-made wire to that wire (soft falloff)
#   ensure_deform() the modifier that moves bound vertices with their wire (identity until a wire is edited)
#   strand_uv()     a second UV map: one strip per strand
# The mesh keeps its vertices, faces and first UV map. Importing this file registers nothing.
import math

import numpy as np

from . import wire as W

GROUP = "LidaHairRewire"
BIND_GROUP = "LidaHairRewireBind"
ATTRS = (
    ("lw_id", "INT"),
    ("lw_f", "FLOAT"),
    ("lw_w", "FLOAT"),
    ("lw_r0", "FLOAT"),
    ("lw_p0", "FLOAT_VECTOR"),
    ("lw_t0", "FLOAT_VECTOR"),
    ("lw_n0", "FLOAT_VECTOR"),
)


# ----------------------------------------------------------------------------- numpy part
def polyline_param(poly):
    seg = np.linalg.norm(np.diff(poly, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum, max(float(cum[-1]), 1e-9)


def nearest_on_polyline(poly, pts):
    """For each point: (factor 0..1 along the polyline, distance)."""
    cum, total = polyline_param(poly)
    a = poly[:-1]
    ab = poly[1:] - a
    den = np.maximum((ab * ab).sum(axis=1), 1e-18)
    best_d = np.full(len(pts), np.inf)
    best_f = np.zeros(len(pts))
    for i in range(len(a)):
        t = np.clip(((pts - a[i]) @ ab[i]) / den[i], 0.0, 1.0)
        q = a[i] + ab[i] * t[:, None]
        d = np.linalg.norm(pts - q, axis=1)
        m = d < best_d
        best_d[m] = d[m]
        best_f[m] = (cum[i] + t[m] * (cum[i + 1] - cum[i])) / total
    return best_f, best_d


def smoothstep(x, lo, hi):
    t = np.clip((np.asarray(x, float) - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def detect_strands(P, T, root, window=0.03, step=0.008, max_tries=500, min_stations=6, min_new=0.6, log=None):
    """Greedy: start from the vertex farthest from the root that no strand owns yet, follow its strand,
    give the strand the vertices of its sections. Returns (strands, owner per welded vertex)."""
    nv = len(P)
    owner = np.full(nv, -1, dtype=np.int64)
    tried = np.zeros(nv, dtype=bool)
    order = np.argsort(-np.linalg.norm(P - root, axis=1))
    strands = []
    tries = 0
    for v in order:
        if tries >= max_tries:
            break
        if owner[v] >= 0 or tried[v]:
            continue
        tries += 1
        tried[v] = True
        st = W.trace_strand(P, T, P[v], window=window, step=step)
        if len(st) < min_stations:
            continue
        ids = [np.array(s.get("verts", []), dtype=np.int64) for s in st]
        good = [i for i, s in enumerate(st) if not s.get("saturated") and s.get("hw", 0) > 0]
        if len(good) < min_stations:
            continue
        allv = np.unique(np.concatenate([ids[i] for i in good]))
        tried[allv] = True
        fresh = allv[owner[allv] < 0]
        if len(fresh) < min_new * len(allv) or len(fresh) < 8:
            continue
        c = np.array([s["centre"] for s in st])
        if np.linalg.norm(c[0] - root) > np.linalg.norm(c[-1] - root):
            st = st[::-1]
        k = len(strands)
        owner[fresh] = k
        fused_root = st[0].get("end") != "tip"
        strands.append(dict(stations=st, fused_root=fused_root))
        if log and k % 10 == 0:
            log("strand %d  tries %d  owned %.0f%%" % (k, tries, 100.0 * (owner >= 0).mean()))
    return strands, owner, tries


def grow_owners(P, T, owner, polys, radii, rounds=4, factor=1.8):
    """Vertices between two sections belong to no section. Give a free vertex to a strand when all its
    owned neighbours belong to that one strand and it lies near that strand's wire."""
    nv = len(P)
    nb = [set() for _ in range(nv)]
    for a, b, c in T:
        nb[a].update((b, c))
        nb[b].update((a, c))
        nb[c].update((a, b))
    for _ in range(rounds):
        add = {}
        for v in np.nonzero(owner < 0)[0]:
            ks = {int(owner[u]) for u in nb[v] if owner[u] >= 0}
            if len(ks) == 1:
                add[int(v)] = ks.pop()
        if not add:
            break
        byk = {}
        for v, k in add.items():
            byk.setdefault(k, []).append(v)
        changed = 0
        for k, vs in byk.items():
            _f, d = nearest_on_polyline(polys[k], P[vs])
            ok = d < factor * radii[k]
            for v, o in zip(vs, ok):
                if o:
                    owner[v] = k
                    changed += 1
        if not changed:
            break
    return owner


def strip_uv(angle_face_corner, f_face_corner):
    """Unwrap the angle within one face so a face never spans the seam. Inputs are per-corner arrays of one face."""
    a = np.asarray(angle_face_corner, float)
    m = math.atan2(np.sin(a).mean(), np.cos(a).mean())
    a = m + (a - m + math.pi) % (2 * math.pi) - math.pi
    return a, np.asarray(f_face_corner, float)


def edge_graph(P, T, radial=None, sideways=1.0):
    """Neighbours with edge costs, per welded vertex. With radial (distance from the crown per vertex),
    the part of an edge that runs sideways costs `sideways` times more than the part that runs along the hair."""
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    ln = np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1)
    if radial is not None:
        dr = np.abs(radial[e[:, 0]] - radial[e[:, 1]])
        dr = np.where(np.isfinite(dr), np.minimum(dr, ln), ln)
        ln = np.sqrt(dr * dr + (ln * ln - dr * dr) * sideways * sideways)
    nb = [[] for _ in range(len(P))]
    for (a, b), l in zip(e, ln):
        nb[a].append((int(b), float(l)))
        nb[b].append((int(a), float(l)))
    return nb


def spread(nb, sources, labels=None):
    """Shortest path along edges from the sources. Returns (distance, label of the nearest source)."""
    import heapq

    n = len(nb)
    dist = np.full(n, np.inf)
    lab = np.full(n, -1, dtype=np.int64)
    heap = []
    for i, s in enumerate(sources):
        dist[s] = 0.0
        lab[s] = labels[i] if labels is not None else 0
        heap.append((0.0, int(s)))
    heapq.heapify(heap)
    while heap:
        d, v = heapq.heappop(heap)
        if d > dist[v]:
            continue
        for u, l in nb[v]:
            nd = d + l
            if nd < dist[u]:
                dist[u] = nd
                lab[u] = lab[v]
                heapq.heappush(heap, (nd, u))
    return dist, lab


def simplify(pos, rad, tolerance=0.006, max_gap=0.08):
    """Fewer control points (Douglas-Peucker), so one point bends a long, smooth stretch of the wire."""
    pos = np.asarray(pos, float)
    n = len(pos)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ab = pos[b] - pos[a]
        L = np.linalg.norm(ab)
        q = pos[a + 1 : b] - pos[a]
        d = (
            np.linalg.norm(q - np.outer(q @ ab / max(L * L, 1e-18), ab), axis=1)
            if L > 1e-9
            else np.linalg.norm(q, axis=1)
        )
        i = int(np.argmax(d))
        if d[i] > tolerance or L > max_gap:
            m = a + 1 + (i if d[i] > tolerance else (b - a - 1) // 2)
            keep[m] = True
            stack += [(a, m), (m, b)]
    return pos[keep], np.asarray(rad, float)[keep]


def frames(poly):
    """Tangent and a normal carried along the polyline without twisting (one per point)."""
    t = np.gradient(poly, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    n = np.zeros_like(poly)
    a = np.array([0.0, 0.0, 1.0]) if abs(t[0][2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n[0] = np.cross(t[0], np.cross(a, t[0]))
    n[0] /= np.linalg.norm(n[0])
    for i in range(1, len(poly)):
        v = n[i - 1] - t[i] * (n[i - 1] @ t[i])
        ln = np.linalg.norm(v)
        n[i] = v / ln if ln > 1e-9 else n[i - 1]
    return t, n


def sample_frames(poly, f):
    """Point, tangent, normal of the polyline at factors f."""
    cum, total = polyline_param(poly)
    t, n = frames(poly)
    s = np.clip(f, 0, 1) * total
    out = []
    for arr in (poly, t, n):
        out.append(np.stack([np.interp(s, cum, arr[:, k]) for k in range(3)], axis=1))
    return out


def join_strands(strands, owner, reach=0.025):
    """A strand that was followed in two pieces becomes one: join where the end of one continues the other."""

    def ends(st):
        c = np.array([s["centre"] for s in st["stations"]])
        k = min(3, len(c) - 1)
        d0 = c[0] - c[k]
        d1 = c[-1] - c[-1 - k]
        return c, d0 / max(np.linalg.norm(d0), 1e-9), d1 / max(np.linalg.norm(d1), 1e-9)

    alive = list(range(len(strands)))
    joined = 0
    changed = True
    while changed:
        changed = False
        for ai in alive:
            ca, a0, a1 = ends(strands[ai])
            best = None
            for bi in alive:
                if bi == ai:
                    continue
                cb, b0, b1 = ends(strands[bi])
                for ea, pa, da in ((0, ca[0], a0), (1, ca[-1], a1)):
                    for eb, pb, db in ((0, cb[0], b0), (1, cb[-1], b1)):
                        gap = pb - pa
                        g = float(np.linalg.norm(gap))
                        if g < reach and float(da @ db) < -0.4 and float(gap @ da) > -0.004:
                            if best is None or g < best[0]:
                                best = (g, bi, ea, eb)
            if best is not None:
                _g, bi, ea, eb = best
                sa = strands[ai]["stations"]
                sb = strands[bi]["stations"]
                sa = sa if ea == 1 else sa[::-1]  # a now ends at the joint
                sb = sb if eb == 0 else sb[::-1]  # b now starts at the joint
                merged = [s for s in sa if s.get("end") != "tip" or s is sa[0]] + [
                    s for s in sb if s.get("end") != "tip" or s is sb[-1]
                ]
                strands[ai] = dict(stations=merged, fused_root=True)
                owner[owner == bi] = ai
                alive.remove(bi)
                joined += 1
                changed = True
                break
    remap = {old: new for new, old in enumerate(alive)}
    out = [strands[i] for i in alive]
    new_owner = np.full_like(owner, -1)
    for old, new in remap.items():
        new_owner[owner == old] = new
    return out, new_owner, joined


def flow_labels(nb, D, owner):
    """Share out unowned vertices along the flow of the hair (the steepest way from and to the crown).
    Pass 1: a vertex takes the strand found upstream of it (unfollowed tips and gaps).
    Pass 2: what is still free (the melted part above the strands) takes the strand found downstream of it,
    so the borders between strands run along the flow, up to the crown.
    Returns (labels, mask of the vertices labelled in pass 2)."""
    n = len(nb)
    lab = owner.copy()
    up = np.full(n, -1, dtype=np.int64)
    down = np.full(n, -1, dtype=np.int64)
    for v in range(n):
        if not np.isfinite(D[v]):
            continue
        bu, bd = 0.0, 0.0
        for u, l in nb[v]:
            if not np.isfinite(D[u]) or l <= 0:
                continue
            s = (D[u] - D[v]) / l
            if s < bu:
                bu = s
                up[v] = u
            if s > bd:
                bd = s
                down[v] = u
    order = np.argsort(D)
    for v in order:  # from the crown outward
        if lab[v] < 0 and up[v] >= 0 and np.isfinite(D[v]):
            lab[v] = lab[up[v]]
    melted = np.zeros(n, dtype=bool)
    for v in order[::-1]:  # from the tips back to the crown
        if lab[v] < 0 and down[v] >= 0 and np.isfinite(D[v]) and lab[down[v]] >= 0:
            lab[v] = lab[down[v]]
            melted[v] = True
    return lab, melted


def smooth_labels(nb, lab, mask, rounds=1):
    """Tidy the borders inside mask: a vertex takes the label most of its neighbours have."""
    for _ in range(rounds):
        new = lab.copy()
        for v in np.nonzero(mask)[0]:
            ks = [int(lab[u]) for u, _l in nb[v] if lab[u] >= 0]
            if len(ks) >= 3:
                vals, cnt = np.unique(ks, return_counts=True)
                i = int(np.argmax(cnt))
                if cnt[i] * 2 > len(ks):
                    new[v] = vals[i]
        lab = new
    return lab


def link_upstream(strands, owner, nb, D, steps=10, slack=0.03, beyond=0.2):
    """Follow the surface toward the crown from where each strand starts. If that runs into another strand:
    the other one ends there -> the two are one strand (join);  it carries on -> a branch (same part, own wire).
    Strands must already be ordered root -> tip. Returns (strands, owner, joined, branch pairs)."""
    n = len(strands)
    lo = np.full(n, np.inf)
    hi = np.full(n, -np.inf)
    for k in range(n):
        d = D[owner == k]
        d = d[np.isfinite(d)]
        if len(d):
            lo[k] = d.min()
            hi[k] = d.max()
    link = {}
    for b in np.argsort(lo):
        if not np.isfinite(lo[b]):
            continue
        vs = np.nonzero(owner == b)[0]
        seeds = vs[D[vs] < lo[b] + 0.01]
        hits = []
        for v in seeds:
            cur = int(v)
            for _ in range(steps):
                cand = [(D[u], u) for u, _l in nb[cur] if D[u] < D[cur]]
                if not cand:
                    break
                cur = int(min(cand)[1])
                if owner[cur] >= 0 and owner[cur] != b:
                    hits.append(int(owner[cur]))
                    break
        if len(hits) * 2 >= max(len(seeds), 1) and hits:
            vals, cnt = np.unique(hits, return_counts=True)
            a = int(vals[int(np.argmax(cnt))])
            da = D[owner == a]
            da = da[np.isfinite(da)]
            past = float((da > lo[b] + slack).mean()) if len(da) else 0.0
            link[int(b)] = (a, bool(past < beyond))
    head = list(range(n))

    def find(x):
        while head[x] != x:
            x = head[x]
        return x

    joined = 0
    branches = []
    for b in sorted(link, key=lambda k: lo[k]):
        a, is_join = link[b]
        a = find(a)
        if a == b:
            continue
        if is_join:
            sa = [s for s in strands[a]["stations"] if s.get("end") != "tip"]
            strands[a] = dict(stations=sa + strands[b]["stations"], fused_root=strands[a]["fused_root"])
            owner[owner == b] = a
            head[b] = a
            hi[a] = max(hi[a], hi[b])
            joined += 1
        else:
            branches.append((a, int(b)))
    alive = [k for k in range(n) if head[k] == k]
    remap = {old: new for new, old in enumerate(alive)}
    new_owner = np.full_like(owner, -1)
    for old, new in remap.items():
        new_owner[owner == old] = new
    branches = [(remap[find(a)], remap[b]) for a, b in branches if find(b) == b and find(a) in remap and b in remap]
    return [strands[k] for k in alive], new_owner, joined, branches


def settle_owners(P, nb, owner, cent, rad, rounds=3, margin=0.8):
    """Where strands touch, a section can pick up vertices of the neighbour. Give each owned vertex to the
    strand whose centre line it is nearest to (in units of that strand's radius), choosing only among the
    strands its neighbours belong to."""
    moved = 0
    for _ in range(rounds):
        want = {}
        for v in np.nonzero(owner >= 0)[0]:
            ks = {int(owner[u]) for u, _l in nb[v] if owner[u] >= 0}
            ks.add(int(owner[v]))
            if len(ks) > 1:
                for k in ks:
                    want.setdefault(k, []).append(int(v))
        if not want:
            break
        score = {}
        for k, vs in want.items():
            _f, d = nearest_on_polyline(cent[k], P[vs])
            for v, x in zip(vs, d / max(rad[k], 1e-4)):
                score.setdefault(v, {})[k] = float(x)
        change = 0
        for v, sc in score.items():
            cur = int(owner[v])
            best = min(sc, key=sc.get)
            if best != cur and sc[best] < margin * sc.get(cur, np.inf):
                owner[v] = best
                change += 1
        moved += change
        if not change:
            break
    return owner, moved


# ----------------------------------------------------------------------------- Blender part
def gather(obj, depsgraph=None):
    """World-space welded triangles of the object's own mesh (no modifiers). Returns P, T, inv (vertex -> welded)."""
    me = obj.data
    me.calc_loop_triangles()
    v = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", v)
    v = v.reshape(-1, 3)
    m = np.array(obj.matrix_world)
    v = v @ m[:3, :3].T + m[:3, 3]
    t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    key = np.round(v / 1e-5).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    return v[first], inv[t.reshape(-1, 3)], inv, v


def spline_polyline(obj, index):
    """World-space evaluated points of one Bezier or poly spline (same points Blender evaluates)."""
    from mathutils import geometry

    sp = obj.data.splines[index]
    mw = obj.matrix_world
    if sp.type == "BEZIER":
        bp = sp.bezier_points
        res = max(sp.resolution_u, 1) + 1
        pts = []
        for i in range(len(bp) - 1):
            seg = geometry.interpolate_bezier(bp[i].co, bp[i].handle_right, bp[i + 1].handle_left, bp[i + 1].co, res)
            pts += seg if i == 0 else seg[1:]
        if not pts:
            pts = [bp[0].co]
    else:
        pts = [p.co.xyz for p in sp.points]
    return np.array([mw @ p for p in pts])


def add_spline(obj, pos, rad):
    """Append one Bezier spline (world positions) with automatic handles. Returns its index."""
    inv = obj.matrix_world.inverted()
    from mathutils import Vector

    sp = obj.data.splines.new("BEZIER")
    sp.bezier_points.add(len(pos) - 1)
    sp.resolution_u = 8
    for i, bp in enumerate(sp.bezier_points):
        bp.co = inv @ Vector([float(x) for x in pos[i]])
        bp.handle_left_type = bp.handle_right_type = "AUTO"
        bp.radius = float(max(rad[i], 0.0005))
    return len(obj.data.splines) - 1


def ensure_wires(name, collection):
    import bpy

    ob = bpy.data.objects.get(name)
    if ob is None:
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        ob = bpy.data.objects.new(name, cu)
        collection.objects.link(ob)
        ob.show_in_front = True
    return ob


def ensure_attrs(me):
    for name, typ in ATTRS:
        if name not in me.attributes:
            a = me.attributes.new(name, typ, "POINT")
            if name == "lw_id":
                a.data.foreach_set("value", np.full(len(me.vertices), -1, dtype=np.int32))


def _get(me, name, width=1):
    a = me.attributes[name]
    if width == 1:
        out = np.empty(len(me.vertices), dtype=np.int32 if a.data_type == "INT" else np.float32)
        a.data.foreach_get("value", out)
    else:
        out = np.empty(len(me.vertices) * 3, dtype=np.float32)
        a.data.foreach_get("vector", out)
        out = out.reshape(-1, 3)
    return out


def _set(me, name, arr):
    a = me.attributes[name]
    if a.data_type == "FLOAT_VECTOR":
        a.data.foreach_set("vector", np.asarray(arr, dtype=np.float32).reshape(-1))
    else:
        a.data.foreach_set("value", np.asarray(arr, dtype=np.int32 if a.data_type == "INT" else np.float32))


def _sample_nodes(g, wires_socket):
    """Nodes that sample the wire of each vertex at its stored factor. Returns (position, tangent, normal, radius, id)."""
    N = g.nodes
    L = g.links
    oi = N.new("GeometryNodeObjectInfo")
    oi.transform_space = "RELATIVE"
    L.new(wires_socket, oi.inputs["Object"])

    def named(name, typ):
        n = N.new("GeometryNodeInputNamedAttribute")
        n.data_type = typ
        n.inputs["Name"].default_value = name
        return n.outputs["Attribute"]

    sc = N.new("GeometryNodeSampleCurve")
    sc.mode = "FACTOR"
    sc.data_type = "FLOAT"
    sc.use_all_curves = False
    L.new(oi.outputs["Geometry"], sc.inputs["Curves"])
    L.new(N.new("GeometryNodeInputRadius").outputs["Radius"], sc.inputs["Value"])
    lid = named("lw_id", "INT")
    L.new(named("lw_f", "FLOAT"), sc.inputs["Factor"])
    L.new(lid, sc.inputs["Curve Index"])
    return sc.outputs["Position"], sc.outputs["Tangent"], sc.outputs["Normal"], sc.outputs["Value"], lid, named


def _new_group(name):
    import bpy

    old = bpy.data.node_groups.get(name)
    if old is not None:
        return old, False
    g = bpy.data.node_groups.new(name, "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Wires", in_out="INPUT", socket_type="NodeSocketObject")
    return g, True


def ensure_bind_group():
    g, fresh = _new_group(BIND_GROUP)
    if not fresh:
        return g
    N = g.nodes
    L = g.links
    gin = N.new("NodeGroupInput")
    gout = N.new("NodeGroupOutput")
    p, t, n, r, _lid, _named = _sample_nodes(g, gin.outputs["Wires"])
    geo = gin.outputs["Geometry"]
    for name, typ, src in (
        ("lw_bp", "FLOAT_VECTOR", p),
        ("lw_bt", "FLOAT_VECTOR", t),
        ("lw_bn", "FLOAT_VECTOR", n),
        ("lw_br", "FLOAT", r),
    ):
        s = N.new("GeometryNodeStoreNamedAttribute")
        s.data_type = typ
        s.domain = "POINT"
        s.inputs["Name"].default_value = name
        L.new(geo, s.inputs["Geometry"])
        L.new(src, s.inputs["Value"])
        geo = s.outputs["Geometry"]
    L.new(geo, gout.inputs["Geometry"])
    return g


def ensure_deform_group():
    g, fresh = _new_group(GROUP)
    if not fresh:
        return g
    s = g.interface.new_socket("Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    s.default_value = 1.0
    s.min_value = 0.0
    s.max_value = 1.0
    s = g.interface.new_socket("Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
    s.default_value = 1.0
    s.min_value = 0.0
    s.max_value = 4.0
    N = g.nodes
    L = g.links
    gin = N.new("NodeGroupInput")
    gout = N.new("NodeGroupOutput")
    p1, t1, n1, r1, lid, named = _sample_nodes(g, gin.outputs["Wires"])

    def vm(op, a, b=None, scale=None):
        n = N.new("ShaderNodeVectorMath")
        n.operation = op
        L.new(a, n.inputs[0])
        if b is not None:
            L.new(b, n.inputs[1])
        if scale is not None:
            L.new(scale, n.inputs["Scale"])
        return n.outputs["Value"] if op == "DOT_PRODUCT" else n.outputs["Vector"]

    def m(op, a, b):
        n = N.new("ShaderNodeMath")
        n.operation = op
        for i, x in enumerate((a, b)):
            if hasattr(x, "is_output"):
                L.new(x, n.inputs[i])
            else:
                n.inputs[i].default_value = x
        return n.outputs[0]

    pos = N.new("GeometryNodeInputPosition").outputs["Position"]
    p0, t0, n0, r0 = (
        named("lw_p0", "FLOAT_VECTOR"),
        named("lw_t0", "FLOAT_VECTOR"),
        named("lw_n0", "FLOAT_VECTOR"),
        named("lw_r0", "FLOAT"),
    )
    b0 = vm("CROSS_PRODUCT", t0, n0)
    b1 = vm("CROSS_PRODUCT", t1, n1)
    d = vm("SUBTRACT", pos, p0)
    a, b, c = vm("DOT_PRODUCT", d, t0), vm("DOT_PRODUCT", d, n0), vm("DOT_PRODUCT", d, b0)
    k = m("MULTIPLY", m("DIVIDE", r1, m("MAXIMUM", r0, 1e-6)), gin.outputs["Thickness"])
    radial = vm("SCALE", vm("ADD", vm("SCALE", n1, scale=b), vm("SCALE", b1, scale=c)), scale=k)
    new = vm("ADD", vm("ADD", p1, vm("SCALE", t1, scale=a)), radial)
    w = m("MULTIPLY", named("lw_w", "FLOAT"), gin.outputs["Strength"])
    off = vm("SCALE", vm("SUBTRACT", new, pos), scale=w)
    sel = m("GREATER_THAN", lid, -0.5)
    sp = N.new("GeometryNodeSetPosition")
    L.new(gin.outputs["Geometry"], sp.inputs["Geometry"])
    L.new(sel, sp.inputs["Selection"])
    L.new(off, sp.inputs["Offset"])
    L.new(sp.outputs["Geometry"], gout.inputs["Geometry"])
    return g


def _set_wires(md, wires):
    ident = next(
        s.identifier
        for s in md.node_group.interface.items_tree
        if getattr(s, "in_out", "") == "INPUT" and s.name == "Wires"
    )
    try:
        md[ident] = wires
    except Exception:
        getattr(md.properties.inputs, ident).value = wires


def ensure_deform(hair, wires):
    md = hair.modifiers.get(GROUP)
    if md is None:
        md = hair.modifiers.new(GROUP, "NODES")
        md.node_group = ensure_deform_group()
        while hair.modifiers.find(GROUP) > 0:  # first in the stack: before armature and the rest
            hair.modifiers.move(hair.modifiers.find(GROUP), hair.modifiers.find(GROUP) - 1)
    _set_wires(md, wires)
    return md


def refresh_rest(hair, wires, which=None):
    """Store, for the given vertices (default: all bound ones), where their wire is now: the rest pose of the tie."""
    import bpy

    me = hair.data
    dm = hair.modifiers.get(GROUP)
    shown = dm.show_viewport if dm else None
    if dm:
        dm.show_viewport = False
    others = [(m, m.show_viewport) for m in hair.modifiers if m is not dm]
    for m, _s in others:  # a Solidify, Subdivision or Mirror would change the number of vertices
        m.show_viewport = False
    bm = hair.modifiers.new("lw_bind_tmp", "NODES")
    bm.node_group = ensure_bind_group()
    _set_wires(bm, wires)
    n = len(me.vertices)
    out = {}
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = hair.evaluated_get(dg).data
        if len(ev.vertices) != n:
            raise RuntimeError("the evaluated mesh has %d vertices, the mesh %d" % (len(ev.vertices), n))
        for src, dst, vec in (
            ("lw_bp", "lw_p0", True),
            ("lw_bt", "lw_t0", True),
            ("lw_bn", "lw_n0", True),
            ("lw_br", "lw_r0", False),
        ):
            a = ev.attributes[src]
            arr = np.empty(n * (3 if vec else 1), dtype=np.float32)
            a.data.foreach_get("vector" if vec else "value", arr)
            out[dst] = arr.reshape(-1, 3) if vec else arr
    finally:
        hair.modifiers.remove(bm)
        for m, s in others:
            m.show_viewport = s
        if dm:
            dm.show_viewport = shown
    ids = _get(me, "lw_id")
    mask = ids >= 0 if which is None else np.asarray(which)
    for dst, arr in out.items():
        cur = _get(me, dst, 3 if arr.ndim == 2 else 1)
        cur[mask] = arr[mask]
        _set(me, dst, cur)
    me.update()


def detect(
    hair,
    wires,
    root,
    window=0.03,
    root_fade=0.04,
    max_tries=500,
    extend=True,
    tolerance=0.006,
    sideways=4.0,
    merge_gap=0.025,
    refine=0,
    log=None,
):
    """Find strands, make one spline each, tie their vertices. With extend, the melted part between the strands
    and the crown is shared out to the nearest strand and each wire is continued up to the crown.
    Returns a summary dict."""
    root = np.asarray(root, float)
    refined = 0
    if refine > 0:
        refined = refine_melted(hair, root, window=window, max_tries=max_tries, cuts=refine)
    P, T, inv, world = gather(hair)
    strands, owner, tries = detect_strands(P, T, root, window=window, max_tries=max_tries, log=log)
    strands, owner, joined = join_strands(strands, owner)
    nb = edge_graph(P, T)
    crown = int(np.argmin(np.linalg.norm(P - root, axis=1)))
    D, _ = spread(nb, [crown])
    for st in strands:  # root = the end nearer the crown along the surface
        c = np.array([s["centre"] for s in st["stations"]])
        e0 = D[int(np.argmin(np.linalg.norm(P - c[0], axis=1)))]
        e1 = D[int(np.argmin(np.linalg.norm(P - c[-1], axis=1)))]
        if np.isfinite(e0) and np.isfinite(e1) and e0 > e1:
            st["stations"] = st["stations"][::-1]
        st["fused_root"] = st["stations"][0].get("end") != "tip"
    cent = [np.array([s["centre"] for s in st["stations"]]) for st in strands]
    rad0 = []
    for st in strands:
        h = [s["hw"] for s in st["stations"] if s.get("hw", 0) > 0 and not s.get("saturated")]
        rad0.append(float(np.median(h)) if h else 0.01)
    owner = grow_owners(P, T, owner, cent, rad0)
    owner, resettled = settle_owners(P, nb, owner, cent, rad0)
    strands, owner, joined2, branches = link_upstream(strands, owner, nb, D)
    joined += joined2
    cent = [np.array([s["centre"] for s in st["stations"]]) for st in strands]
    rad0 = []
    for st in strands:
        h = [s["hw"] for s in st["stations"] if s.get("hw", 0) > 0 and not s.get("saturated")]
        rad0.append(float(np.median(h)) if h else 0.01)
    owner = grow_owners(P, T, owner, cent, rad0)
    traced = owner >= 0
    ext = np.zeros(len(P), dtype=bool)
    if extend and traced.any():
        lab, melted = flow_labels(nb, D, owner)
        lab = smooth_labels(nb, lab, melted, rounds=4)
        left = lab < 0  # islands the flow cannot reach: nearest strand
        if left.any():
            src = np.nonzero(lab >= 0)[0]
            _d, near = spread(nb, src, labels=lab[src])
            lab = np.where(left, near, lab)
            melted |= left & (lab >= 0) & (D < np.nanmedian(D[np.isfinite(D)]))
        ext = melted & (lab >= 0)
        owner = lab
    base = len(wires.data.splines)
    polys, joins = [], []
    for k, st in enumerate(strands):
        pos, rad, _maj, sm = W.stations_to_points(st["stations"])
        E = np.nonzero(ext & (owner == k))[0]
        join = 0.0
        if len(E) >= 6:
            d0 = float(D[int(np.argmin(np.linalg.norm(P - pos[0], axis=1)))])
            E = E[np.isfinite(D[E]) & (D[E] < d0 + 0.005)]
            if len(E) >= 6:
                edges = np.arange(float(D[E].min()), d0, 0.02)
                pts, rr = [], []
                for lo in edges:
                    m = E[(D[E] >= lo) & (D[E] < lo + 0.02)]
                    if len(m) >= 2:
                        c = P[m].mean(axis=0)
                        pts.append(c)
                        rr.append(max(float(np.linalg.norm(P[m] - c, axis=1).max()) * 0.6, 0.004))
                if len(pts) >= 2:
                    pts = np.array(pts)
                    sm_pts = pts.copy()
                    sm_pts[1:-1] = (pts[:-2] + 2 * pts[1:-1] + pts[2:]) / 4
                    join = float(np.linalg.norm(np.diff(np.vstack([sm_pts, pos[:1]]), axis=0), axis=1).sum())
                    pos = np.vstack([sm_pts, pos])
                    rad = np.concatenate([rr, rad])
        length = float(np.linalg.norm(np.diff(pos, axis=0), axis=1).sum())
        pos, rad = simplify(pos, rad, tolerance=tolerance)
        idx = add_spline(wires, pos, rad)
        st["spline"] = idx
        st["length"] = length
        st["join"] = join
        st["points"] = len(pos)
        polys.append(spline_polyline(wires, idx))
        joins.append(join / max(length, 1e-9))
    me = hair.data
    ensure_attrs(me)
    if "lw_ext" not in me.attributes:
        me.attributes.new("lw_ext", "FLOAT", "POINT")
    ids = _get(me, "lw_id")
    f = _get(me, "lw_f")
    w = _get(me, "lw_w")
    own_v = owner[inv]
    ext_v = ext[inv]
    for k, st in enumerate(strands):
        vs = np.nonzero(own_v == k)[0]
        if not len(vs):
            continue
        ff, _d = nearest_on_polyline(polys[k], world[vs])
        ids[vs] = base + k
        f[vs] = ff
        if joins[k] > 0:  # fixed at the crown, following fully where the strand leaves the melted part
            w[vs] = smoothstep(ff, joins[k] * 0.25, joins[k])
        elif st["fused_root"]:
            w[vs] = smoothstep(ff, 0.0, min(0.35, root_fade / max(st["length"], 1e-6)))
        else:
            w[vs] = 1.0
    _set(me, "lw_id", ids)
    _set(me, "lw_f", f)
    _set(me, "lw_w", w)
    _set(me, "lw_ext", ext_v.astype(np.float32))
    ensure_deform(hair, wires)
    refresh_rest(hair, wires)
    # strands that leave the melted part close together share one part (each keeps its own wire)
    group = list(range(len(strands)))

    def find(x):
        while group[x] != x:
            group[x] = group[group[x]]
            x = group[x]
        return x

    roots = (
        np.array([np.array([s["centre"] for s in st["stations"]])[0] for st in strands])
        if strands
        else np.zeros((0, 3))
    )
    for a_ in range(len(strands)):
        for b_ in range(a_ + 1, len(strands)):
            if np.linalg.norm(roots[a_] - roots[b_]) < merge_gap:
                group[find(a_)] = find(b_)
    for a_, b_ in branches:
        group[find(b_)] = find(a_)
    wires["lw_groups"] = [base + find(k) for k in range(len(strands))]
    wires["lw_base"] = base
    parts = face_parts(hair, wires)
    return dict(
        strands=len(strands),
        tries=tries,
        vertices=int(len(own_v)),
        traced=int(traced[inv].sum()),
        traced_share=float(traced[inv].mean()),
        bound=int((own_v >= 0).sum()),
        bound_share=float((own_v >= 0).mean()),
        extended_wires=int(sum(1 for s in strands if s["join"] > 0)),
        joined=int(joined),
        branches=len(branches),
        resettled=int(resettled),
        refined_faces=int(refined),
        parts=parts,
        control_points=int(sum(s["points"] for s in strands)),
        lengths=[round(s["length"], 3) for s in strands],
    )


def refine_melted(hair, root, window=0.03, max_tries=500, cuts=1):
    """Cut the faces of the melted part (faces no strand section touches) into smaller ones, so the borders
    between parts can be finer than the original faces. The shape does not change. Returns faces cut."""
    import bmesh

    P, T, inv, _world = gather(hair)
    strands, owner, _tries = detect_strands(P, T, np.asarray(root, float), window=window, max_tries=max_tries)
    cent = [np.array([s["centre"] for s in st["stations"]]) for st in strands]
    rad0 = [0.01] * len(strands)
    owner = grow_owners(P, T, owner, cent, rad0)
    traced_v = (owner >= 0)[inv]
    me = hair.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    faces = [f for f in bm.faces if not any(traced_v[v.index] for v in f.verts)]
    edges = list({e for f in faces for e in f.edges})
    if edges:
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)
        bm.to_mesh(me)
        me.update()
    bm.free()
    return len(faces)


def face_parts(hair, wires=None, colour="lw_part_col"):
    """Per face: the strand most of its corners belong to (lw_strand) and the part that strand is in (lw_part),
    plus a colour per part."""
    me = hair.data
    ids = _get(me, "lw_id")
    for nm in ("lw_strand", "lw_part"):
        if nm not in me.attributes:
            me.attributes.new(nm, "INT", "FACE")
    lv = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lv)
    strand = np.full(len(me.polygons), -1, dtype=np.int32)
    for p in me.polygons:
        k = ids[lv[p.loop_start : p.loop_start + p.loop_total]]
        vals, cnt = np.unique(k, return_counts=True)
        strand[p.index] = vals[int(np.argmax(cnt))]
    part = strand.copy()
    if wires is not None and "lw_groups" in wires:
        g = np.array(list(wires["lw_groups"]), dtype=np.int32)
        b = int(wires["lw_base"])
        m = (strand >= b) & (strand < b + len(g))
        part[m] = g[strand[m] - b]
    me.attributes["lw_strand"].data.foreach_set("value", strand)
    me.attributes["lw_part"].data.foreach_set("value", part)
    total = np.array([p.loop_total for p in me.polygons])
    for nm, key, seed in ((colour, part, 1), ("lw_strand_col", strand, 7)):
        rng = np.random.default_rng(seed)
        pal = rng.uniform(0.25, 1.0, size=(max(int(key.max()), 0) + 2, 3))
        ca = me.color_attributes.get(nm) or me.color_attributes.new(nm, "FLOAT_COLOR", "CORNER")
        fc = np.where((key >= 0)[:, None], pal[np.maximum(key, 0)], 0.35)
        col = np.ones((len(me.loops), 4), dtype=np.float32)
        col[:, :3] = np.repeat(fc, total, axis=0)
        ca.data.foreach_set("color", col.reshape(-1))
    me.color_attributes.active_color = me.color_attributes["lw_strand_col"]
    me.update()
    return dict(
        parts=int(len(np.unique(part[part >= 0]))),
        strands=int(len(np.unique(strand[strand >= 0]))),
        faces=int(len(part)),
        faces_without_part=int((part < 0).sum()),
    )


def split_parts(hair, collection, name=None):
    """A copy of the current shape cut along the part borders: every part its own piece of mesh. The source stays whole."""
    import bmesh
    import bpy

    dg = bpy.context.evaluated_depsgraph_get()
    dg.update()
    me = bpy.data.meshes.new_from_object(hair.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    o = bpy.data.objects.new(name or (hair.name + "_parts"), me)
    o.matrix_world = hair.matrix_world
    collection.objects.link(o)
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.faces.layers.int.get("lw_part")
    cut = [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][lay] != e.link_faces[1][lay]]
    bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(me)
    bm.free()
    return o, len(cut)


def bind_manual(hair, wires, spline_index, radius=0.02, steal=False, falloff=0.5):
    """Tie the mesh near one wire to it. Full weight within falloff*radius, fading to 0 at radius.
    Vertices already tied to another wire are left alone unless steal is set."""
    me = hair.data
    ensure_attrs(me)
    _P, _T, _inv, world = gather(hair)
    poly = spline_polyline(wires, spline_index)
    ff, d = nearest_on_polyline(poly, world)
    ids = _get(me, "lw_id")
    f = _get(me, "lw_f")
    w = _get(me, "lw_w")
    pick = d < radius
    if not steal:
        pick &= (ids < 0) | (ids == spline_index)
    ids[pick] = spline_index
    f[pick] = ff[pick]
    w[pick] = 1.0 - smoothstep(d[pick], radius * falloff, radius)
    _set(me, "lw_id", ids)
    _set(me, "lw_f", f)
    _set(me, "lw_w", w)
    ensure_deform(hair, wires)
    refresh_rest(hair, wires, which=pick)
    return int(pick.sum())


def unbind(hair, spline_index=None):
    me = hair.data
    if "lw_id" not in me.attributes:
        return 0
    ids = _get(me, "lw_id")
    m = ids >= 0 if spline_index is None else ids == spline_index
    ids[m] = -1
    _set(me, "lw_id", ids)
    me.update()
    return int(m.sum())


def strand_uv(hair, wires, name="LW_StrandUV", pad=0.004):
    """A second UV map: every part a strip (root at the top). Tube-like stretches are opened around the wire;
    the flat melted stretch near the crown is laid out by its sideways distance from the wire, as its own strip."""
    me = hair.data
    if "lw_strand" not in me.attributes:
        face_parts(hair, wires)
    part = np.empty(len(me.polygons), dtype=np.int32)
    me.attributes["lw_strand"].data.foreach_get("value", part)
    extv = _get(me, "lw_ext") if "lw_ext" in me.attributes else np.zeros(len(me.vertices), dtype=np.float32)
    _P, _T, _inv, world = gather(hair)
    vn = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("normal", vn)
    vn = vn.reshape(-1, 3)
    m3 = np.array(hair.matrix_world)[:3, :3]
    vn = vn @ np.linalg.inv(m3)
    lv = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lv)
    start = np.array([p.loop_start for p in me.polygons])
    total = np.array([p.loop_total for p in me.polygons])
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name, do_init=False)
    uv = np.zeros((len(me.loops), 2), dtype=np.float32)
    islands = {}
    for k in np.unique(part[part >= 0]):
        poly = spline_polyline(wires, int(k))
        length = polyline_param(poly)[1]
        faces = np.nonzero(part == k)[0]
        loops = np.concatenate([np.arange(start[fi], start[fi] + total[fi]) for fi in faces])
        v = lv[loops]
        ff, _d = nearest_on_polyline(poly, world[v])
        pp, tt, nn = sample_frames(poly, ff)
        d = world[v] - pp
        bb = np.cross(tt, nn)
        ang = np.arctan2((d * bb).sum(axis=1), (d * nn).sum(axis=1))
        rr = np.linalg.norm(d - tt * (d * tt).sum(axis=1)[:, None], axis=1)
        side = np.cross(tt, vn[v])
        side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-9)
        lat = (d * side).sum(axis=1)
        pos = 0
        for fi in faces:
            n = total[fi]
            sl = slice(pos, pos + n)
            pos += n
            li = loops[sl]
            flat = extv[v[sl]].mean() > 0.5
            if flat:
                u = lat[sl]
            else:
                a, _ = strip_uv(ang[sl], ff[sl])
                u = a * float(np.median(rr[sl]))
            uv[li, 0] = u
            uv[li, 1] = ff[sl] * length
            islands.setdefault((int(k), bool(flat)), []).append(li)
    # tubes: bring every face of one island onto the same turn of the angle
    boxes = {}
    for key, lis in islands.items():
        allu = np.concatenate([uv[li, 0] for li in lis])
        allv = np.concatenate([uv[li, 1] for li in lis])
        boxes[key] = (float(allu.min()), float(allu.max()), float(allv.min()), float(allv.max()))
    order = sorted(boxes, key=lambda q: -(boxes[q][3] - boxes[q][2]))
    area = sum(max(b[1] - b[0], 1e-4) * max(b[3] - b[2], 1e-4) for b in boxes.values()) or 1.0
    scale = (0.8 / area) ** 0.5
    for _attempt in range(60):
        x = pad
        y = pad
        col_w = 0.0
        lost = 0
        place = {}
        for key in order:
            b = boxes[key]
            wk = max(b[1] - b[0], 1e-4) * scale
            hk = min(max(b[3] - b[2], 1e-4) * scale, 1 - 2 * pad)
            if y + hk > 1 - pad:
                x += col_w + pad
                y = pad
                col_w = 0.0
            if x + wk > 1 - pad:
                lost += 1
            place[key] = (x, y, wk, hk)
            y += hk + pad
            col_w = max(col_w, wk)
        if not lost:
            break
        scale *= 0.95
    for key, lis in islands.items():
        b = boxes[key]
        x0, y0, wk, hk = place[key]
        for li in lis:
            uv[li, 0] = x0 + (uv[li, 0] - b[0]) / max(b[1] - b[0], 1e-6) * wk
            uv[li, 1] = 1.0 - (y0 + (uv[li, 1] - b[2]) / max(b[3] - b[2], 1e-6) * hk)
    layer.data.foreach_set("uv", uv.reshape(-1))
    me.update()
    return dict(
        strips=len(islands),
        flat_strips=int(sum(1 for q in islands if q[1])),
        faces_in_strips=int((part >= 0).sum()),
        base_faces=int((part < 0).sum()),
        overflow=lost,
    )

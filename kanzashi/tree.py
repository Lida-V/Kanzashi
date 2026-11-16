# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
# Prototype (not part of the Skills package). Strands of a generated hair mesh found by surface connectivity.
#
# Idea: D = distance along the surface from the crown. Sweep the vertices from the farthest to the nearest.
# A vertex with no swept neighbour starts a tube (a tip). A vertex whose swept neighbours belong to one tube
# joins it. A vertex whose swept neighbours belong to two or more tubes is where they merge: the tubes end
# there and one trunk goes on. So every vertex belongs to exactly one piece, a piece is always connected, and
# pieces meet only where three or more come together. No slicing is involved.
import numpy as np


def cap_by_flow(nb, f, zone, owner):
    """The melted part: every vertex climbs the smooth value (0 at the crown, 1 where the strands leave) from
    neighbour to neighbour until it reaches a strand, and takes that strand's label. So the cap is divided along
    the flow, not by straight distance. Returns (owner, vertices decided)."""
    owner = owner.copy(); done = 0
    for v in np.nonzero(zone & (owner < 0))[0]:
        cur = int(v); seen = 0
        while owner[cur] < 0 and seen < 400:
            best = cur; bf = f[cur] if np.isfinite(f[cur]) else -1.0
            for u, _l in nb[cur]:
                fu = f[u] if np.isfinite(f[u]) else -1.0
                if fu > bf:
                    best, bf = int(u), fu
            if best == cur:
                break
            cur = best; seen += 1
        if owner[cur] >= 0:
            owner[v] = -2 - owner[cur]; done += 1       # mark first, so later climbs do not stop on it early
    m = owner <= -2
    owner[m] = -2 - owner[m]
    return owner, done


# ---------------------------------------------------------------------------------------------------------
# Level rings. The sweep above joins two tubes for good as soon as they touch once. Tubes of a generated
# mesh touch and part again, so instead: cut the surface with contours of D every `h`. A contour is a closed
# ring round a tube (exact on the triangles, however coarse the mesh). The strip of surface between two
# levels falls into connected patches; a patch with one ring below and one above is a tube going on, one ring
# below and none above is a tip, one below and two above is a branch, two below is tubes touching.


class _UF:
    def __init__(self, n):
        self.p = np.arange(n, dtype=np.int64)

    def find(self, a):
        p = self.p
        while p[a] != a:
            p[a] = p[p[a]]; a = p[a]
        return a

    def union(self, a, b):
        a = self.find(a); b = self.find(b)
        if a != b:
            self.p[b] = a


def level_graph(P, T, D, h=0.01):
    """Returns (rings, patches, patch per vertex).
    rings[i]: level (index, D = level*h), length, centre, points (unordered crossing points), below, above (patch ids).
    patches[i]: band, inner (rings on the crown side), outer (rings on the tip side), verts."""
    n = len(P)
    band = np.floor(np.where(np.isfinite(D), D, 0.0) / h).astype(np.int64)
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]); e = np.unique(np.sort(e, axis=1), axis=0)
    sw = band[e[:, 0]] > band[e[:, 1]]; e[sw] = e[sw][:, ::-1]                 # a = lower band
    eid = {(int(min(a, b)), int(max(a, b))): i for i, (a, b) in enumerate(e)}
    cnt = band[e[:, 1]] - band[e[:, 0]]; off = np.concatenate([[0], np.cumsum(cnt)]); nc = int(off[-1])
    first = band[e[:, 0]] + 1                                                    # first level an edge crosses
    cpos = np.zeros((nc, 3)); clev = np.zeros(nc, dtype=np.int64)
    for i in np.nonzero(cnt > 0)[0]:
        a, b = e[i]; da, db = D[a], D[b]
        for q in range(cnt[i]):
            j = first[i] + q; s = (j * h - da) / max(db - da, 1e-12)
            cpos[off[i] + q] = P[a] + (P[b] - P[a]) * min(max(s, 0.0), 1.0); clev[off[i] + q] = j

    def node(i, j):
        return int(off[i] + (j - first[i]))

    ul = _UF(nc); seg = []
    for tri in T:
        v = sorted((int(x) for x in tri), key=lambda x: band[x]); b0, b1, b2 = band[v[0]], band[v[1]], band[v[2]]
        if b0 == b2:
            continue
        e01 = eid[(min(v[0], v[1]), max(v[0], v[1]))]; e02 = eid[(min(v[0], v[2]), max(v[0], v[2]))]
        e12 = eid[(min(v[1], v[2]), max(v[1], v[2]))]
        for j in range(b0 + 1, b2 + 1):
            x = node(e02, j); y = node(e01, j) if j <= b1 else node(e12, j)
            ul.union(x, y); seg.append((x, y))
    root = np.array([ul.find(i) for i in range(nc)], dtype=np.int64)
    ids, ring_of = np.unique(root, return_inverse=True); nr = len(ids)
    length = np.zeros(nr); csum = np.zeros((nr, 3))
    for x, y in seg:
        l = float(np.linalg.norm(cpos[x] - cpos[y])); r = ring_of[x]
        length[r] += l; csum[r] += (cpos[x] + cpos[y]) / 2 * l
    centre = np.where(length[:, None] > 1e-9, csum / np.maximum(length[:, None], 1e-9), 0.0)
    pts = [[] for _ in range(nr)]
    for i in range(nc):
        pts[ring_of[i]].append(i)
    for r in range(nr):
        if length[r] <= 1e-9:
            centre[r] = cpos[pts[r]].mean(axis=0)
    # strips between levels
    ub = _UF(n + 2 * nr)

    def IN(r):
        return n + 2 * int(r)

    def OUT(r):
        return n + 2 * int(r) + 1

    for i, (a, b) in enumerate(e):
        if cnt[i] == 0:
            ub.union(int(a), int(b)); continue
        ub.union(int(a), IN(ring_of[node(i, first[i])]))
        ub.union(int(b), OUT(ring_of[node(i, first[i] + cnt[i] - 1)]))
        for q in range(cnt[i] - 1):
            ub.union(OUT(ring_of[off[i] + q]), IN(ring_of[off[i] + q + 1]))
    roots = {}; patches = []

    def patch(x, bnd):
        r = ub.find(x)
        if r not in roots:
            roots[r] = len(patches); patches.append(dict(band=int(bnd), inner=[], outer=[], verts=[]))
        return roots[r]

    pv = np.full(n, -1, dtype=np.int64)
    for v in range(n):
        if np.isfinite(D[v]):
            pv[v] = patch(v, band[v]); patches[pv[v]]["verts"].append(v)
    rings = []
    for r in range(nr):
        lev = int(clev[pts[r][0]])
        below = patch(IN(r), lev - 1); above = patch(OUT(r), lev)
        patches[below]["outer"].append(r); patches[above]["inner"].append(r)
        rings.append(dict(level=lev, length=float(length[r]), centre=centre[r], points=cpos[pts[r]], below=below, above=above))
    return rings, patches, pv


def ring_tree(P, rings, patches, pv, h=0.01, cap_len=0.40, min_leaf=0.03, sheet_share=0.7, sheet_flat=0.35):
    """Tubes from the level rings, going outward from the crown.
    A segment is a run of rings with nothing joining or leaving. A ring longer than cap_len is not a tube but a
    sheet of tubes melted together (wide). A leaf shorter than min_leaf is a bump and goes back to its parent.
    Returns (segment per vertex, segs). segs[i]: rings, verts, parent, children, wide, reach (farthest level
    in its subtree), fused (it ended by running into another tube)."""
    n = len(pv); segs = []; ring_seg = np.full(len(rings), -1, dtype=np.int64)
    seg_of_v = np.full(n, -1, dtype=np.int64)

    def new_seg(parent, wide):
        segs.append(dict(rings=[], verts=[], parent=parent, children=[], wide=bool(wide), fused=False))
        if parent >= 0:
            segs[parent]["children"].append(len(segs) - 1)
        return len(segs) - 1

    def wide(r):
        return rings[r]["length"] > cap_len

    for pi in sorted(range(len(patches)), key=lambda i: patches[i]["band"]):
        pt = patches[pi]; inner = pt["inner"]; outer = pt["outer"]; verts = pt["verts"]
        if not inner:
            first = -1
            for r in outer:
                s = new_seg(-1, wide(r)); ring_seg[r] = s; segs[s]["rings"].append(r)
                first = s if first < 0 else first
            if first < 0:
                first = new_seg(-1, False)
            segs[first]["verts"] += verts; seg_of_v[verts] = first
            continue
        if len(inner) == 1:
            s = int(ring_seg[inner[0]])
            segs[s]["verts"] += verts; seg_of_v[verts] = s
            if len(outer) == 1 and wide(outer[0]) == segs[s]["wide"]:
                ring_seg[outer[0]] = s; segs[s]["rings"].append(outer[0])
            else:
                for r in outer:
                    c = new_seg(s, wide(r)); ring_seg[r] = c; segs[c]["rings"].append(r)
            continue
        # two or more tubes touch here. Each ring beyond goes on as the tube whose ring it is nearest to.
        ins = [int(ring_seg[r]) for r in inner]; ic = np.array([rings[r]["centre"] for r in inner])
        if verts:
            d = np.linalg.norm(P[verts][:, None, :] - ic[None, :, :], axis=2); near = np.argmin(d, axis=1)
            for v, q in zip(verts, near):
                segs[ins[q]]["verts"].append(v); seg_of_v[v] = ins[q]
        pairs = sorted(((float(np.linalg.norm(rings[r]["centre"] - ic[q])), r, q) for r in outer for q in range(len(inner))))
        used_in = set(); used_out = set()
        for _d, r, q in pairs:
            if r in used_out or q in used_in:
                continue
            used_out.add(r); used_in.add(q); s = ins[q]
            if wide(r) == segs[s]["wide"]:
                ring_seg[r] = s; segs[s]["rings"].append(r)
            else:
                c = new_seg(s, wide(r)); ring_seg[r] = c; segs[c]["rings"].append(r)
        for r in outer:
            if r not in used_out:
                q = int(np.argmin(np.linalg.norm(ic - rings[r]["centre"], axis=1)))
                c = new_seg(ins[q], wide(r)); ring_seg[r] = c; segs[c]["rings"].append(r)
        for q in range(len(inner)):
            if q not in used_in:
                segs[ins[q]]["fused"] = True
    # bumps go back to the tube they sit on
    absorbed = 0
    for _ in range(3):
        hit = False
        for i, s in enumerate(segs):
            if s.get("dead") or s["children"] or s["parent"] < 0 or s["fused"]:
                continue
            if len(s["rings"]) * h < min_leaf:
                par = segs[s["parent"]]
                par["verts"] += s["verts"]; seg_of_v[s["verts"]] = s["parent"]; par["children"].remove(i)
                s["dead"] = True; s["verts"] = []; hit = True; absorbed += 1
        if not hit:
            break
    for s in segs:
        s["reach"] = max([rings[r]["level"] for r in s["rings"]] or [0])
    for i in range(len(segs) - 1, -1, -1):
        s = segs[i]
        if not s.get("dead"):
            for c in s["children"]:
                s["reach"] = max(s["reach"], segs[c]["reach"])
    # Ribbons grown together side by side: a flat stretch that splits into parts, none of which is nearly as wide
    # as the stretch itself. That is not a tube with a branch but a sheet; it is divided lengthwise between the
    # ribbons that leave it (like the cap), instead of going to one of them as a block.
    def flatness(r):
        q = rings[r]["points"]
        if len(q) < 4:
            return 1.0
        sv = np.linalg.svd(q - q.mean(axis=0), compute_uv=False)
        return float(sv[1] / max(sv[0], 1e-9))

    sheets = 0
    for s in segs:
        ch = [c for c in s["children"] if not segs[c].get("dead")]
        if s.get("dead") or s["wide"] or len(ch) < 2 or not s["rings"]:
            continue
        main = max(ch, key=lambda c: segs[c]["reach"])
        if not segs[main]["rings"]:
            continue
        lp = float(np.median([rings[r]["length"] for r in s["rings"][-3:]]))
        lc = rings[segs[main]["rings"][0]]["length"]
        if lc < sheet_share * lp and float(np.median([flatness(r) for r in s["rings"]])) < sheet_flat:
            s["wide"] = True; s["sheet"] = True; sheets += 1
    for i in range(len(segs) - 1, -1, -1):
        s = segs[i]
        if s.get("dead"):
            continue
        s["has_wide"] = s["wide"] or any(segs[c]["has_wide"] for c in s["children"])
    return seg_of_v, segs, dict(sheets=sheets, segments=int(sum(1 for s in segs if not s.get("dead"))), bumps_absorbed=absorbed,
                                fused_ends=int(sum(1 for s in segs if s["fused"])))


def wires_from_rings(rings, segs, main_root):
    """One wire per tube. The cap is every segment that is wide or has something wide beyond it. A tube that
    leaves the cap starts a base wire. At a branch the tube keeps the wire of the child that reaches farthest.
    Returns (wire per segment, -1 in the cap; wires). wires[i]: segs, kind (base / branch / loose), parent."""
    wire_of = np.full(len(segs), -1, dtype=np.int64); wires = []

    def root_of(i):
        while segs[i]["parent"] >= 0:
            i = segs[i]["parent"]
        return i

    starts = []
    for i, s in enumerate(segs):
        if s.get("dead") or s["has_wide"]:
            continue
        p = s["parent"]
        if p < 0:
            starts.append((i, "base" if i in main_root else "loose", -1))
        elif segs[p]["has_wide"]:
            starts.append((i, "base" if root_of(i) in main_root else "loose", -1))
    stack = list(starts)
    while stack:
        i, kind, pw = stack.pop()
        w = len(wires); wires.append(dict(segs=[], kind=kind, parent=pw)); cur = i
        while True:
            wire_of[cur] = w; wires[w]["segs"].append(cur)
            ch = [c for c in segs[cur]["children"] if not segs[c].get("dead")]
            if not ch:
                break
            nxt = max(ch, key=lambda c: segs[c]["reach"])
            for c in ch:
                if c != nxt:
                    stack.append((c, "branch" if kind == "base" else kind, w))
            cur = nxt
    for w in wires:
        c = [rings[r]["centre"] for s in w["segs"] for r in segs[s]["rings"]]
        w["centres"] = np.array(c) if c else np.zeros((0, 3))
        w["rings"] = [r for s in w["segs"] for r in segs[s]["rings"]]
    return wire_of, wires


def smooth_line(c, spacing=0.008, smooth=4):
    c = np.asarray(c, float)
    if len(c) < 3:
        return c
    seg = np.linalg.norm(np.diff(c, axis=0), axis=1); c = c[np.concatenate([[True], seg > 1e-6])]
    if len(c) < 3:
        return c
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c, axis=0), axis=1))])
    s = np.linspace(0, cum[-1], max(4, int(cum[-1] / spacing) + 1))
    c = np.stack([np.interp(s, cum, c[:, q]) for q in range(3)], axis=1)
    for _ in range(smooth):
        c[1:-1] = (c[:-2] + 2 * c[1:-1] + c[2:]) / 4
    return c


# ---------------------------------------------------------------------------------------------------------
# The cap (melted part). Every base tube spreads a smooth share over the cap: 1 where that tube leaves it,
# 0 where the other tubes leave it, smooth in between. A point of the cap belongs to the tube with the largest
# share. The border between two tubes is where their shares are equal: a smooth line that runs with the flow
# from between two roots toward the crown. The mesh is cut along that line, so borders are not stair-stepped.


def cap_partition(nb, zone, owner, f=None, across=0.02, power=2.0):
    """Returns (labels, G, index): labels = tube ids that touch the cap, G[i, k] = share of labels[k] at cap
    vertex i, index[v] = row of vertex v in G or -1.
    With f (the smooth value, 0 at the crown and 1 where the tubes leave) a share spreads easily along the flow
    (edges on which f changes) and hardly across it (edges on which f stays the same; `across` is how much
    passes there). So every tube gets a wedge that runs toward the crown, not just the area nearest to it."""
    n = len(nb); zv = np.nonzero(zone & (owner < 0))[0]
    slope = None
    if f is not None:
        fz = np.where(np.isfinite(f), f, 1.0)
        sl = [abs(fz[u] - fz[v]) / max(l, 1e-6) for v in zv for u, l in nb[v]]
        slope = float(np.percentile(sl, 90)) if sl else None
    index = np.full(n, -1, dtype=np.int64); index[zv] = np.arange(len(zv))
    labs = sorted({int(owner[u]) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    col = {k: i for i, k in enumerate(labs)}
    m = len(zv); A = np.zeros((m, m)); B = np.zeros((m, len(labs)))
    for i, v in enumerate(zv):
        for u, l in nb[v]:
            w = 1.0 / max(l, 1e-6)
            if slope:
                w *= across + min(abs(fz[u] - fz[v]) / max(l, 1e-6) / slope, 1.0) ** power
            if index[u] >= 0:
                A[i, i] += w; A[i, index[u]] -= w
            elif owner[u] >= 0:
                A[i, i] += w; B[i, col[int(owner[u])]] += w
        A[i, i] += 1e-9
    G = np.linalg.solve(A, B) if m and labs else np.zeros((m, len(labs)))
    return labs, G, index


def cap_transport(nb, D, zone, owner):
    """The melted part (cap, or a sheet of ribbons grown together) divided by carrying every strand's label
    back toward the crown. Going from the far end inward, a vertex takes the shares of its neighbours that are
    farther from the crown, so a strand keeps a strip that runs along the flow all the way up, and strips of
    strands that leave the sheet one below the other lie side by side instead of in blocks.
    Returns (labels, G, index) like cap_partition."""
    n = len(nb); zv = np.nonzero(zone & (owner < 0))[0]
    index = np.full(n, -1, dtype=np.int64); index[zv] = np.arange(len(zv))
    labs = sorted({int(owner[u]) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    col = {k: i for i, k in enumerate(labs)}
    G = np.zeros((len(zv), len(labs))); done = np.zeros(len(zv), dtype=bool)
    for v in zv[np.argsort(-D[zv])]:
        acc = np.zeros(len(labs)); wsum = 0.0
        for u, l in nb[v]:
            if D[u] <= D[v]:
                continue
            w = (D[u] - D[v]) / max(l * l, 1e-12)
            if owner[u] >= 0:
                acc[col[int(owner[u])]] += w; wsum += w
            elif index[u] >= 0 and done[index[u]]:
                acc += w * G[index[u]]; wsum += w
        if wsum > 0:
            G[index[v]] = acc / wsum; done[index[v]] = True
    for _ in range(50):                               # edges of the sheet with nothing farther out: from any side
        left = np.nonzero(~done)[0]
        if not len(left):
            break
        hit = False
        for i in left:
            v = zv[i]; acc = np.zeros(len(labs)); wsum = 0.0
            for u, l in nb[v]:
                w = 1.0 / max(l, 1e-6)
                if owner[u] >= 0:
                    acc[col[int(owner[u])]] += w; wsum += w
                elif index[u] >= 0 and done[index[u]]:
                    acc += w * G[index[u]]; wsum += w
            if wsum > 0:
                G[i] = acc / wsum; done[i] = True; hit = True
        if not hit:
            break
    return labs, G, index


def cut_cap(me, inv, owner, labs, G, index, margin=0.12):
    """Cuts the mesh where the owner changes inside the cap, at the point of each edge where the two shares are
    equal. New vertices lie on the borders. Returns (edges cut, faces split, labels per new mesh vertex with -9
    for border vertices)."""
    import bmesh
    col = {k: i for i, k in enumerate(labs)}

    def share(v, k):
        if index[v] >= 0:
            return float(G[index[v], col[k]]) if k in col else 0.0
        return 1.0 if owner[v] == k else 0.0

    bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
    lay = bm.verts.layers.int.get("lw_cut") or bm.verts.layers.int.new("lw_cut")
    todo = []
    for e in bm.edges:
        a = int(inv[e.verts[0].index]); b = int(inv[e.verts[1].index])
        la, lb = int(owner[a]), int(owner[b])
        if la == lb or la < 0 or lb < 0 or (index[a] < 0 and index[b] < 0):
            continue
        da = share(a, la) - share(a, lb); db = share(b, la) - share(b, lb)
        s = da / (da - db) if (da - db) > 1e-9 else 0.5
        todo.append((e, min(max(s, margin), 1.0 - margin)))
    new = set()
    for e, s in todo:
        _ne, nv = bmesh.utils.edge_split(e, e.verts[0], s); nv[lay] = 1; new.add(nv)
    split = 0
    for f in list(bm.faces):
        nv = [v for v in f.verts if v in new]
        if len(nv) >= 2:
            try:
                bmesh.utils.face_split(f, nv[0], nv[1]); split += 1
            except Exception:
                pass
    bm.verts.ensure_lookup_table()
    old_n = len(inv)
    ids = np.full(len(bm.verts), -9, dtype=np.int64)
    for v in bm.verts:
        if v.index < old_n and not v[lay]:
            ids[v.index] = owner[inv[v.index]]
    bm.to_mesh(me); bm.free(); me.update()
    return len(todo), split, ids


def face_colours(me, ids, seed=7, name="lw_strand_col"):
    """Per face: the label most of its labelled corners have (border vertices, -9, do not vote). Writes the face
    attribute lw_strand and a colour per label."""
    lv = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lv)
    strand = np.full(len(me.polygons), -1, dtype=np.int32)
    for p in me.polygons:
        k = ids[lv[p.loop_start:p.loop_start + p.loop_total]]; k = k[k >= 0]
        if len(k):
            vals, cnt = np.unique(k, return_counts=True); strand[p.index] = vals[int(np.argmax(cnt))]
    at = me.attributes.get("lw_strand") or me.attributes.new("lw_strand", "INT", "FACE")
    at.data.foreach_set("value", strand)
    total = np.array([p.loop_total for p in me.polygons])
    pal = PAL
    ca = me.color_attributes.get(name) or me.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
    fc = np.where((strand >= 0)[:, None], pal[np.maximum(strand, 0)], 0.35)
    c = np.ones((len(me.loops), 4), dtype=np.float32); c[:, :3] = np.repeat(fc, total, axis=0)
    ca.data.foreach_set("color", c.reshape(-1))
    me.color_attributes.active_color = ca; me.update()
    return strand


def cap_wedges(P, nb, D, zone, owner, crown, start=0.03, tie=0.05, smooth=10, outward=1.0, behind=0.02):
    """The cap divided like hair parts: every tube that leaves the cap gets a wedge that runs to the crown.
    Each cap vertex gets a direction round the crown (an angle). Near the crown the angle is read off directly;
    farther out a vertex takes the angle of its neighbours nearer the crown, so the angle stays the same along
    the shortest lines from the crown outward. A tube covers the angles of its first ring; a vertex goes to the
    tube whose angles are nearest its own. Returns (labels, G, index, angle) like cap_partition (G = share)."""
    n = len(P); free = zone & (owner < 0)
    zv = np.nonzero(free)[0]
    index = np.full(n, -1, dtype=np.int64); index[zv] = np.arange(len(zv))
    ringv = sorted({int(u) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    labs = sorted({int(owner[u]) for u in ringv})
    c = P[crown]
    nearv = zv[D[zv] < 0.15] if (D[zv] < 0.15).sum() >= 8 else zv
    axis = (c - P[nearv]).sum(axis=0); axis /= max(np.linalg.norm(axis), 1e-9)
    e1 = np.cross(axis, (1.0, 0.0, 0.0))
    if np.linalg.norm(e1) < 0.2:
        e1 = np.cross(axis, (0.0, 1.0, 0.0))
    e1 /= np.linalg.norm(e1); e2 = np.cross(axis, e1)
    z = np.zeros(n, dtype=complex); known = np.zeros(n, dtype=bool)
    todo = np.array(sorted(set(zv.tolist()) | set(ringv), key=lambda v: D[v]), dtype=np.int64)
    seed = [v for v in todo if D[v] < start and v != crown]
    if len(seed) < 6:
        seed = [v for v in todo[:12] if v != crown]
    for v in seed:
        q = P[v] - c; zz = complex(q @ e1, q @ e2)
        if abs(zz) > 1e-9:
            z[v] = zz / abs(zz); known[v] = True
    for v in todo:
        if known[v]:
            continue
        acc = 0j
        for u, l in nb[v]:
            if known[u] and D[u] < D[v]:
                acc += z[u] * (D[v] - D[u]) / max(l, 1e-6)
        if abs(acc) < 1e-12:
            for u, l in nb[v]:
                if known[u]:
                    acc += z[u] / max(l, 1e-6)
        if abs(acc) < 1e-12:
            q = P[v] - c; acc = complex(q @ e1, q @ e2) or 1 + 0j
        z[v] = acc / abs(acc); known[v] = True
    fixed = np.zeros(n, dtype=bool); fixed[seed] = True
    for _ in range(smooth):                         # even out the angle over the surface
        new = z.copy()
        for v in todo:
            if fixed[v]:
                continue
            acc = z[v] * 0.5
            for u, l in nb[v]:
                if known[u]:
                    acc += z[u] * 0.5 / len(nb[v])
            new[v] = acc / max(abs(acc), 1e-12)
        z = new
    ang = np.angle(z)
    # the angles every tube covers: centre and half width of its first ring
    # Going outward from the crown along one direction, the first tube that leaves the cap there takes the
    # surface up to its root; what lies beyond goes to the next tube out. So all borders run along the flow.
    cen = {}; half = {}; rootd = {}
    for k in labs:
        rv = [u for u in ringv if owner[u] == k]
        zz = z[rv]; m = zz.mean(); m = m / abs(m) if abs(m) > 1e-9 else zz[0]
        cen[k] = m; half[k] = float(np.max(np.abs(np.angle(zz / m)))); rootd[k] = float(np.max(D[rv]))
    G = np.zeros((len(zv), len(labs)))
    for j, k in enumerate(labs):
        dev = np.abs(np.angle(z[zv] / cen[k])); gap = rootd[k] - D[zv]
        G[:, j] = (-np.maximum(dev - half[k], 0.0) - tie * dev - outward * np.maximum(gap, 0.0)
                   - np.where(gap < -behind, 10.0, 0.0))
    return labs, G, index, ang


# ---------------------------------------------------------------------------------------------------------
# From detection to something you can use: wires (curves) the hair follows, a colour per wire on the faces,
# and repainting. Paint faces with the colour of another wire, press apply, and those faces (their vertices,
# their place in the strand UV) move over to that wire.

PAL = np.random.default_rng(7).uniform(0.25, 1.0, size=(1024, 3))     # linear colour per wire id


def to_srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def detect_and_bind(hair, wires_obj, root, cap_len=0.40, h=0.01, min_wire=0.05, cut=True, log=None, cap_rule="transport", root_fix=0.05):
    """Finds the strands of `hair`, makes one curve per strand in `wires_obj`, cuts the cap along the borders,
    colours the faces and ties every vertex to its wire. Changes the mesh of `hair` (work on a copy)."""
    from . import strands as S
    R = S.R
    me = hair.data; root = np.asarray(root, float)
    P, T, inv, world = R.gather(hair)
    nb = R.edge_graph(P, T)
    D, comp = S.distance_from_root(P, nb, root)
    crown = int(np.argmin(np.linalg.norm(P - root, axis=1)))
    rings, patches, pv = level_graph(P, T, D, h)
    seg_of_v, segs, st = ring_tree(P, rings, patches, pv, h, cap_len)
    main_root = {i for i, s in enumerate(segs) if s["parent"] < 0 and not s.get("dead")
                 and comp[crown] in set(comp[s["verts"]].tolist())}
    wire_of, wires = wires_from_rings(rings, segs, main_root)
    owner = np.where(seg_of_v >= 0, wire_of[np.maximum(seg_of_v, 0)], -1)
    short = [i for i, w in enumerate(wires) if len(w["rings"]) * h < min_wire]
    owner0 = owner.copy()
    for i in short:
        owner[owner == i] = -3
    lv = np.nonzero(owner == -3)[0]
    if len(lv):
        src = np.nonzero(owner >= 0)[0]
        _d, near = R.spread(nb, src, labels=owner[src]); owner[lv] = near[lv]
        alone = lv[owner[lv] < 0]                 # a small piece on its own (a braid bead): it keeps its short wire
        owner[alone] = owner0[alone]
        short = [i for i in short if not (owner == i).any()]
    if (owner < 0).any():
        f, _info, zone, _ring = S.melted_field(P, T, nb, owner, D, crown)
    else:                                   # every vertex already belongs to a strand: there is no cap
        f = np.full(len(P), np.nan); zone = np.zeros(len(P), dtype=bool)
    if cap_rule == "wedges":
        labs, G, gidx, _ang = cap_wedges(P, nb, D, zone, owner, crown)
    else:
        labs, G, gidx = cap_transport(nb, D, owner < 0, owner)
    melted = owner < 0
    zv = np.nonzero(gidx >= 0)[0]
    if len(zv) and labs:
        Gz = G[gidx[zv]].copy(); la = np.array(labs)
        pick = np.argmax(Gz, axis=1)
        if cap_rule == "wedges":
            for _ in range(6):
                pick = np.argmax(Gz, axis=1); cnt = np.bincount(pick, minlength=len(labs))
                small = np.nonzero((cnt > 0) & (cnt < 10))[0]
                if not len(small):
                    break
                Gz[:, small] = -1e9
        ok = Gz[np.arange(len(zv)), pick] > (1e-9 if cap_rule != "wedges" else -1e8)
        owner[zv[ok]] = la[pick[ok]]
        tid, _m = S.tidy_labels(nb, owner, rounds=4, keep_min=12 if cap_rule != "wedges" else 40); owner[zv] = tid[zv]
    owner, _c = cap_by_flow(nb, f, zone, owner)
    lv = np.nonzero(owner < 0)[0]
    if len(lv):
        src = np.nonzero(owner >= 0)[0]
        _d, near = R.spread(nb, src, labels=owner[src]); owner[lv] = near[lv]
    # one number per wire that has hair, in a row
    used = sorted(int(x) for x in np.unique(owner) if x >= 0)
    new = np.full(len(wires) + 1, -1, dtype=np.int64); new[used] = np.arange(len(used))
    old_n = len(me.vertices)
    # how much a vertex follows its wire: fully. (It used to be less inside the cap and in sheets; then the
    # middle of a strand stayed behind when its wire was bent.) Only the root stretch is held, further down.
    wv = np.ones(len(inv), dtype=np.float32)
    extv = (zone | melted)[inv].astype(np.float32)
    da = me.attributes.get("lw_d") or me.attributes.new("lw_d", "FLOAT", "POINT")
    da.data.foreach_set("value", np.where(np.isfinite(D), D, 0.0)[inv].astype(np.float32))
    if cut:
        edges_cut, faces_split, ids = cut_cap(me, inv, owner, labs, G, gidx)
    else:
        edges_cut = faces_split = 0; ids = owner[inv]
    ids = np.where(ids >= 0, new[np.maximum(ids, 0)], -9)
    strand = face_colours(me, ids)
    nv = len(me.vertices)
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    for pg in me.polygons:                                                       # border vertices: a wire of a face they are on
        for li in range(pg.loop_start, pg.loop_start + pg.loop_total):
            if ids[lvi[li]] < 0 and strand[pg.index] >= 0:
                ids[lvi[li]] = strand[pg.index]
    w_all = np.ones(nv, dtype=np.float32); w_all[:old_n] = wv
    e_all = np.ones(nv, dtype=np.float32); e_all[:old_n] = extv
    if nv > old_n:
        ev = np.empty(len(me.edges) * 2, dtype=np.int32); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
        acc = np.zeros(nv); num = np.zeros(nv)
        for a_, b_ in ev:
            if a_ >= old_n > b_:
                acc[a_] += wv[b_]; num[a_] += 1
            elif b_ >= old_n > a_:
                acc[b_] += wv[a_]; num[b_] += 1
        m = (np.arange(nv) >= old_n) & (num > 0); w_all[m] = (acc[m] / num[m]).astype(np.float32)
    # the wires
    cu = wires_obj.data
    while len(cu.splines):
        cu.splines.remove(cu.splines[0])
    kinds = []; parents = []
    for k in used:
        w = wires[k]; cen = w["centres"]; lead = 0
        # the strip this strand got inside a sheet or the cap: the wire starts there, not where the tube starts
        zs = np.nonzero(melted & (owner == k))[0]
        if len(zs) >= 3 and len(w["rings"]):
            d0 = rings[w["rings"][0]]["level"] * h; zs = zs[D[zs] < d0]
            if len(zs) >= 3:
                bins = np.floor((D[zs] - D[zs].min()) / 0.015).astype(np.int64); pre = []
                for s in range(int(bins.max()) + 1):
                    m = bins == s
                    if m.sum() >= 2:
                        pre.append(P[zs[m]].mean(axis=0))
                if pre:
                    cen = np.vstack([np.array(pre), cen]) if len(cen) else np.array(pre); lead = len(pre)
        c = smooth_line(cen)
        rad = np.full(len(c), 0.01)
        if len(w["rings"]):
            rr = np.array([rings[r]["length"] for r in w["rings"]]) / (2 * np.pi)
            if lead:
                rr = np.concatenate([np.full(lead, rr[0]), rr])
            rad = np.interp(np.linspace(0, 1, len(c)), np.linspace(0, 1, len(rr)), rr)
        if len(c) >= 3:
            c, rad = R.simplify(c, rad, tolerance=0.010)[:2]      # few control points: each one is a grip to move
        if len(c) < 2:
            c = np.vstack([c[:1], c[:1] + (0, 0, -0.01)]) if len(c) else np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -0.01]]); rad = np.full(2, 0.01)
        R.add_spline(wires_obj, c, rad)
        kinds.append(w["kind"]); parents.append(int(new[w["parent"]]) if w["parent"] >= 0 else -1)
    wires_obj["lw_kinds"] = kinds; wires_obj["lw_parent"] = parents
    # tie the vertices
    R.ensure_attrs(me)
    for nm, typ, dom in (("lw_ext", "FLOAT", "POINT"), ("lw_lock", "INT", "FACE")):
        if nm not in me.attributes:
            me.attributes.new(nm, typ, dom)
    _P, _T, _inv, world = R.gather(hair)
    fv = np.zeros(nv, dtype=np.float32)
    for k in range(len(used)):
        vs = np.nonzero(ids == k)[0]
        if len(vs):
            poly = R.spline_polyline(wires_obj, k)
            fv[vs] = R.nearest_on_polyline(poly, world[vs])[0]
            # the root of a strand does not move: nothing for the first stretch, full follow after it
            length = float(np.linalg.norm(np.diff(poly, axis=0), axis=1).sum())
            fade = min(root_fix, 0.3 * length)
            if fade > 1e-6:
                x = np.clip(fv[vs] * length / fade, 0.0, 1.0)
                w_all[vs] = w_all[vs] * (x * x * (3 - 2 * x)).astype(np.float32)
    R._set(me, "lw_id", ids.astype(np.int32)); R._set(me, "lw_f", fv); R._set(me, "lw_w", w_all); R._set(me, "lw_ext", e_all)
    me.attributes["lw_lock"].data.foreach_set("value", np.zeros(len(me.polygons), dtype=np.int32))
    try:
        R.ensure_deform(hair, wires_obj); R.refresh_rest(hair, wires_obj)
        st["rest_shift_mm"] = rest_shift(hair) * 1000
        if st["rest_shift_mm"] > 0.05:
            raise RuntimeError("the hair moved %.3f mm when it was tied to the wires" % st["rest_shift_mm"])
    except Exception:
        md = hair.modifiers.get(R.GROUP)
        if md is not None:
            hair.modifiers.remove(md)
        raise
    hair["lw_picked"] = []; hair["lw_hidden"] = []; hair["lw_new"] = []
    kk = {}
    for x in kinds:
        kk[x] = kk.get(x, 0) + 1
    st.update(wires=len(used), kinds=kk, short_merged=len(short), cap_vertices=int(zone.sum()), edges_cut=int(edges_cut),
              faces_split=int(faces_split), vertices=int(nv), faces=int(len(me.polygons)))
    return st


def rest_shift(hair):
    """How far the deform moves the hair right now (metres), other modifiers switched off for the check."""
    import bpy
    from . import strands as S
    me = hair.data; dm = hair.modifiers.get(S.R.GROUP)
    others = [(m, m.show_viewport) for m in hair.modifiers if m is not dm]
    for m, _s in others:
        m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get(); dg.update()
        ev = hair.evaluated_get(dg).data
        if len(ev.vertices) != len(me.vertices):
            return float("inf")
        e = np.empty(len(ev.vertices) * 3, dtype=np.float32); ev.vertices.foreach_get("co", e)
        r = np.empty(len(me.vertices) * 3, dtype=np.float32); me.vertices.foreach_get("co", r)
        return float(np.abs(e - r).max())
    finally:
        for m, s in others:
            m.show_viewport = s


def face_strands(me):
    s = np.empty(len(me.polygons), dtype=np.int32); me.attributes["lw_strand"].data.foreach_get("value", s)
    return s


def set_face_colours(me, strand, name="lw_strand_col"):
    total = np.array([p.loop_total for p in me.polygons])
    ca = me.color_attributes.get(name) or me.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
    fc = np.where((strand >= 0)[:, None], PAL[np.maximum(strand, 0)], 0.35)
    c = np.ones((len(me.loops), 4), dtype=np.float32); c[:, :3] = np.repeat(fc, total, axis=0)
    ca.data.foreach_set("color", c.reshape(-1)); me.update()


def apply_repaint(hair, wires_obj, tol=0.12, changed_min=0.04, keep_min=6):
    """Reads the face colours. A face painted with the colour of another wire moves to that wire: the face, its
    vertices (they are tied to the new wire where it is now) and so its place in the strand UV. Painted faces are
    locked. Small pieces a wire is left with, cut off from the rest of it, join what surrounds them. Faces painted
    only partly, or with no wire's colour, go back to their own colour."""
    from . import strands as S
    R = S.R
    me = hair.data; strand = face_strands(me); nf = len(strand)
    ca = me.color_attributes["lw_strand_col"]
    col = np.empty(len(me.loops) * 4, dtype=np.float32); ca.data.foreach_get("color", col); col = col.reshape(-1, 4)[:, :3]
    start = np.array([p.loop_start for p in me.polygons]); total = np.array([p.loop_total for p in me.polygons])
    mean = np.add.reduceat(col, start, axis=0) / total[:, None]
    own = PAL[np.maximum(strand, 0)]
    n_w = len(wires_obj.data.splines)
    cand = [int(k) for k in hair.get("lw_picked", []) if 0 <= int(k) < n_w] or list(range(n_w))
    touched = np.nonzero((np.linalg.norm(mean - own, axis=1) > changed_min) & (strand >= 0))[0]
    moved = []; reverted = 0
    if len(touched):
        d = np.linalg.norm(mean[touched][:, None, :] - PAL[cand][None, :, :], axis=2)
        best = np.argmin(d, axis=1)
        for fi, b, dd in zip(touched, best, d[np.arange(len(touched)), best]):
            k = cand[int(b)]
            if dd < tol and k != strand[fi]:
                moved.append((int(fi), int(strand[fi]), k))
            else:
                reverted += 1
    lock = np.empty(nf, dtype=np.int32); me.attributes["lw_lock"].data.foreach_get("value", lock)
    for fi, _o, k in moved:
        strand[fi] = k; lock[fi] = 1
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
        seen = np.zeros(nf, dtype=bool); comps = {}
        for s in range(nf):
            if seen[s] or strand[s] < 0:
                continue
            k = strand[s]; stack = [s]; seen[s] = True; comp = [s]
            while stack:
                v = stack.pop()
                for u in adj[v]:
                    if not seen[u] and strand[u] == k:
                        seen[u] = True; stack.append(u); comp.append(u)
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
                    strand[comp] = vals[int(np.argmax(cnt))]; rejoined += len(comp)
    me.attributes["lw_strand"].data.foreach_set("value", strand)
    me.attributes["lw_lock"].data.foreach_set("value", lock)
    # vertices follow their faces
    ids = R._get(me, "lw_id").astype(np.int64); nv = len(ids)
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    per = [[] for _ in range(nv)]
    for pg in me.polygons:
        for li in range(pg.loop_start, pg.loop_start + pg.loop_total):
            per[lvi[li]].append(int(strand[pg.index]))
    change = np.zeros(nv, dtype=bool)
    for v in range(nv):
        ks = [k for k in per[v] if k >= 0]
        if ks and ids[v] not in ks:
            vals, cnt = np.unique(ks, return_counts=True); ids[v] = int(vals[int(np.argmax(cnt))]); change[v] = True
    if change.any():
        _P, _T, _inv, world = R.gather(hair)
        fv = R._get(me, "lw_f")
        for k in np.unique(ids[change]):
            vs = np.nonzero(change & (ids == k))[0]
            fv[vs] = R.nearest_on_polyline(R.spline_polyline(wires_obj, int(k)), world[vs])[0]
        R._set(me, "lw_id", ids.astype(np.int32)); R._set(me, "lw_f", fv)
        R.refresh_rest(hair, wires_obj, which=change)
    fitted = 0
    for k in [int(x) for x in hair.get("lw_new", [])]:
        if (strand == k).sum() >= 3 and fit_wire(hair, wires_obj, k, strand):
            fitted += 1
    set_face_colours(me, strand)
    have = set(np.unique(strand).tolist())
    hair["lw_picked"] = []
    return dict(wires_fitted=fitted, faces_moved=len(moved), faces_reverted=int(reverted), faces_rejoined=int(rejoined),
                vertices_moved=int(change.sum()), wires_without_faces=[k for k in range(n_w) if k not in have])


def set_hidden(hair, hidden):
    """Hides the faces of the wires in `hidden` (a list of wire ids), shows the rest."""
    me = hair.data; strand = face_strands(me)
    hide = np.isin(strand, list(hidden)) if len(hidden) else np.zeros(len(strand), dtype=bool)
    me.polygons.foreach_set("hide", hide)
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    total = np.array([p.loop_total for p in me.polygons])
    vis = np.zeros(len(me.vertices), dtype=bool); vis[lvi[np.repeat(~hide, total)]] = True
    me.vertices.foreach_set("hide", ~vis)
    ev = np.empty(len(me.edges) * 2, dtype=np.int32); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
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
        gi = g.nodes.new("NodeGroupInput"); go = g.nodes.new("NodeGroupOutput")
        na = g.nodes.new("GeometryNodeInputNamedAttribute"); na.data_type = "BOOLEAN"; na.inputs["Name"].default_value = "lw_hide"
        dl = g.nodes.new("GeometryNodeDeleteGeometry"); dl.domain = "FACE"
        g.links.new(gi.outputs[0], dl.inputs["Geometry"]); g.links.new(na.outputs["Attribute"], dl.inputs["Selection"])
        g.links.new(dl.outputs["Geometry"], go.inputs[0])
    md = hair.modifiers.get(HIDE_GROUP)
    if md is None:
        md = hair.modifiers.new(HIDE_GROUP, "NODES"); md.node_group = g; md.show_render = False
        want = hair.modifiers.find("LidaHairRewire") + 1
        while hair.modifiers.find(HIDE_GROUP) > want:
            hair.modifiers.move(hair.modifiers.find(HIDE_GROUP), hair.modifiers.find(HIDE_GROUP) - 1)
    md.show_viewport = bool(show)
    return md


def wire_table(hair, wires_obj):
    """[(wire id, faces, kind)] for every wire of the hair."""
    strand = face_strands(hair.data); cnt = np.bincount(strand[strand >= 0], minlength=len(wires_obj.data.splines))
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
    hair["lw_current"] = k; hair["lw_picked"] = [int(x) for x in hair.get("lw_picked", [])] + [k]
    return k


def replace_spline(wires_obj, index, pos, rad):
    """Gives spline `index` new points and keeps every other spline, and the order, as it is."""
    from . import strands as S
    cu = wires_obj.data; keep = []
    for sp in cu.splines:
        keep.append([(bp.co.copy(), bp.handle_left.copy(), bp.handle_right.copy(), bp.handle_left_type, bp.handle_right_type,
                      bp.radius) for bp in sp.bezier_points])
    while len(cu.splines):
        cu.splines.remove(cu.splines[0])
    for i, pts in enumerate(keep):
        if i == index:
            S.R.add_spline(wires_obj, pos, rad); continue
        sp = cu.splines.new("BEZIER"); sp.bezier_points.add(len(pts) - 1); sp.resolution_u = 8
        for bp, (co, hl, hr, tl, tr, r) in zip(sp.bezier_points, pts):
            bp.co = co; bp.handle_left_type = tl; bp.handle_right_type = tr; bp.handle_left = hl; bp.handle_right = hr; bp.radius = r


def fit_wire(hair, wires_obj, k, strand=None):
    """Lays wire k through the middle of its faces, from the crown side to the tip side, and ties their vertices
    to it where it now lies."""
    from . import strands as S
    R = S.R; me = hair.data
    strand = face_strands(me) if strand is None else strand
    if "lw_d" not in me.attributes:
        return False
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    total = np.array([p.loop_total for p in me.polygons])
    vs = np.unique(lvi[np.repeat(strand == k, total)])
    if len(vs) < 3:
        return False
    _P, _T, _inv, world = R.gather(hair)
    d = R._get(me, "lw_d")[vs]; p = world[vs]
    step = 0.01; b = np.floor((d - d.min()) / step).astype(np.int64)
    cen = []; rad = []
    for s in range(int(b.max()) + 1):
        m = b == s
        if m.any():
            c = p[m].mean(axis=0); cen.append(c); rad.append(max(float(np.linalg.norm(p[m] - c, axis=1).max()), 0.003))
    if len(cen) < 2:                                   # painted across, not along: a short line along its longest side
        c = p.mean(axis=0); sv = np.linalg.svd(p - c, full_matrices=False); ax = sv[2][0] * max(float(sv[1][0]) / max(len(p), 1) ** 0.5, 0.005)
        cen = [c - ax, c + ax]; rad = [0.005, 0.005]
    line = smooth_line(np.array(cen)); rr = np.interp(np.linspace(0, 1, len(line)), np.linspace(0, 1, len(rad)), rad)
    if len(line) >= 3:
        line, rr = R.simplify(line, rr, tolerance=0.004)[:2]
    replace_spline(wires_obj, k, line, rr)
    ids = R._get(me, "lw_id").astype(np.int64); fv = R._get(me, "lw_f")
    mine = np.zeros(len(ids), dtype=bool); mine[vs] = True; mine &= ids == k
    if mine.any():
        fv[mine] = R.nearest_on_polyline(R.spline_polyline(wires_obj, k), world[mine])[0]
        R._set(me, "lw_f", fv); R.refresh_rest(hair, wires_obj, which=mine)
    hair["lw_new"] = [int(x) for x in hair.get("lw_new", []) if int(x) != k]
    return True


BIND_ATTRS = ("lw_id", "lw_f", "lw_w", "lw_r0", "lw_p0", "lw_t0", "lw_n0", "lw_ext", "lw_d", "lw_hide", "lw_lock", "lw_cut")


def finalize(hair, wires_obj, keep_colours=True):
    """Writes the bent shape into the mesh and takes the machinery away: the bend and hide modifiers, the wires,
    the attributes that tie vertices to wires. The colour per strand (lw_strand, lw_strand_col) and the strand UV
    stay unless keep_colours is off. After this the hair is an ordinary mesh; to bend again, detect again."""
    import bpy
    from . import strands as S
    R = S.R; me = hair.data
    if me.shape_keys is not None:
        raise RuntimeError("the mesh has shape keys; the bent shape cannot be written into it")
    if me.users > 1:
        raise RuntimeError("the mesh is used by %d objects" % me.users)
    dm = hair.modifiers.get(R.GROUP); moved = 0.0
    if dm is not None:
        others = [(m, m.show_viewport) for m in hair.modifiers if m is not dm]
        for m, _s in others:
            m.show_viewport = False
        was = dm.show_viewport; dm.show_viewport = True
        try:
            dg = bpy.context.evaluated_depsgraph_get(); dg.update()
            ev = hair.evaluated_get(dg).data
            if len(ev.vertices) != len(me.vertices):
                raise RuntimeError("the bent mesh has another number of vertices")
            co = np.empty(len(ev.vertices) * 3, dtype=np.float32); ev.vertices.foreach_get("co", co)
            old = np.empty(len(me.vertices) * 3, dtype=np.float32); me.vertices.foreach_get("co", old)
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


def strand_uv2(hair, wires_obj, name="LW_StrandUV", margin=0.004, method="MINIMUM_STRETCH", deep=0.6, squash=0.3, fold_cut=False):
    """A UV map with one island per strand, made by a real unwrap (no stretching by hand):
    seams on the borders between strands; where a strand is a closed tube, one seam along its length (a path of
    edges from its root end to its tip, kept on one side); Blender's unwrap; then every island at its true size,
    turned so that the root is up and the tip down, and packed without turning.
    Other UV maps, the seams of the mesh, hidden faces and the selection are left as they were."""
    import heapq
    import bpy
    from . import strands as S
    R = S.R; me = hair.data
    strand = face_strands(me); nf = len(strand)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    _P, _T, _inv, world = R.gather(hair)
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    start = np.array([p.loop_start for p in me.polygons]); total = np.array([p.loop_total for p in me.polygons])
    face_of_loop = np.repeat(np.arange(nf), total)
    ek = {key: i for i, key in enumerate(me.edge_keys)}
    efaces = [[] for _ in range(len(me.edges))]
    for pg in me.polygons:
        for key in pg.edge_keys:
            efaces[ek[key]].append(pg.index)
    seam0 = np.empty(len(me.edges), dtype=bool); me.edges.foreach_get("use_seam", seam0)
    seam = np.zeros(len(me.edges), dtype=bool)
    for ei, fs in enumerate(efaces):
        if len(fs) != 2 or strand[fs[0]] != strand[fs[1]]:
            seam[ei] = True                                    # borders between strands, open edges, fans
    ev = np.empty(len(me.edges) * 2, dtype=np.int32); me.edges.foreach_get("vertices", ev); ev = ev.reshape(-1, 2)
    elen = np.linalg.norm(world[ev[:, 0]] - world[ev[:, 1]], axis=1)
    fpar = np.zeros(len(me.loops), dtype=np.float32)             # along the wire, per face corner (to turn the islands)
    n_w = len(wires_obj.data.splines)
    for k in np.unique(strand[strand >= 0]):
        k = int(k)
        if k >= n_w:
            continue
        loops = np.nonzero(strand[face_of_loop] == k)[0]; vs = np.unique(lvi[loops])
        ff, _d = R.nearest_on_polyline(R.spline_polyline(wires_obj, k), world[vs])
        look = np.full(len(me.vertices), -1, dtype=np.int64); look[vs] = np.arange(len(vs))
        fpar[loops] = ff[look[lvi[loops]]]
    # Every island must be a flat-able piece (a disc). That is decided by how the faces hang together, not by
    # where the wire is: an island with no rim (a bead) gets a slit; one with two or more rims (a tube open at
    # both ends) gets a cut from rim to rim; one with a single rim that is deep (a sock: a tube closed at the tip)
    # gets a cut from the rim to its far end.
    fedges = [[ek[key] for key in pg.edge_keys] for pg in me.polygons]
    tubes = 0
    for _round in range(3):
        par = np.arange(nf)

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        for ei, fs in enumerate(efaces):
            if not seam[ei] and len(fs) == 2:
                ra, rb = find(fs[0]), find(fs[1])
                if ra != rb:
                    par[rb] = ra
        root = np.array([find(f) for f in range(nf)]); root[strand < 0] = -1
        groups = {}
        for f in np.nonzero(root >= 0)[0]:
            groups.setdefault(int(root[f]), []).append(int(f))
        added = 0
        for faces in groups.values():
            if len(faces) < 4:
                continue
            es = {e for f in faces for e in fedges[f]}
            rim = [e for e in es if seam[e]]; inner = [e for e in es if not seam[e]]
            adj = {}
            for e in inner:
                a_, b_ = int(ev[e, 0]), int(ev[e, 1]); c = float(elen[e]) + 1e-9
                adj.setdefault(a_, []).append((b_, c, e)); adj.setdefault(b_, []).append((a_, c, e))
            if len(adj) < 3:
                continue
            # rims: loops of seam edges round this island
            rp = {}

            def rfind(x):
                while rp.setdefault(x, x) != x:
                    rp[x] = rp[rp[x]]; x = rp[x]
                return x
            for e in rim:
                ra, rb = rfind(int(ev[e, 0])), rfind(int(ev[e, 1]))
                if ra != rb:
                    rp[rb] = ra
            loops_ = {}
            for v in list(rp):
                loops_.setdefault(rfind(v), []).append(v)
            rims = sorted(loops_.values(), key=len, reverse=True)

            def spread_from(sources):
                dist = {v: 0.0 for v in sources if v in adj}; prev = {}; heap = [(0.0, v) for v in dist]
                heapq.heapify(heap)
                while heap:
                    dd, v = heapq.heappop(heap)
                    if dd > dist.get(v, 1e18):
                        continue
                    for u, c, e in adj[v]:
                        nd = dd + c
                        if nd < dist.get(u, 1e18):
                            dist[u] = nd; prev[u] = (v, e); heapq.heappush(heap, (nd, u))
                return dist, prev

            def cut_back(v, prev):
                nonlocal added
                while v in prev:
                    v, e = prev[v]; seam[e] = True; added += 1

            if not rims:                                            # a bead: slit between its two far ends
                v0 = next(iter(adj)); d0, _p = spread_from([v0]); a_ = max(d0, key=d0.get)
                d1, p1 = spread_from([a_]); b_ = max(d1, key=d1.get); cut_back(b_, p1); tubes += 1
            elif len(rims) >= 2:                                    # a tube open at both ends: rim to rim
                d1, p1 = spread_from(rims[0])
                for other in rims[1:]:
                    cand = [v for v in other if v in d1]
                    if cand:
                        cut_back(min(cand, key=lambda v: d1[v]), p1)
                tubes += 1
            else:                                                   # one rim: a sock if it is deep
                d1, p1 = spread_from(rims[0])
                if d1:
                    far = max(d1, key=d1.get); rim_len = float(sum(elen[e] for e in rim))
                    if d1[far] > deep * rim_len:
                        cut_back(far, p1); tubes += 1
        if not added:
            break
    me.edges.foreach_set("use_seam", seam)
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name, do_init=False)
    stage = _stage_enter([hair], name)
    edit = _edit_all

    islands = 0
    try:
        area3 = np.empty(nf, dtype=np.float32); me.polygons.foreach_get("area", area3)
        cut_out = 0; unsolved = 0
        for attempt in range(4):
            me.edges.foreach_set("use_seam", seam)
            try:
                edit(lambda: bpy.ops.uv.unwrap(method=method, margin=0.001))
            except TypeError:                                       # a Blender without that method
                method = "ANGLE_BASED"; edit(lambda: bpy.ops.uv.unwrap(method=method, margin=0.001))
            layer = me.uv_layers[name]
            uv = np.empty(len(me.loops) * 2, dtype=np.float32); layer.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2).astype(np.float64)
            par = np.arange(nf)

            def find(x):
                while par[x] != x:
                    par[x] = par[par[x]]; x = par[x]
                return x
            for ei, fs in enumerate(efaces):
                if not seam[ei] and len(fs) == 2:
                    ra, rb = find(fs[0]), find(fs[1])
                    if ra != rb:
                        par[rb] = ra
            root = np.array([find(i) for i in range(nf)]); root[strand < 0] = -1
            # islands the unwrap could not solve come out collapsed: those alone are unwrapped again the plain way
            _u, isl = np.unique(root, return_inverse=True)
            ua_i = np.bincount(isl, weights=_uv_area(uv, start, total)); a3_i = np.bincount(isl, weights=area3.astype(np.float64))
            ratio = ua_i / np.maximum(a3_i, 1e-14); live = (a3_i > 1e-10) & (_u >= 0)
            if live.any() and method != "ANGLE_BASED":
                failed = live & ~(ratio > 0.02 * np.median(ratio[live]))
                if failed.any():
                    pick = failed[isl]; unsolved += int(failed.sum())
                    me.polygons.foreach_set("select", pick)
                    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_mode(type="FACE")
                    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001); bpy.ops.object.mode_set(mode="OBJECT")
                    layer = me.uv_layers[name]
                    uv = np.empty(len(me.loops) * 2, dtype=np.float32); layer.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2).astype(np.float64)
            if attempt == 3:
                break
            # faces the unwrap squashed (far less room in the UV than their neighbours of the same island get for
            # the same size of surface) are cut out, to become islands of their own at their true size
            dens = _uv_area(uv, start, total) / np.maximum(area3.astype(np.float64), 1e-14)
            real = area3 > 1e-10; squashed = np.zeros(nf, dtype=bool)
            order = np.argsort(root, kind="stable"); rs = root[order]; cuts = np.nonzero(np.diff(rs))[0] + 1
            for grp in np.split(order, cuts):
                if root[grp[0]] < 0 or len(grp) < 2:
                    continue
                g = grp[real[grp]]
                if len(g) < 2:
                    continue
                # against the island's own average (surface-weighted): the median fails when most of it is squashed
                med = float((dens[g] * area3[g]).sum() / max(float(area3[g].sum()), 1e-14)); squashed[g[dens[g] < squash * med]] = True
            tight = squashed.copy()
            if fold_cut:
                squashed |= _folded_faces(me, uv)                   # and faces lying on top of others in the UV
            if not squashed.any():
                break
            alone = attempt == 2                                    # last try: each face still squashed on its own
            for ei, fs in enumerate(efaces):
                if not seam[ei] and len(fs) == 2 and (squashed[fs[0]] != squashed[fs[1]] or (alone and tight[fs[0]] and tight[fs[1]])):
                    seam[ei] = True
            cut_out += int(squashed.sum())
        x_at = 0.0
        for r in np.unique(root[root >= 0]):
            faces = np.nonzero(root == r)[0]
            loops = np.concatenate([np.arange(start[f], start[f] + total[f]) for f in faces])
            q = uv[loops]; ft = fpar[loops].astype(np.float64); ua = 0.0
            for f in faces:
                c = uv[start[f]:start[f] + total[f]]
                ua += abs(float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1]))) / 2
            a3 = float(area3[faces].sum())
            if ua < 1e-14 or a3 < 1e-12:
                uv[loops] = (x_at, 0.0); continue
            qc = (q - q.mean(axis=0)) * np.sqrt(a3 / ua)                    # true size
            _u, sv, vt = np.linalg.svd(qc, full_matrices=False); ax = vt[0]
            if sv[0] < sv[1] * 1.3:                                         # not long: turn by where the wire runs
                g = (qc * (ft - ft.mean())[:, None]).sum(axis=0)
                ax = g / np.linalg.norm(g) if np.linalg.norm(g) > 1e-12 else ax
            if float(((qc @ ax) * (ft - ft.mean())).sum()) < 0:
                ax = -ax                                                    # ax: from root to tip
            rot = np.array([[-ax[1], ax[0]], [-ax[0], -ax[1]]])             # root up, tip down
            qc = qc @ rot.T; qc -= qc.min(axis=0)
            uv[loops] = qc + (x_at, 0.0); x_at += float(qc[:, 0].max()) + 0.01; islands += 1
        layer.data.foreach_set("uv", uv.astype(np.float32).reshape(-1)); me.update()
        me.edges.foreach_set("use_seam", seam)
        edit(lambda: _pack(margin))
    finally:
        _stage_exit(stage)
        me.edges.foreach_set("use_seam", seam0)
    return dict(strips=int(islands), strands=int(len(np.unique(strand[strand >= 0]))), tubes_cut=int(tubes), squashed_cut_out=int(cut_out), unsolved_islands=int(unsolved),
                seam_edges=int(seam.sum()), faces=int((strand >= 0).sum()))


def uv_quality(me, name="LW_StrandUV"):
    """How good a UV map is: flipped faces, stretch (edge length in UV against 3D, per island it should be even)."""
    uv = np.empty(len(me.loops) * 2, dtype=np.float32); me.uv_layers[name].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2).astype(np.float64)
    co = np.empty(len(me.vertices) * 3, dtype=np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
    flipped = 0; ratio = []; zero = 0
    for p in me.polygons:
        ls = np.arange(p.loop_start, p.loop_start + p.loop_total); c = uv[ls]
        sa = float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1])) / 2
        if abs(sa) < 1e-12:
            zero += 1; continue
        flipped += sa < 0
        l2 = np.linalg.norm(c - np.roll(c, -1, axis=0), axis=1); l3 = np.linalg.norm(co[lvi[ls]] - np.roll(co[lvi[ls]], -1, axis=0), axis=1)
        m = l3 > 1e-6
        ratio += list(l2[m] / l3[m])
    r = np.array(ratio); med = np.median(r) if len(r) else 1.0
    flipped = min(int(flipped), len(me.polygons) - zero - int(flipped))      # islands are all one way round
    return dict(faces=len(me.polygons), flipped=int(flipped), zero_area=int(zero),
                stretch_p05=float(np.percentile(r / med, 5)), stretch_p95=float(np.percentile(r / med, 95)),
                edges_within_20pct=float((np.abs(r / med - 1) < 0.2).mean()))


def _uv_arrays(me, name):
    uv = np.empty(len(me.loops) * 2, dtype=np.float32); me.uv_layers[name].data.foreach_get("uv", uv)
    start = np.array([p.loop_start for p in me.polygons]); total = np.array([p.loop_total for p in me.polygons])
    return uv.reshape(-1, 2).astype(np.float64), start, total


def _uv_area(uv, start, total):
    out = np.zeros(len(start))
    for f in range(len(start)):
        c = uv[start[f]:start[f] + total[f]]
        out[f] = abs(float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1]))) / 2
    return out


def uv_trouble(hair, name="LW_StrandUV", size=2048):
    """Faces of this hair that cannot carry a texture well in the strand UV: folded (on top of others) and squashed."""
    me = hair.data; uv, start, total = _uv_arrays(me, name)
    folded = _folded_faces(me, uv, size)
    a3 = np.empty(len(me.polygons), dtype=np.float32); me.polygons.foreach_get("area", a3)
    dens = _uv_area(uv, start, total) / np.maximum(a3.astype(np.float64), 1e-14); real = a3 > 1e-10
    squashed = real & (dens < 0.1 * np.median(dens[real])) if real.any() else np.zeros(len(a3), dtype=bool)
    bad = folded | squashed; tot = float(a3.sum())
    return dict(folded=int(folded.sum()), squashed=int(squashed.sum()), bad_area=float(a3[bad].sum()), area=tot,
                share=float(a3[bad].sum()) / tot if tot > 0 else 0.0)                 # share of the surface, not of the count


def strand_uv_auto(hair, wires_obj, name="LW_StrandUV", ok_share=0.01):
    """The strand UV, made the tidy way first; if too many faces fold or are squashed on this hair, made again with
    the folded parts cut out as islands of their own (more islands, no faces on top of each other). The better of
    the tries is kept. Returns the result of strand_uv2 plus what was tried."""
    tries = []; best = None
    for label, kw in (("tidy", dict(fold_cut=False)), ("cut folds", dict(fold_cut=True)),
                      ("cut folds, angle", dict(fold_cut=True, method="ANGLE_BASED"))):
        _tell(_tr("UV を展開中（%d 回目）") % (len(tries) + 1), 0.05 + 0.25 * len(tries))
        r = strand_uv2(hair, wires_obj, name=name, **kw)
        _tell(_tr("重なりとつぶれを調べ中"), 0.2 + 0.25 * len(tries)); tr = uv_trouble(hair, name)
        tries.append(dict(way=label, islands=r["strips"], **tr))
        if best is None or tr["share"] < 0.7 * best[1]["share"]:       # more islands only for a real gain
            uv = np.empty(len(hair.data.loops) * 2, dtype=np.float32); hair.data.uv_layers[name].data.foreach_get("uv", uv)
            best = (r, tr, uv, label)
        if tr["share"] <= ok_share:
            break
    if best[3] != tries[-1]["way"]:
        hair.data.uv_layers[name].data.foreach_set("uv", best[2]); hair.data.update()
    out = dict(best[0]); out["tries"] = tries; out["way"] = best[3]; out.update(best[1])
    return out


PROGRESS = None          # set by the panel: a function (text, share 0-1) called at the slow steps
TRANSLATE = None         # set by the panel: gives a progress text in the language of the panel


def _tr(text):
    return TRANSLATE(text) if TRANSLATE is not None else text


def _tell(text, share):
    if PROGRESS is not None:
        try:
            PROGRESS(text, share)
        except Exception:
            pass


def _folded_faces(me, uv, size=2048):
    """Faces whose place in the UV is shared with another face (a fold: the unwrap laid one part of an island over
    another). Drawn into a picture; where a texel's centre lies inside two triangles of different faces, both."""
    me.calc_loop_triangles()
    tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
    tp = np.empty(len(me.loop_triangles), dtype=np.int32); me.loop_triangles.foreach_get("polygon_index", tp)
    C = uv[tl] * size; owner = np.full((size, size), -1, dtype=np.int32); out = np.zeros(len(me.polygons), dtype=bool)
    den_all = (C[:, 1, 0] - C[:, 0, 0]) * (C[:, 2, 1] - C[:, 0, 1]) - (C[:, 2, 0] - C[:, 0, 0]) * (C[:, 1, 1] - C[:, 0, 1])
    for ti in range(len(tl)):
        den = den_all[ti]
        if abs(den) < 1e-9:
            continue
        a_, b_, c_ = C[ti]
        x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))), 0); x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))), size - 1)
        y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))), 0); y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))), size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
        w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
        ins = (w1 > 0.02) & (w2 > 0.02) & (w1 + w2 < 0.98)
        if not ins.any():
            continue
        view = owner[y0:y1 + 1, x0:x1 + 1]; old = view[ins]; f = int(tp[ti])
        hit = old[(old >= 0) & (old != f)]
        if len(hit):
            out[f] = True; out[np.unique(hit)] = True
        old[:] = f; view[ins] = old
    return out


def _stage_enter(hairs, name):
    """Ready for a UV operator on these hairs: object mode, only they are selected, their strand UV is the active
    map, nothing hidden. Returns what _stage_exit needs to put everything back."""
    import bpy
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view = bpy.context.view_layer
    stage = dict(active=view.objects.active, selected=[o for o in view.objects if o.select_get()], hairs=[])
    for h in hairs:
        me = h.data; nf = len(me.polygons)
        hide0 = np.empty(nf, dtype=bool); me.polygons.foreach_get("hide", hide0)
        stage["hairs"].append((h, me.uv_layers.active.name if me.uv_layers.active else None,
                               next((l.name for l in me.uv_layers if l.active_render), None), h.hide_get(), h.hide_select, bool(hide0.any())))
        if hide0.any():
            me.polygons.foreach_set("hide", np.zeros(nf, dtype=bool)); me.vertices.foreach_set("hide", np.zeros(len(me.vertices), dtype=bool))
            me.edges.foreach_set("hide", np.zeros(len(me.edges), dtype=bool))
        me.uv_layers.active = me.uv_layers[name]
        h.hide_set(False); h.hide_select = False
    for o in view.objects:
        o.select_set(o in hairs)
    view.objects.active = hairs[0]
    return stage


def _stage_exit(stage):
    import bpy
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    view = bpy.context.view_layer
    for h, act, ren, hid, unsel, had in stage["hairs"]:
        me = h.data
        if act and act in me.uv_layers:
            me.uv_layers.active = me.uv_layers[act]
        if ren and ren in me.uv_layers:
            me.uv_layers[ren].active_render = True
        h.hide_select = unsel; h.hide_set(hid)
        if had:
            set_hidden(h, [int(x) for x in h.get("lw_hidden", [])])
    for o in view.objects:
        o.select_set(o in stage["selected"])
    view.objects.active = stage["active"]


def _edit_all(fn):
    """Runs fn in edit mode with every face of the selected objects selected."""
    import bpy
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE"); bpy.ops.mesh.select_all(action="SELECT")
    fn()
    bpy.ops.object.mode_set(mode="OBJECT")


def _pack(margin):
    """Islands packed along their outlines, not turned (the root stays up)."""
    import bpy
    try:
        bpy.ops.uv.pack_islands(rotate=False, margin=margin, shape_method="CONCAVE")
    except TypeError:
        bpy.ops.uv.pack_islands(rotate=False, margin=margin)


def fill_strandless(me):
    """Faces that came out of the detection without a strand take the strand most of their neighbours have
    (over edges, repeated; a piece with no neighbour at all takes the nearest face's). Returns how many."""
    strand = face_strands(me).copy(); miss = int((strand < 0).sum())
    if not miss or miss == len(strand):
        return 0
    ek = {}
    for pg in me.polygons:
        for key in pg.edge_keys:
            ek.setdefault(key, []).append(pg.index)
    nbr = [[] for _ in range(len(strand))]
    for fs in ek.values():
        for x in fs:
            nbr[x].extend(y for y in fs if y != x)
    for _round in range(64):
        todo = np.nonzero(strand < 0)[0]; new = {}
        for f in todo:
            c = [int(strand[g]) for g in nbr[f] if strand[g] >= 0]
            if c:
                new[int(f)] = max(set(c), key=c.count)
        if not new:
            break
        for f, k in new.items():
            strand[f] = k
    todo = np.nonzero(strand < 0)[0]
    if len(todo):
        cen = np.empty(len(me.polygons) * 3, dtype=np.float32); me.polygons.foreach_get("center", cen); cen = cen.reshape(-1, 3)
        have = np.nonzero(strand >= 0)[0]
        for f in todo:
            strand[f] = strand[have[int(np.argmin(((cen[have] - cen[f]) ** 2).sum(axis=1)))]]
    me.attributes["lw_strand"].data.foreach_set("value", strand.astype(np.int32))
    set_face_colours(me, strand)
    return miss


def drop_unused_groups():
    """Node groups of this tool that nothing uses any more (after finalize, after binding)."""
    import bpy
    from . import strands as S
    R = S.R; gone = []
    for nm in (R.BIND_GROUP, R.GROUP, HIDE_GROUP):
        g = bpy.data.node_groups.get(nm)
        if g is not None and g.users == 0:
            bpy.data.node_groups.remove(g); gone.append(nm)
    return gone


def pack_together(hairs, name="LW_StrandUV", margin=0.004):
    """The strand islands of all the hairs in ONE 0-1 square (one texture for all of them): first the same
    size of texture per size of surface on every hair, then packed together without turning."""
    import bpy
    hairs = [h for h in hairs if name in h.data.uv_layers]
    if not hairs:
        return 0
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for h in hairs:                                              # same texel density on every hair
        me = h.data; uv, start, total = _uv_arrays(me, name)
        a3 = np.empty(len(me.polygons), dtype=np.float32); me.polygons.foreach_get("area", a3)
        s = np.abs(np.linalg.det(np.array(h.matrix_world.to_3x3()))) ** (2.0 / 3.0)
        ua = float(_uv_area(uv, start, total).sum()); wa = float(a3.sum()) * s
        if ua > 1e-12 and wa > 1e-12:
            uv *= np.sqrt(wa / ua)
            me.uv_layers[name].data.foreach_set("uv", uv.astype(np.float32).reshape(-1)); me.update()
    stage = _stage_enter(hairs, name)
    try:
        _edit_all(lambda: _pack(margin))
    finally:
        _stage_exit(stage)
    return len(hairs)


def uv_check(hairs, name="LW_StrandUV", size=2048, gap=2, max_trouble=0.02):
    """Is the strand UV fit to carry a texture made elsewhere? Everything inside 0-1, no island on top of
    another (drawn into a size x size picture: places covered twice), and at least `gap` pixels between islands."""
    ids = np.zeros((size, size), dtype=np.int32); twice = 0; covered = 0
    lo = np.array([1e9, 1e9]); hi = -lo; base = 0; n_isl = 0; zero = 0; faces = 0
    for h in hairs:
        me = h.data
        if name not in me.uv_layers:
            continue
        uv, start, total = _uv_arrays(me, name); nf = len(start); faces += nf
        lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
        lo = np.minimum(lo, uv.min(axis=0)); hi = np.maximum(hi, uv.max(axis=0))
        par = np.arange(nf); seen = {}

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        q = np.round(uv * 1e5).astype(np.int64)
        for f in range(nf):
            for l in range(start[f], start[f] + total[f]):
                key = (int(lvi[l]), int(q[l, 0]), int(q[l, 1])); g = seen.get(key)
                if g is None:
                    seen[key] = f
                else:
                    ra, rb = find(g), find(f)
                    if ra != rb:
                        par[rb] = ra
        root = np.array([find(f) for f in range(nf)]); uniq, isl = np.unique(root, return_inverse=True)
        n_isl += len(uniq)
        for f in range(nf):
            c = uv[start[f]:start[f] + total[f]] * size; iid = base + int(isl[f]) + 1
            for k in range(1, len(c) - 1):
                a_, b_, c_ = c[0], c[k], c[k + 1]
                den = (b_[0] - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (b_[1] - a_[1])
                if abs(den) < 1e-9:
                    zero += 1; continue
                x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))), 0); x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))), size - 1)
                y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))), 0); y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))), size - 1)
                if x1 < x0 or y1 < y0:
                    continue
                xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
                w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
                ins = (w1 > 1e-4) & (w2 > 1e-4) & (w1 + w2 < 1 - 1e-4)
                if not ins.any():
                    continue
                view = ids[y0:y1 + 1, x0:x1 + 1]; old = view[ins]
                twice += int(((old != 0) & (old != iid)).sum()); covered += int((old == 0).sum())
                old[:] = iid; view[ins] = old
        base += len(uniq)
    close = 0
    if gap > 0 and covered:
        for dy, dx in ((0, gap), (gap, 0), (gap, gap), (gap, -gap)):
            a = ids[max(dy, 0):, max(dx, 0):size + min(dx, 0)] if dx >= 0 else ids[dy:, :size + dx]
            b = ids[:size - dy, :size - dx] if dx >= 0 else ids[:size - dy, -dx:]
            close += int(((a != 0) & (b != 0) & (a != b)).sum())
    inside = bool(lo.min() >= -1e-6 and hi.max() <= 1 + 1e-6) if faces else False
    folded = 0; squashed = 0; bad_area = 0.0; area = 0.0
    for h in hairs:
        if name not in h.data.uv_layers:
            continue
        tr = uv_trouble(h, name, size)
        folded += tr["folded"]; squashed += tr["squashed"]; bad_area += tr["bad_area"]; area += tr["area"]
    trouble = bad_area / area if area > 0 else 0.0
    return dict(faces=int(faces), islands=int(n_isl), inside_0_1=inside, uv_min=[round(float(x), 4) for x in lo], uv_max=[round(float(x), 4) for x in hi],
                overlap_pixels=int(twice), too_close_pixels=int(close), filled=round(covered / float(size * size), 3),
                zero_triangles=int(zero), size=int(size), gap=int(gap),
                folded_faces=int(folded), squashed_faces=int(squashed), trouble_share=round(trouble, 4),
                ok=bool(inside and twice == 0 and close == 0 and trouble <= max_trouble))


def export_for_texture(hairs, path, name="LW_StrandUV"):
    """One file to take to a texturing service: the hairs as they look now (bent), joined into one mesh with ONE
    UV map (the strand UV) and one plain material; no rig, no outline shell, no other UV maps. The scene's hairs
    are not changed: the mesh is built apart, exported and removed again. FBX or GLB by the file's ending."""
    import bpy
    import os
    from . import strands as S
    R = S.R
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    V = []; LV = []; LS = []; UV = []; off_v = 0; off_l = 0
    for h in hairs:
        me = h.data
        if name not in me.uv_layers:
            raise RuntimeError("%s has no strand UV yet" % h.name)
        keep = {m.name: m.show_viewport for m in h.modifiers}
        for m in h.modifiers:
            m.show_viewport = (m.name == R.GROUP)
        try:
            dg = bpy.context.evaluated_depsgraph_get(); dg.update(); ev = h.evaluated_get(dg).data
            if len(ev.vertices) != len(me.vertices):
                raise RuntimeError("%s: the bent mesh has another number of vertices" % h.name)
            co = np.empty(len(ev.vertices) * 3, dtype=np.float32); ev.vertices.foreach_get("co", co)
        finally:
            for m in h.modifiers:
                m.show_viewport = keep[m.name]
        co = co.reshape(-1, 3).astype(np.float64); M = np.array(h.matrix_world)
        V.append(co @ M[:3, :3].T + M[:3, 3])
        lvi = np.empty(len(me.loops), dtype=np.int32); me.loops.foreach_get("vertex_index", lvi)
        uv, start, _total = _uv_arrays(me, name)
        LV.append(lvi + off_v); LS.append(start + off_l); UV.append(uv)
        off_v += len(co); off_l += len(lvi)
    V = np.concatenate(V); LV = np.concatenate(LV); LS = np.concatenate(LS); UV = np.concatenate(UV)
    me2 = bpy.data.meshes.new("LidaHair_ForTexture")
    me2.vertices.add(len(V)); me2.loops.add(len(LV)); me2.polygons.add(len(LS))
    me2.vertices.foreach_set("co", V.astype(np.float32).reshape(-1))
    me2.loops.foreach_set("vertex_index", LV.astype(np.int32)); me2.polygons.foreach_set("loop_start", LS.astype(np.int32))
    me2.update(calc_edges=True); me2.validate()
    lay = me2.uv_layers.new(name="UVMap", do_init=False); lay.data.foreach_set("uv", UV.astype(np.float32).reshape(-1))
    me2.polygons.foreach_set("use_smooth", np.ones(len(me2.polygons), dtype=bool))
    mat = bpy.data.materials.new("LidaHair_ForTexture"); me2.materials.append(mat)
    ob = bpy.data.objects.new("LidaHair_ForTexture", me2); bpy.context.scene.collection.objects.link(ob)
    view = bpy.context.view_layer; prev_active = view.objects.active; prev_sel = [o for o in view.objects if o.select_get()]
    info = dict(vertices=len(V), faces=len(LS), same_faces=bool(len(me2.polygons) == len(LS)))
    try:
        for o in view.objects:
            o.select_set(o == ob)
        view.objects.active = ob
        if path.lower().endswith(".glb"):
            bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_format="GLB", export_animations=False)
        else:
            bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"}, bake_anim=False,
                                     add_leaf_bones=False, mesh_smooth_type="FACE", path_mode="AUTO")
    finally:
        for o in view.objects:
            o.select_set(o in prev_sel)
        view.objects.active = prev_active
        bpy.data.objects.remove(ob, do_unlink=True); bpy.data.meshes.remove(me2); bpy.data.materials.remove(mat)
    info["bytes"] = os.path.getsize(path); info["path"] = path
    return info


# ---- the hair drawn with the strand UV: textures carried over, and back ------------------------------------------

SWAP_KEY = "lw_uv_before"
SWAP_TAG = "_LW"


def _transfer_map(hairs, width, height, dst="LW_StrandUV"):
    """For every texel of the strand UV: where the same spot of the hair lies in the UV the hair is drawn with now.
    Two pictures (u and v), NaN where no face is; then grown a few texels past the islands' edges."""
    _tell(_tr("写す位置を計算中"), 0.1)
    U = np.full((height, width), np.nan, dtype=np.float32); V = U.copy()
    scale = np.array([width, height], dtype=np.float64)
    for h in hairs:
        me = h.data; src = next((l.name for l in me.uv_layers if l.active_render), me.uv_layers[0].name)
        new, start, total = _uv_arrays(me, dst); old, _s, _t = _uv_arrays(me, src)
        me.calc_loop_triangles()                                    # the same triangles the renderer draws
        tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
        C = new[tl] * scale; O = old[tl]
        den_all = (C[:, 1, 0] - C[:, 0, 0]) * (C[:, 2, 1] - C[:, 0, 1]) - (C[:, 2, 0] - C[:, 0, 0]) * (C[:, 1, 1] - C[:, 0, 1])
        for ti in np.argsort(np.abs(den_all)):                      # small ones first; a texel keeps its first owner
            den = den_all[ti]
            if abs(den) < 1e-9:
                continue
            a_, b_, c_ = C[ti]; o = O[ti]
            x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))) - 1, 0); x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))) + 1, width - 1)
            y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))) - 1, 0); y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))) + 1, height - 1)
            if x1 < x0 or y1 < y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
            w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
            w0 = 1.0 - w1 - w2
            view_u = U[y0:y1 + 1, x0:x1 + 1]; view_v = V[y0:y1 + 1, x0:x1 + 1]
            ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) & np.isnan(view_u)
            if not ins.any():
                continue
            view_u[ins] = (w0 * o[0, 0] + w1 * o[1, 0] + w2 * o[2, 0])[ins]; view_v[ins] = (w0 * o[0, 1] + w1 * o[1, 1] + w2 * o[2, 1])[ins]
        for f in range(len(start)):                                 # faces smaller than a texel: the texel under them
            cx, cy = (new[start[f]:start[f] + total[f]] * scale).mean(axis=0)
            ix, iy = int(cx), int(cy)
            if 0 <= ix < width and 0 <= iy < height and np.isnan(U[iy, ix]):
                U[iy, ix], V[iy, ix] = old[start[f]:start[f] + total[f]].mean(axis=0)
    inside = ~np.isnan(U)
    for _grow in range(8):                                          # past the edges, so that no seam shows
        miss = np.isnan(U)
        if not miss.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            su = np.roll(U, (dy, dx), axis=(0, 1)); sv = np.roll(V, (dy, dx), axis=(0, 1))
            take = np.isnan(U) & miss & ~np.isnan(su)
            U[take] = su[take]; V[take] = sv[take]
    return U, V, inside


def _resample(src, U, V):
    """src: (h, w, 4) picture; returns the picture seen through the map (bilinear, repeating)."""
    h, w = src.shape[:2]; ok = ~np.isnan(U)
    x = np.where(ok, U, 0.0).astype(np.float64) * w - 0.5; y = np.where(ok, V, 0.0).astype(np.float64) * h - 0.5
    x0 = np.floor(x).astype(np.int64); y0 = np.floor(y).astype(np.int64); fx = (x - x0)[..., None]; fy = (y - y0)[..., None]
    x1 = (x0 + 1) % w; y1 = (y0 + 1) % h; x0 %= w; y0 %= h
    out = (src[y0, x0] * (1 - fx) + src[y0, x1] * fx) * (1 - fy) + (src[y1, x0] * (1 - fx) + src[y1, x1] * fx) * fy
    if ok.any():
        fill = out[ok].mean(axis=0); fill[3] = 1.0; out[~ok] = fill
    return out.astype(np.float32)


def _reads_uv(node, depth=0):
    """Does this image node take its place from the UV map (nothing plugged in, or a UV output, also through a
    Mapping node)?"""
    sock = node.inputs.get("Vector")
    if sock is None or not sock.is_linked:
        return True
    src = sock.links[0].from_node; out = sock.links[0].from_socket
    if src.type == "UVMAP":
        return True
    if src.type == "TEX_COORD":
        return out.name == "UV"
    if src.type == "MAPPING" and depth < 4:
        return _reads_uv(src, depth + 1)
    return False


def swap_uv(hairs, name="LW_StrandUV", max_size=4096):
    """The hairs are drawn with the strand UV from now on, and look as before: every picture their materials use
    is carried over into the strand UV (a new picture, kept inside the file), in copies of the materials that only
    these hairs use. The old UV map, the old materials and the old pictures stay; revert_uv puts them back."""
    import bpy
    import json
    hairs = [h for h in hairs if name in h.data.uv_layers and not h.get(SWAP_KEY)]
    if not hairs:
        return dict(hairs=0, images=0, skipped=[])
    maps = {}; made = {}; skipped = []; mats = {}; befores = {}
    for h in hairs:
        me = h.data
        before = dict(render=next((l.name for l in me.uv_layers if l.active_render), None),
                      active=me.uv_layers.active.name if me.uv_layers.active else None, materials=[m.name if m else "" for m in me.materials])
        for i, m in enumerate(me.materials):
            if m is None or not m.use_nodes:
                continue
            if m.name not in mats:
                c = m.copy(); c.name = m.name + SWAP_TAG; mats[m.name] = c
                for nd in c.node_tree.nodes:
                    if nd.type == "UVMAP" and nd.uv_map in ("", before["render"]):
                        nd.uv_map = name
                    if nd.type != "TEX_IMAGE" or nd.image is None or not _reads_uv(nd):
                        continue                                  # matcaps and the like do not go by the UV
                    img = nd.image
                    if img.name not in made:
                        w, hh = img.size[0], img.size[1]
                        if w == 0 or hh == 0 or len(img.pixels) != w * hh * 4:
                            skipped.append(img.name); made[img.name] = None
                        else:
                            ow, oh = min(w, max_size), min(hh, max_size)
                            if (ow, oh) not in maps:
                                maps[(ow, oh)] = _transfer_map(hairs, ow, oh, name)
                            _tell(_tr("画像を写し中：%s") % img.name[:14], 0.2 + 0.1 * min(len(made), 6))
                            px = np.empty(w * hh * 4, dtype=np.float32); img.pixels.foreach_get(px)
                            out = _resample(px.reshape(hh, w, 4), maps[(ow, oh)][0], maps[(ow, oh)][1])
                            ni = bpy.data.images.new(img.name + SWAP_TAG, ow, oh, alpha=True, float_buffer=img.is_float)
                            ni.colorspace_settings.name = img.colorspace_settings.name; ni.alpha_mode = img.alpha_mode
                            ni.pixels.foreach_set(out.reshape(-1)); ni.update(); ni.pack(); made[img.name] = ni
                    if made[img.name] is not None:
                        nd.image = made[img.name]
            me.materials[i] = mats[m.name]
        h[SWAP_KEY] = json.dumps(before)
        befores[h.name] = before["render"]
        me.uv_layers[name].active_render = True; me.uv_layers.active = me.uv_layers[name]; me.update()
    _tell(_tr("色の答え合わせ中"), 0.9)
    return dict(hairs=len(hairs), images=len([x for x in made.values() if x is not None]), skipped=sorted(set(skipped)),
                materials=len(mats), **_swap_answer(hairs, made, befores, name))


def _swap_answer(hairs, made, befores, name, limit=0.15):
    """The answer check after carrying pictures over: for every triangle, the old picture at its middle (old UV)
    against the new picture at its middle (strand UV). Triangles where the old picture itself changes a lot from
    corner to corner are left out (their middle is no fair sample). Returns how many triangles differ."""
    import bpy
    pairs = [(bpy.data.images.get(k), v) for k, v in made.items() if v is not None]
    pairs = [(a_, b_) for a_, b_ in pairs if a_ is not None]
    if not pairs:
        return dict(triangles=0, differ=0)
    src_img, dst_img = max(pairs, key=lambda q: q[0].size[0] * q[0].size[1])

    def load(im):
        w, hh = im.size; px = np.empty(w * hh * 4, dtype=np.float32); im.pixels.foreach_get(px); return px.reshape(hh, w, 4)
    src = load(src_img); dst = load(dst_img)

    def samp(im, uv):
        hh, w = im.shape[:2]
        return im[np.clip((uv[:, 1] % 1.0 * hh).astype(int), 0, hh - 1), np.clip((uv[:, 0] % 1.0 * w).astype(int), 0, w - 1), :3]
    n = 0; bad = 0
    for h in hairs:
        me = h.data; new, _s, _t = _uv_arrays(me, name); old, _s, _t = _uv_arrays(me, befores[h.name])
        me.calc_loop_triangles()
        tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32); me.loop_triangles.foreach_get("loops", tl); tl = tl.reshape(-1, 3)
        co = samp(src, old[tl].mean(axis=1)); cn = samp(dst, new[tl].mean(axis=1))
        even = (np.abs(samp(src, old[tl][:, 0]) - samp(src, old[tl][:, 1])).max(axis=1) <= limit) &                (np.abs(samp(src, old[tl][:, 1]) - samp(src, old[tl][:, 2])).max(axis=1) <= limit)
        n += int(even.sum()); bad += int((even & (np.abs(co - cn).max(axis=1) > limit)).sum())
    return dict(triangles=n, differ=bad)


def revert_uv(hairs):
    """Back to how the hairs were drawn before swap_uv; the copies made for the strand UV are removed if nothing uses them."""
    import bpy
    import json
    done = 0
    for h in hairs:
        raw = h.get(SWAP_KEY)
        if not raw:
            continue
        before = json.loads(raw); me = h.data
        for i, nm in enumerate(before["materials"]):
            if i < len(me.materials) and nm and nm in bpy.data.materials:
                me.materials[i] = bpy.data.materials[nm]
        if before["render"] in me.uv_layers:
            me.uv_layers[before["render"]].active_render = True
        if before["active"] in me.uv_layers:
            me.uv_layers.active = me.uv_layers[before["active"]]
        del h[SWAP_KEY]; me.update(); done += 1
    for m in [m for m in bpy.data.materials if m.name.endswith(SWAP_TAG) and m.users == 0]:
        bpy.data.materials.remove(m)
    for im in [im for im in bpy.data.images if im.name.endswith(SWAP_TAG) and im.users == 0]:
        bpy.data.images.remove(im)
    return done


def drop_old_uv(hairs, name="LW_StrandUV"):
    """Only for hairs already drawn with the strand UV: every other UV map is removed. There is no way back after
    this (the old pictures no longer fit); the note for revert_uv is removed too."""
    gone = []
    for h in hairs:
        me = h.data
        if not h.get(SWAP_KEY) or name not in me.uv_layers:
            continue
        for nm in [l.name for l in me.uv_layers if l.name != name]:
            me.uv_layers.remove(me.uv_layers[nm]); gone.append("%s/%s" % (h.name, nm))
        me.uv_layers[name].active_render = True; me.uv_layers.active = me.uv_layers[name]
        del h[SWAP_KEY]; h["lw_uv_only"] = 1; me.update()
    return gone

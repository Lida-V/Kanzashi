# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Strands of a generated hair mesh, found by surface connectivity.

Idea: D = distance along the surface from the crown. Sweep the vertices from the farthest to the nearest.
A vertex with no swept neighbour starts a tube (a tip). A vertex whose swept neighbours belong to one tube
joins it. A vertex whose swept neighbours belong to two or more tubes is where they merge: the tubes end
there and one trunk goes on. So every vertex belongs to exactly one piece, a piece is always connected, and
pieces meet only where three or more come together. No slicing is involved.

detect_and_bind() does the whole detection for one hair: strands, one wire and one colour per strand, and the
binding of the vertices to their wires."""

import numpy as np


def cap_by_flow(nb, f, zone, owner):
    """The melted part: every vertex climbs the smooth value (0 at the crown, 1 where the strands leave) from
    neighbour to neighbour until it reaches a strand, and takes that strand's label. So the cap is divided along
    the flow, not by straight distance. Returns (owner, vertices decided)."""
    owner = owner.copy()
    done = 0
    for v in np.nonzero(zone & (owner < 0))[0]:
        cur = int(v)
        seen = 0
        while owner[cur] < 0 and seen < 400:
            best = cur
            bf = f[cur] if np.isfinite(f[cur]) else -1.0
            for u, _l in nb[cur]:
                fu = f[u] if np.isfinite(f[u]) else -1.0
                if fu > bf:
                    best, bf = int(u), fu
            if best == cur:
                break
            cur = best
            seen += 1
        if owner[cur] >= 0:
            owner[v] = -2 - owner[cur]
            done += 1  # mark first, so later climbs do not stop on it early
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
            p[a] = p[p[a]]
            a = p[a]
        return a

    def union(self, a, b):
        a = self.find(a)
        b = self.find(b)
        if a != b:
            self.p[b] = a


def level_graph(P, T, D, h=0.01):
    """Returns (rings, patches, patch per vertex).
    rings[i]: level (index, D = level*h), length, centre, points (unordered crossing points), below, above (patch ids).
    patches[i]: band, inner (rings on the crown side), outer (rings on the tip side), verts."""
    n = len(P)
    band = np.floor(np.where(np.isfinite(D), D, 0.0) / h).astype(np.int64)
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    sw = band[e[:, 0]] > band[e[:, 1]]
    e[sw] = e[sw][:, ::-1]  # a = lower band
    eid = {(int(min(a, b)), int(max(a, b))): i for i, (a, b) in enumerate(e)}
    cnt = band[e[:, 1]] - band[e[:, 0]]
    off = np.concatenate([[0], np.cumsum(cnt)])
    nc = int(off[-1])
    first = band[e[:, 0]] + 1  # first level an edge crosses
    cpos = np.zeros((nc, 3))
    clev = np.zeros(nc, dtype=np.int64)
    for i in np.nonzero(cnt > 0)[0]:
        a, b = e[i]
        da, db = D[a], D[b]
        for q in range(cnt[i]):
            j = first[i] + q
            s = (j * h - da) / max(db - da, 1e-12)
            cpos[off[i] + q] = P[a] + (P[b] - P[a]) * min(max(s, 0.0), 1.0)
            clev[off[i] + q] = j

    def node(i, j):
        return int(off[i] + (j - first[i]))

    ul = _UF(nc)
    seg = []
    for tri in T:
        v = sorted((int(x) for x in tri), key=lambda x: band[x])
        b0, b1, b2 = band[v[0]], band[v[1]], band[v[2]]
        if b0 == b2:
            continue
        e01 = eid[(min(v[0], v[1]), max(v[0], v[1]))]
        e02 = eid[(min(v[0], v[2]), max(v[0], v[2]))]
        e12 = eid[(min(v[1], v[2]), max(v[1], v[2]))]
        for j in range(b0 + 1, b2 + 1):
            x = node(e02, j)
            y = node(e01, j) if j <= b1 else node(e12, j)
            ul.union(x, y)
            seg.append((x, y))
    root = np.array([ul.find(i) for i in range(nc)], dtype=np.int64)
    ids, ring_of = np.unique(root, return_inverse=True)
    nr = len(ids)
    length = np.zeros(nr)
    csum = np.zeros((nr, 3))
    for x, y in seg:
        l = float(np.linalg.norm(cpos[x] - cpos[y]))
        r = ring_of[x]
        length[r] += l
        csum[r] += (cpos[x] + cpos[y]) / 2 * l
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
            ub.union(int(a), int(b))
            continue
        ub.union(int(a), IN(ring_of[node(i, first[i])]))
        ub.union(int(b), OUT(ring_of[node(i, first[i] + cnt[i] - 1)]))
        for q in range(cnt[i] - 1):
            ub.union(OUT(ring_of[off[i] + q]), IN(ring_of[off[i] + q + 1]))
    roots = {}
    patches = []

    def patch(x, bnd):
        r = ub.find(x)
        if r not in roots:
            roots[r] = len(patches)
            patches.append(dict(band=int(bnd), inner=[], outer=[], verts=[]))
        return roots[r]

    pv = np.full(n, -1, dtype=np.int64)
    for v in range(n):
        if np.isfinite(D[v]):
            pv[v] = patch(v, band[v])
            patches[pv[v]]["verts"].append(v)
    rings = []
    for r in range(nr):
        lev = int(clev[pts[r][0]])
        below = patch(IN(r), lev - 1)
        above = patch(OUT(r), lev)
        patches[below]["outer"].append(r)
        patches[above]["inner"].append(r)
        rings.append(
            dict(level=lev, length=float(length[r]), centre=centre[r], points=cpos[pts[r]], below=below, above=above)
        )
    return rings, patches, pv


def ring_tree(P, rings, patches, pv, h=0.01, cap_len=0.40, min_leaf=0.03, sheet_share=0.7, sheet_flat=0.35):
    """Tubes from the level rings, going outward from the crown.
    A segment is a run of rings with nothing joining or leaving. A ring longer than cap_len is not a tube but a
    sheet of tubes melted together (wide). A leaf shorter than min_leaf is a bump and goes back to its parent.
    Returns (segment per vertex, segs). segs[i]: rings, verts, parent, children, wide, reach (farthest level
    in its subtree), fused (it ended by running into another tube)."""
    n = len(pv)
    segs = []
    ring_seg = np.full(len(rings), -1, dtype=np.int64)
    seg_of_v = np.full(n, -1, dtype=np.int64)

    def new_seg(parent, wide):
        segs.append(dict(rings=[], verts=[], parent=parent, children=[], wide=bool(wide), fused=False))
        if parent >= 0:
            segs[parent]["children"].append(len(segs) - 1)
        return len(segs) - 1

    def wide(r):
        return rings[r]["length"] > cap_len

    for pi in sorted(range(len(patches)), key=lambda i: patches[i]["band"]):
        pt = patches[pi]
        inner = pt["inner"]
        outer = pt["outer"]
        verts = pt["verts"]
        if not inner:
            first = -1
            for r in outer:
                s = new_seg(-1, wide(r))
                ring_seg[r] = s
                segs[s]["rings"].append(r)
                first = s if first < 0 else first
            if first < 0:
                first = new_seg(-1, False)
            segs[first]["verts"] += verts
            seg_of_v[verts] = first
            continue
        if len(inner) == 1:
            s = int(ring_seg[inner[0]])
            segs[s]["verts"] += verts
            seg_of_v[verts] = s
            if len(outer) == 1 and wide(outer[0]) == segs[s]["wide"]:
                ring_seg[outer[0]] = s
                segs[s]["rings"].append(outer[0])
            else:
                for r in outer:
                    c = new_seg(s, wide(r))
                    ring_seg[r] = c
                    segs[c]["rings"].append(r)
            continue
        # two or more tubes touch here. Each ring beyond goes on as the tube whose ring it is nearest to.
        ins = [int(ring_seg[r]) for r in inner]
        ic = np.array([rings[r]["centre"] for r in inner])
        if verts:
            d = np.linalg.norm(P[verts][:, None, :] - ic[None, :, :], axis=2)
            near = np.argmin(d, axis=1)
            for v, q in zip(verts, near):
                segs[ins[q]]["verts"].append(v)
                seg_of_v[v] = ins[q]
        pairs = sorted(
            ((float(np.linalg.norm(rings[r]["centre"] - ic[q])), r, q) for r in outer for q in range(len(inner)))
        )
        used_in = set()
        used_out = set()
        for _d, r, q in pairs:
            if r in used_out or q in used_in:
                continue
            used_out.add(r)
            used_in.add(q)
            s = ins[q]
            if wide(r) == segs[s]["wide"]:
                ring_seg[r] = s
                segs[s]["rings"].append(r)
            else:
                c = new_seg(s, wide(r))
                ring_seg[r] = c
                segs[c]["rings"].append(r)
        for r in outer:
            if r not in used_out:
                q = int(np.argmin(np.linalg.norm(ic - rings[r]["centre"], axis=1)))
                c = new_seg(ins[q], wide(r))
                ring_seg[r] = c
                segs[c]["rings"].append(r)
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
                par["verts"] += s["verts"]
                seg_of_v[s["verts"]] = s["parent"]
                par["children"].remove(i)
                s["dead"] = True
                s["verts"] = []
                hit = True
                absorbed += 1
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
            s["wide"] = True
            s["sheet"] = True
            sheets += 1
    for i in range(len(segs) - 1, -1, -1):
        s = segs[i]
        if s.get("dead"):
            continue
        s["has_wide"] = s["wide"] or any(segs[c]["has_wide"] for c in s["children"])
    return (
        seg_of_v,
        segs,
        dict(
            sheets=sheets,
            segments=int(sum(1 for s in segs if not s.get("dead"))),
            bumps_absorbed=absorbed,
            fused_ends=int(sum(1 for s in segs if s["fused"])),
        ),
    )


def wires_from_rings(rings, segs, main_root):
    """One wire per tube. The cap is every segment that is wide or has something wide beyond it. A tube that
    leaves the cap starts a base wire. At a branch the tube keeps the wire of the child that reaches farthest.
    Returns (wire per segment, -1 in the cap; wires). wires[i]: segs, kind (base / branch / loose), parent."""
    wire_of = np.full(len(segs), -1, dtype=np.int64)
    wires = []

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
        w = len(wires)
        wires.append(dict(segs=[], kind=kind, parent=pw))
        cur = i
        while True:
            wire_of[cur] = w
            wires[w]["segs"].append(cur)
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
    seg = np.linalg.norm(np.diff(c, axis=0), axis=1)
    c = c[np.concatenate([[True], seg > 1e-6])]
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
    n = len(nb)
    zv = np.nonzero(zone & (owner < 0))[0]
    slope = None
    if f is not None:
        fz = np.where(np.isfinite(f), f, 1.0)
        sl = [abs(fz[u] - fz[v]) / max(l, 1e-6) for v in zv for u, l in nb[v]]
        slope = float(np.percentile(sl, 90)) if sl else None
    index = np.full(n, -1, dtype=np.int64)
    index[zv] = np.arange(len(zv))
    labs = sorted({int(owner[u]) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    col = {k: i for i, k in enumerate(labs)}
    m = len(zv)
    A = np.zeros((m, m))
    B = np.zeros((m, len(labs)))
    for i, v in enumerate(zv):
        for u, l in nb[v]:
            w = 1.0 / max(l, 1e-6)
            if slope:
                w *= across + min(abs(fz[u] - fz[v]) / max(l, 1e-6) / slope, 1.0) ** power
            if index[u] >= 0:
                A[i, i] += w
                A[i, index[u]] -= w
            elif owner[u] >= 0:
                A[i, i] += w
                B[i, col[int(owner[u])]] += w
        A[i, i] += 1e-9
    G = np.linalg.solve(A, B) if m and labs else np.zeros((m, len(labs)))
    return labs, G, index


def cap_transport(nb, D, zone, owner):
    """The melted part (cap, or a sheet of ribbons grown together) divided by carrying every strand's label
    back toward the crown. Going from the far end inward, a vertex takes the shares of its neighbours that are
    farther from the crown, so a strand keeps a strip that runs along the flow all the way up, and strips of
    strands that leave the sheet one below the other lie side by side instead of in blocks.
    Returns (labels, G, index) like cap_partition."""
    n = len(nb)
    zv = np.nonzero(zone & (owner < 0))[0]
    index = np.full(n, -1, dtype=np.int64)
    index[zv] = np.arange(len(zv))
    labs = sorted({int(owner[u]) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    col = {k: i for i, k in enumerate(labs)}
    G = np.zeros((len(zv), len(labs)))
    done = np.zeros(len(zv), dtype=bool)
    for v in zv[np.argsort(-D[zv])]:
        acc = np.zeros(len(labs))
        wsum = 0.0
        for u, l in nb[v]:
            if D[u] <= D[v]:
                continue
            w = (D[u] - D[v]) / max(l * l, 1e-12)
            if owner[u] >= 0:
                acc[col[int(owner[u])]] += w
                wsum += w
            elif index[u] >= 0 and done[index[u]]:
                acc += w * G[index[u]]
                wsum += w
        if wsum > 0:
            G[index[v]] = acc / wsum
            done[index[v]] = True
    for _ in range(50):  # edges of the sheet with nothing farther out: from any side
        left = np.nonzero(~done)[0]
        if not len(left):
            break
        hit = False
        for i in left:
            v = zv[i]
            acc = np.zeros(len(labs))
            wsum = 0.0
            for u, l in nb[v]:
                w = 1.0 / max(l, 1e-6)
                if owner[u] >= 0:
                    acc[col[int(owner[u])]] += w
                    wsum += w
                elif index[u] >= 0 and done[index[u]]:
                    acc += w * G[index[u]]
                    wsum += w
            if wsum > 0:
                G[i] = acc / wsum
                done[i] = True
                hit = True
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

    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    lay = bm.verts.layers.int.get("lw_cut") or bm.verts.layers.int.new("lw_cut")
    todo = []
    for e in bm.edges:
        a = int(inv[e.verts[0].index])
        b = int(inv[e.verts[1].index])
        la, lb = int(owner[a]), int(owner[b])
        if la == lb or la < 0 or lb < 0 or (index[a] < 0 and index[b] < 0):
            continue
        da = share(a, la) - share(a, lb)
        db = share(b, la) - share(b, lb)
        s = da / (da - db) if (da - db) > 1e-9 else 0.5
        todo.append((e, min(max(s, margin), 1.0 - margin)))
    new = set()
    for e, s in todo:
        _ne, nv = bmesh.utils.edge_split(e, e.verts[0], s)
        nv[lay] = 1
        new.add(nv)
    split = 0
    for f in list(bm.faces):
        nv = [v for v in f.verts if v in new]
        if len(nv) >= 2:
            try:
                bmesh.utils.face_split(f, nv[0], nv[1])
                split += 1
            except Exception:
                pass
    bm.verts.ensure_lookup_table()
    old_n = len(inv)
    ids = np.full(len(bm.verts), -9, dtype=np.int64)
    for v in bm.verts:
        if v.index < old_n and not v[lay]:
            ids[v.index] = owner[inv[v.index]]
    bm.to_mesh(me)
    bm.free()
    me.update()
    return len(todo), split, ids


def face_colours(me, ids, seed=7, name="lw_strand_col"):
    """Per face: the label most of its labelled corners have (border vertices, -9, do not vote). Writes the face
    attribute lw_strand and a colour per label."""
    lv = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lv)
    strand = np.full(len(me.polygons), -1, dtype=np.int32)
    for p in me.polygons:
        k = ids[lv[p.loop_start : p.loop_start + p.loop_total]]
        k = k[k >= 0]
        if len(k):
            vals, cnt = np.unique(k, return_counts=True)
            strand[p.index] = vals[int(np.argmax(cnt))]
    at = me.attributes.get("lw_strand") or me.attributes.new("lw_strand", "INT", "FACE")
    at.data.foreach_set("value", strand)
    total = np.array([p.loop_total for p in me.polygons])
    pal = PAL
    ca = me.color_attributes.get(name) or me.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
    fc = np.where((strand >= 0)[:, None], pal[np.maximum(strand, 0)], 0.35)
    c = np.ones((len(me.loops), 4), dtype=np.float32)
    c[:, :3] = np.repeat(fc, total, axis=0)
    ca.data.foreach_set("color", c.reshape(-1))
    me.color_attributes.active_color = ca
    me.update()
    return strand


def cap_wedges(P, nb, D, zone, owner, crown, start=0.03, tie=0.05, smooth=10, outward=1.0, behind=0.02):
    """The cap divided like hair parts: every tube that leaves the cap gets a wedge that runs to the crown.
    Each cap vertex gets a direction round the crown (an angle). Near the crown the angle is read off directly;
    farther out a vertex takes the angle of its neighbours nearer the crown, so the angle stays the same along
    the shortest lines from the crown outward. A tube covers the angles of its first ring; a vertex goes to the
    tube whose angles are nearest its own. Returns (labels, G, index, angle) like cap_partition (G = share)."""
    n = len(P)
    free = zone & (owner < 0)
    zv = np.nonzero(free)[0]
    index = np.full(n, -1, dtype=np.int64)
    index[zv] = np.arange(len(zv))
    ringv = sorted({int(u) for v in zv for u, _l in nb[v] if owner[u] >= 0})
    labs = sorted({int(owner[u]) for u in ringv})
    c = P[crown]
    nearv = zv[D[zv] < 0.15] if (D[zv] < 0.15).sum() >= 8 else zv
    axis = (c - P[nearv]).sum(axis=0)
    axis /= max(np.linalg.norm(axis), 1e-9)
    e1 = np.cross(axis, (1.0, 0.0, 0.0))
    if np.linalg.norm(e1) < 0.2:
        e1 = np.cross(axis, (0.0, 1.0, 0.0))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    z = np.zeros(n, dtype=complex)
    known = np.zeros(n, dtype=bool)
    todo = np.array(sorted(set(zv.tolist()) | set(ringv), key=lambda v: D[v]), dtype=np.int64)
    seed = [v for v in todo if D[v] < start and v != crown]
    if len(seed) < 6:
        seed = [v for v in todo[:12] if v != crown]
    for v in seed:
        q = P[v] - c
        zz = complex(q @ e1, q @ e2)
        if abs(zz) > 1e-9:
            z[v] = zz / abs(zz)
            known[v] = True
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
            q = P[v] - c
            acc = complex(q @ e1, q @ e2) or 1 + 0j
        z[v] = acc / abs(acc)
        known[v] = True
    fixed = np.zeros(n, dtype=bool)
    fixed[seed] = True
    for _ in range(smooth):  # even out the angle over the surface
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
    cen = {}
    half = {}
    rootd = {}
    for k in labs:
        rv = [u for u in ringv if owner[u] == k]
        zz = z[rv]
        m = zz.mean()
        m = m / abs(m) if abs(m) > 1e-9 else zz[0]
        cen[k] = m
        half[k] = float(np.max(np.abs(np.angle(zz / m))))
        rootd[k] = float(np.max(D[rv]))
    G = np.zeros((len(zv), len(labs)))
    for j, k in enumerate(labs):
        dev = np.abs(np.angle(z[zv] / cen[k]))
        gap = rootd[k] - D[zv]
        G[:, j] = (
            -np.maximum(dev - half[k], 0.0)
            - tie * dev
            - outward * np.maximum(gap, 0.0)
            - np.where(gap < -behind, 10.0, 0.0)
        )
    return labs, G, index, ang


# ---------------------------------------------------------------------------------------------------------
# From detection to something you can use: wires (curves) the hair follows, a colour per wire on the faces,
# and repainting. Paint faces with the colour of another wire, press apply, and those faces (their vertices,
# their place in the strand UV) move over to that wire.


PAL = np.random.default_rng(7).uniform(0.25, 1.0, size=(1024, 3))  # linear colour per wire id


def to_srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def detect_and_bind(
    hair, wires_obj, root, cap_len=0.40, h=0.01, min_wire=0.05, cut=True, log=None, cap_rule="transport", root_fix=0.05
):
    """Finds the strands of `hair`, makes one curve per strand in `wires_obj`, cuts the cap along the borders,
    colours the faces and ties every vertex to its wire. Changes the mesh of `hair` (work on a copy)."""
    from . import strands as S

    R = S.R
    me = hair.data
    root = np.asarray(root, float)
    P, T, inv, world = R.gather(hair)
    nb = R.edge_graph(P, T)
    D, comp = S.distance_from_root(P, nb, root)
    crown = int(np.argmin(np.linalg.norm(P - root, axis=1)))
    rings, patches, pv = level_graph(P, T, D, h)
    seg_of_v, segs, st = ring_tree(P, rings, patches, pv, h, cap_len)
    main_root = {
        i
        for i, s in enumerate(segs)
        if s["parent"] < 0 and not s.get("dead") and comp[crown] in set(comp[s["verts"]].tolist())
    }
    wire_of, wires = wires_from_rings(rings, segs, main_root)
    owner = np.where(seg_of_v >= 0, wire_of[np.maximum(seg_of_v, 0)], -1)
    short = [i for i, w in enumerate(wires) if len(w["rings"]) * h < min_wire]
    owner0 = owner.copy()
    for i in short:
        owner[owner == i] = -3
    lv = np.nonzero(owner == -3)[0]
    if len(lv):
        src = np.nonzero(owner >= 0)[0]
        _d, near = R.spread(nb, src, labels=owner[src])
        owner[lv] = near[lv]
        alone = lv[owner[lv] < 0]  # a small piece on its own (a braid bead): it keeps its short wire
        owner[alone] = owner0[alone]
        short = [i for i in short if not (owner == i).any()]
    if (owner < 0).any():
        f, _info, zone, _ring = S.melted_field(P, T, nb, owner, D, crown)
    else:  # every vertex already belongs to a strand: there is no cap
        f = np.full(len(P), np.nan)
        zone = np.zeros(len(P), dtype=bool)
    if cap_rule == "wedges":
        labs, G, gidx, _ang = cap_wedges(P, nb, D, zone, owner, crown)
    else:
        labs, G, gidx = cap_transport(nb, D, owner < 0, owner)
    melted = owner < 0
    zv = np.nonzero(gidx >= 0)[0]
    if len(zv) and labs:
        Gz = G[gidx[zv]].copy()
        la = np.array(labs)
        pick = np.argmax(Gz, axis=1)
        if cap_rule == "wedges":
            for _ in range(6):
                pick = np.argmax(Gz, axis=1)
                cnt = np.bincount(pick, minlength=len(labs))
                small = np.nonzero((cnt > 0) & (cnt < 10))[0]
                if not len(small):
                    break
                Gz[:, small] = -1e9
        ok = Gz[np.arange(len(zv)), pick] > (1e-9 if cap_rule != "wedges" else -1e8)
        owner[zv[ok]] = la[pick[ok]]
        tid, _m = S.tidy_labels(nb, owner, rounds=4, keep_min=12 if cap_rule != "wedges" else 40)
        owner[zv] = tid[zv]
    owner, _c = cap_by_flow(nb, f, zone, owner)
    lv = np.nonzero(owner < 0)[0]
    if len(lv):
        src = np.nonzero(owner >= 0)[0]
        _d, near = R.spread(nb, src, labels=owner[src])
        owner[lv] = near[lv]
    # one number per wire that has hair, in a row
    used = sorted(int(x) for x in np.unique(owner) if x >= 0)
    new = np.full(len(wires) + 1, -1, dtype=np.int64)
    new[used] = np.arange(len(used))
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
        edges_cut = faces_split = 0
        ids = owner[inv]
    ids = np.where(ids >= 0, new[np.maximum(ids, 0)], -9)
    strand = face_colours(me, ids)
    nv = len(me.vertices)
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    for pg in me.polygons:  # border vertices: a wire of a face they are on
        for li in range(pg.loop_start, pg.loop_start + pg.loop_total):
            if ids[lvi[li]] < 0 and strand[pg.index] >= 0:
                ids[lvi[li]] = strand[pg.index]
    w_all = np.ones(nv, dtype=np.float32)
    w_all[:old_n] = wv
    e_all = np.ones(nv, dtype=np.float32)
    e_all[:old_n] = extv
    if nv > old_n:
        ev = np.empty(len(me.edges) * 2, dtype=np.int32)
        me.edges.foreach_get("vertices", ev)
        ev = ev.reshape(-1, 2)
        acc = np.zeros(nv)
        num = np.zeros(nv)
        for a_, b_ in ev:
            if a_ >= old_n > b_:
                acc[a_] += wv[b_]
                num[a_] += 1
            elif b_ >= old_n > a_:
                acc[b_] += wv[a_]
                num[b_] += 1
        m = (np.arange(nv) >= old_n) & (num > 0)
        w_all[m] = (acc[m] / num[m]).astype(np.float32)
    # the wires
    cu = wires_obj.data
    while len(cu.splines):
        cu.splines.remove(cu.splines[0])
    kinds = []
    parents = []
    for k in used:
        w = wires[k]
        cen = w["centres"]
        lead = 0
        # the strip this strand got inside a sheet or the cap: the wire starts there, not where the tube starts
        zs = np.nonzero(melted & (owner == k))[0]
        if len(zs) >= 3 and len(w["rings"]):
            d0 = rings[w["rings"][0]]["level"] * h
            zs = zs[D[zs] < d0]
            if len(zs) >= 3:
                bins = np.floor((D[zs] - D[zs].min()) / 0.015).astype(np.int64)
                pre = []
                for s in range(int(bins.max()) + 1):
                    m = bins == s
                    if m.sum() >= 2:
                        pre.append(P[zs[m]].mean(axis=0))
                if pre:
                    cen = np.vstack([np.array(pre), cen]) if len(cen) else np.array(pre)
                    lead = len(pre)
        c = smooth_line(cen)
        rad = np.full(len(c), 0.01)
        if len(w["rings"]):
            rr = np.array([rings[r]["length"] for r in w["rings"]]) / (2 * np.pi)
            if lead:
                rr = np.concatenate([np.full(lead, rr[0]), rr])
            rad = np.interp(np.linspace(0, 1, len(c)), np.linspace(0, 1, len(rr)), rr)
        if len(c) >= 3:
            c, rad = R.simplify(c, rad, tolerance=0.010)[:2]  # few control points: each one is a grip to move
        if len(c) < 2:
            c = np.vstack([c[:1], c[:1] + (0, 0, -0.01)]) if len(c) else np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -0.01]])
            rad = np.full(2, 0.01)
        R.add_spline(wires_obj, c, rad)
        kinds.append(w["kind"])
        parents.append(int(new[w["parent"]]) if w["parent"] >= 0 else -1)
    wires_obj["lw_kinds"] = kinds
    wires_obj["lw_parent"] = parents
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
    R._set(me, "lw_id", ids.astype(np.int32))
    R._set(me, "lw_f", fv)
    R._set(me, "lw_w", w_all)
    R._set(me, "lw_ext", e_all)
    me.attributes["lw_lock"].data.foreach_set("value", np.zeros(len(me.polygons), dtype=np.int32))
    try:
        R.ensure_deform(hair, wires_obj)
        R.refresh_rest(hair, wires_obj)
        st["rest_shift_mm"] = rest_shift(hair) * 1000
        if st["rest_shift_mm"] > 0.05:
            raise RuntimeError("the hair moved %.3f mm when it was tied to the wires" % st["rest_shift_mm"])
    except Exception:
        md = hair.modifiers.get(R.GROUP)
        if md is not None:
            hair.modifiers.remove(md)
        raise
    hair["lw_picked"] = []
    hair["lw_hidden"] = []
    hair["lw_new"] = []
    kk = {}
    for x in kinds:
        kk[x] = kk.get(x, 0) + 1
    st.update(
        wires=len(used),
        kinds=kk,
        short_merged=len(short),
        cap_vertices=int(zone.sum()),
        edges_cut=int(edges_cut),
        faces_split=int(faces_split),
        vertices=int(nv),
        faces=int(len(me.polygons)),
    )
    return st


def rest_shift(hair):
    """How far the deform moves the hair right now (metres), other modifiers switched off for the check."""
    import bpy

    from . import strands as S

    me = hair.data
    dm = hair.modifiers.get(S.R.GROUP)
    others = [(m, m.show_viewport) for m in hair.modifiers if m is not dm]
    for m, _s in others:
        m.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        ev = hair.evaluated_get(dg).data
        if len(ev.vertices) != len(me.vertices):
            return float("inf")
        e = np.empty(len(ev.vertices) * 3, dtype=np.float32)
        ev.vertices.foreach_get("co", e)
        r = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", r)
        return float(np.abs(e - r).max())
    finally:
        for m, s in others:
            m.show_viewport = s

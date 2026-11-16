# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Lida
# Prototype, second design: strands are found from their tips and followed toward the root;
# the melted part near the crown is divided by flow lines of a smooth field, not vertex by vertex.
#   find_tips()        dead ends of the surface (candidates for strand tips)
#   trace_from_tip()   follow one strand from its tip toward the root, passing places where it only touches a neighbour
#   detect_from_tips() all strands, one id per tip
#   melted_field()     smooth value on the melted part: 0 at the crown, 1 where the strands leave it
#   flow_line()        the line of steepest change of that value through the faces
# Nothing here changes a mesh. Importing registers nothing.

import numpy as np

from . import rewire as R
from . import wire as W


def components(nb):
    n = len(nb)
    comp = np.full(n, -1, dtype=np.int64)
    k = 0
    for s in range(n):
        if comp[s] >= 0:
            continue
        stack = [s]
        comp[s] = k
        while stack:
            v = stack.pop()
            for u, _l in nb[v]:
                if comp[u] < 0:
                    comp[u] = k
                    stack.append(u)
        k += 1
    return comp, k


def distance_from_root(P, nb, root):
    """Distance along the surface from the point of each connected piece that is nearest the root."""
    comp, k = components(nb)
    D = np.full(len(P), np.inf)
    for c in range(k):
        vs = np.nonzero(comp == c)[0]
        src = int(vs[int(np.argmin(np.linalg.norm(P[vs] - root, axis=1)))])
        d, _ = R.spread(nb, [src])
        D[vs] = d[vs]
    return D, comp


def find_tips(nb, D):
    """Vertices farther from the root than everything within two edges: dead ends of the surface."""
    out = []
    for v in range(len(nb)):
        if not np.isfinite(D[v]):
            continue
        ok = True
        for u, _l in nb[v]:
            if D[u] > D[v]:
                ok = False
                break
            for x, _l2 in nb[u]:
                if D[x] > D[v]:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            out.append(v)
    return sorted(out, key=lambda v: -D[v])


def _march(P, T, first, direction, window, step, max_steps, pass_through, grow, min_hw, recover=4):
    """Follow the tube from `first` in one direction. Where the section suddenly grows (the strand meets
    something), keep going straight for up to `pass_through`: if a section of the old size returns on the same
    line, the strand only touched a neighbour. Where the section is lost (a sharp bend), read the direction
    of the tube again from the surface around the last centre and try once more.
    Returns (stations, how it ended, sections passed, recoveries)."""
    out = []
    c = first["centre"].copy()
    d = direction.copy()
    hold = 0
    passed = 0
    end = "merge"
    rec = 0

    def bad(s):
        return s is None or s["near"] > max(window * 0.5, step * 2)

    for _ in range(max_steps):
        s = W.slice_section(P, T, c + d * step, d, window)
        if bad(s) and not hold and rec < recover:
            ax = W.local_axis(P, T, c, window)
            if ax is not None:
                if float(ax @ d) < 0:
                    ax = -ax
                for stp in (step, step * 0.5):
                    s2 = W.slice_section(P, T, c + ax * stp, ax, window)
                    if not bad(s2) and not s2["saturated"]:
                        s = s2
                        d = ax
                        rec += 1
                        break
        if bad(s):
            end = "lost" if (hold or out) and not (out and out[-1]["hw"] < 3 * min_hw) else "tip"
            break
        hist = [first["hw"]] + [x["hw"] for x in out]
        ref = float(np.median(hist[-6:]))
        big = s["saturated"] or (len(hist) >= 3 and s["hw"] > grow * ref)
        if (
            hold
            and not big
            and (s["hw"] < 0.5 * ref or np.linalg.norm(s["centre"] - (c + d * step)) > 1.5 * max(ref, 0.004))
        ):
            big = True  # something else, not the strand coming back
        if big:
            hold += 1
            if hold * step > pass_through:
                end = "merge"
                break
            c = c + d * step
            continue
        nd = s["centre"] - c
        ln = np.linalg.norm(nd)
        if ln < step * 0.2 or float(nd @ d) <= 0:
            end = "stall"
            break
        if hold:
            passed += 1
            hold = 0
        d = d * 0.35 + nd / ln * 0.65
        d /= np.linalg.norm(d)
        c = s["centre"]
        out.append(s)
        if s["hw"] < min_hw:
            end = "tip"
            break
    return out, end, passed, rec


def trace_from_tip(
    P, T, nb, tip, window=0.03, step=0.008, max_steps=400, pass_through=0.05, grow=1.8, min_hw=0.0012, back=(0.04, 0.06)
):
    """One strand, named by its tip. Curled tips cut badly, so start a few cm up the strand from the tip and
    follow it both ways. Returns (stations ordered root -> tip, info) or ([], info)."""
    seen = {int(tip): 0.0}
    front = [int(tip)]
    while front:
        nxt = []
        for v in front:
            for u, l in nb[v]:
                dd = seen[v] + l
                if dd < back[1] and dd < seen.get(u, np.inf):
                    seen[u] = dd
                    nxt.append(u)
        front = nxt
    vs = [v for v, dd in seen.items() if dd >= back[0]]
    if len(vs) < 3:
        far = sorted(seen, key=seen.get)[-max(3, len(seen) // 3) :]
        vs = far
    if len(vs) < 3:
        return [], dict(why="too small")
    cen = P[vs].mean(axis=0)
    seed = P[vs[int(np.argmin(np.linalg.norm(P[vs] - cen, axis=1)))]]
    axis = W.local_axis(P, T, seed, window)
    if axis is None:
        return [], dict(why="no axis")
    first = W.slice_section(P, T, seed, axis, window)
    if first is None or first["saturated"]:
        return [], dict(why="no section")
    a, ea, pa, ra = _march(P, T, first, axis, window, step, max_steps, pass_through, grow, min_hw)
    b, eb, pb, rb = _march(P, T, first, -axis, window, step, max_steps, pass_through, grow, min_hw)
    st = b[::-1] + [first] + a
    ends = (eb, ea)
    c0, c1 = st[0]["centre"], st[-1]["centre"]
    if np.linalg.norm(c0 - P[tip]) < np.linalg.norm(c1 - P[tip]):
        st = st[::-1]
        ends = ends[::-1]
    miss = float(np.linalg.norm(st[-1]["centre"] - P[tip]))
    return st, dict(why="ok", root_end=ends[0], tip_end=ends[1], tip_miss=miss, passed=pa + pb, recovered=ra + rb)


def detect_from_tips(P, T, nb, D, min_stations=5, log=None):
    """One strand per tip. Returns (strands, owner per vertex, stats)."""
    owner = np.full(len(P), -1, dtype=np.int64)
    tips = find_tips(nb, D)
    strands = []
    rejected = 0
    passed = 0
    why = {}
    ends = {}
    recovered = 0
    for tip in tips:
        if owner[tip] >= 0:
            continue
        st, info = trace_from_tip(P, T, nb, tip)
        why[info["why"]] = why.get(info["why"], 0) + 1
        if len(st) < min_stations or info.get("tip_miss", 1.0) > 0.05:
            rejected += 1
            continue
        ids = np.unique(np.concatenate([np.array(s.get("verts", []), dtype=np.int64) for s in st]))
        fresh = ids[owner[ids] < 0]
        if len(fresh) < 0.5 * len(ids) or len(fresh) < 6:
            rejected += 1
            continue
        k = len(strands)
        owner[fresh] = k
        owner[tip] = k
        passed += info["passed"]
        ends[info["root_end"]] = ends.get(info["root_end"], 0) + 1
        recovered += info["recovered"]
        strands.append(dict(stations=st, tip=int(tip), fused_root=True, root_end=info["root_end"]))
        if log and k % 10 == 0:
            log("strand %d  owned %.0f%%" % (k, 100.0 * (owner >= 0).mean()))
    return (
        strands,
        owner,
        dict(
            tip_candidates=len(tips),
            strands=len(strands),
            rejected=rejected,
            contacts_passed=passed,
            recovered=recovered,
            trace=why,
            root_ends=ends,
        ),
    )


def melted_field(P, T, nb, owner, D, crown, root_radius=0.025):
    """Smooth value on the part no strand owns that is connected to the crown: 0 around the crown,
    1 on the first ring of every strand that leaves it. Returns (value per vertex or nan, info)."""
    n = len(P)
    free = owner < 0
    seeds = np.nonzero(free & (D < root_radius))[0]
    if not len(seeds):
        fv = np.nonzero(free)[0]
        seeds = fv[[int(np.argmin(np.linalg.norm(P[fv] - P[crown], axis=1)))]]
    zone = np.zeros(n, dtype=bool)
    stack = [int(s) for s in seeds]
    zone[seeds] = True
    while stack:
        v = stack.pop()
        for u, _l in nb[v]:
            if free[u] and not zone[u]:
                zone[u] = True
                stack.append(u)
    rootset = np.zeros(n, dtype=bool)
    rootset[seeds] = True
    ring = np.zeros(n, dtype=bool)
    for v in np.nonzero(zone)[0]:
        for u, _l in nb[v]:
            if not free[u]:
                ring[u] = True
    unknown = np.nonzero(zone & ~rootset)[0]
    idx = np.full(n, -1, dtype=np.int64)
    idx[unknown] = np.arange(len(unknown))
    m = len(unknown)
    A = np.zeros((m, m))
    b = np.zeros(m)
    for i, v in enumerate(unknown):
        for u, l in nb[v]:
            w = 1.0 / max(l, 1e-6)
            if zone[u] and not rootset[u]:
                A[i, i] += w
                A[i, idx[u]] -= w
            elif rootset[u]:
                A[i, i] += w
            elif ring[u]:
                A[i, i] += w
                b[i] += w
        if A[i, i] == 0:
            A[i, i] = 1.0
    x = np.linalg.solve(A, b) if m else np.zeros(0)
    f = np.full(n, np.nan)
    f[rootset] = 0.0
    f[ring] = 1.0
    f[unknown] = x
    return f, dict(zone=int(zone.sum()), unknown=int(m), ring=int(ring.sum()), rootset=int(rootset.sum())), zone, ring


class Flow:
    """Steepest-descent lines of a value given on vertices, traced through the faces."""

    def __init__(self, P, T, f):
        self.P = P
        self.f = f
        ok = np.isfinite(f[T]).all(axis=1)
        self.T = T[ok]
        pa, pb, pc = P[self.T[:, 0]], P[self.T[:, 1]], P[self.T[:, 2]]
        nrm = np.cross(pb - pa, pc - pa)
        n2 = np.maximum((nrm * nrm).sum(axis=1), 1e-24)
        fa, fb, fc = f[self.T[:, 0]], f[self.T[:, 1]], f[self.T[:, 2]]
        self.g = ((fb - fa)[:, None] * np.cross(nrm, pa - pc) + (fc - fa)[:, None] * np.cross(nrm, pb - pa)) / n2[
            :, None
        ]
        self.vt = {}
        self.et = {}
        for ti, (a, b, c) in enumerate(self.T):
            for v in (a, b, c):
                self.vt.setdefault(int(v), []).append(ti)
            for u, v in ((a, b), (b, c), (c, a)):
                self.et.setdefault((min(int(u), int(v)), max(int(u), int(v))), []).append(ti)

    def _hit(self, x, d, p, q):
        """Ray x + s d against segment p-q. Returns (s, t) or None."""
        e = self.P[q] - self.P[p]
        M = np.stack([d, -e], axis=1)
        rhs = self.P[p] - x
        sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)
        s, t = float(sol[0]), float(sol[1])
        if s > 1e-9 and -1e-6 <= t <= 1 + 1e-6 and np.linalg.norm(M @ sol - rhs) < 1e-6 + 1e-3 * np.linalg.norm(e):
            return s, min(max(t, 0.0), 1.0)
        return None

    def line(self, start, stop_below=0.02, max_steps=4000):
        """From vertex `start` toward lower values. Returns the list of points."""
        P, f = self.P, self.f
        pts = [P[start].copy()]
        loc = ("v", int(start))
        visited = set()
        for _ in range(max_steps):
            if loc[0] == "v":
                v = loc[1]
                if f[v] <= stop_below or v in visited:
                    break
                visited.add(v)
                best = None
                for ti in self.vt.get(v, []):
                    g = self.g[ti]
                    gn = float(np.linalg.norm(g))
                    if gn < 1e-9:
                        continue
                    p, q = [int(u) for u in self.T[ti] if int(u) != v]
                    h = self._hit(P[v], -g, p, q)
                    if h is not None and (best is None or gn > best[0]):
                        best = (gn, ti, p, q, h[1])
                if best is not None:
                    _gn, ti, p, q, t = best
                    if t < 1e-4:
                        loc = ("v", p)
                        pts.append(P[p].copy())
                    elif t > 1 - 1e-4:
                        loc = ("v", q)
                        pts.append(P[q].copy())
                    else:
                        x = P[p] + (P[q] - P[p]) * t
                        pts.append(x)
                        loc = ("e", p, q, t, ti)
                    continue
                cand = []
                for ti in self.vt.get(v, []):
                    for u in self.T[ti]:
                        u = int(u)
                        if u != v and f[u] < f[v]:
                            cand.append(((f[v] - f[u]) / max(np.linalg.norm(P[u] - P[v]), 1e-9), u))
                if not cand:
                    break
                u = max(cand)[1]
                loc = ("v", u)
                pts.append(P[u].copy())
            else:
                _e, p, q, t, t0 = loc
                x = P[p] + (P[q] - P[p]) * t
                if f[p] + (f[q] - f[p]) * t <= stop_below:
                    break
                others = [ti for ti in self.et.get((min(p, q), max(p, q)), []) if ti != t0]
                moved = False
                for ti in others:
                    g = self.g[ti]
                    r = [int(u) for u in self.T[ti] if int(u) not in (p, q)][0]
                    best = None
                    for a, b in ((p, r), (q, r)):
                        h = self._hit(x, -g, a, b)
                        if h is not None and (best is None or h[0] < best[0]):
                            best = (h[0], a, b, h[1])
                    if best is not None:
                        _s, a, b, tt = best
                        if tt < 1e-4:
                            loc = ("v", a)
                            pts.append(P[a].copy())
                        elif tt > 1 - 1e-4:
                            loc = ("v", b)
                            pts.append(P[b].copy())
                        else:
                            pts.append(P[a] + (P[b] - P[a]) * tt)
                            loc = ("e", a, b, tt, ti)
                        moved = True
                        break
                if not moved:  # the value rises on the other side: run along the edge
                    u = p if f[p] < f[q] else q
                    loc = ("v", u)
                    pts.append(P[u].copy())
        return pts


def notches(nb, owner, zone, f):
    """Where two strands leave the melted part side by side: the melted vertex between them nearest the crown
    (lowest value). Returns {(i, j): vertex}."""
    touch = {}
    for v in np.nonzero(zone)[0]:
        ks = {int(owner[u]) for u, _l in nb[v] if owner[u] >= 0}
        if ks:
            touch[int(v)] = ks
    best = {}
    for v, ks in touch.items():
        pairs = set()
        if len(ks) >= 2:
            ks = sorted(ks)
            pairs |= {(a, b) for i, a in enumerate(ks) for b in ks[i + 1 :]}
        for u, _l in nb[v]:
            ku = touch.get(int(u))
            if ku and len(ks) == 1 and len(ku) == 1:
                a, b = next(iter(ks)), next(iter(ku))
                if a != b:
                    pairs.add((min(a, b), max(a, b)))
        for pr in pairs:
            if pr not in best or f[v] < f[best[pr]]:
                best[pr] = v
    return best


def iso_centre(P, T, f, level, near, reach=0.08, max_loop=0.25):
    """The contour of the value at `level` that passes nearest `near`. If it is a closed loop no longer than
    `max_loop` (the surface is a tube there) return its centre, else None (an open sheet: stay on the surface)."""
    tri = P[T]
    ok = np.isfinite(f[T]).all(axis=1) & (np.linalg.norm(tri.mean(axis=1) - near, axis=1) < reach)
    ti = T[ok]
    fv = f[ti]
    cross = (fv.min(axis=1) < level) & (fv.max(axis=1) >= level)
    ti, fv = ti[cross], fv[cross]
    if not len(ti):
        return None
    segs, keys = [], []
    for k in range(len(ti)):
        pts, ks = [], []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            fa, fb = fv[k, a], fv[k, b]
            if (fa < level) != (fb < level):
                s = (level - fa) / (fb - fa)
                va, vb = int(ti[k, a]), int(ti[k, b])
                pts.append(P[va] + (P[vb] - P[va]) * s)
                ks.append((min(va, vb), max(va, vb)))
        if len(pts) == 2:
            segs.append(pts)
            keys.append(ks)
    if not segs:
        return None
    segs = np.array(segs)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for ka, kb in keys:
        parent[find(ka)] = find(kb)
    comp = np.array([hash(find(k[0])) for k in keys])
    mid = segs.mean(axis=1)
    pick = comp == comp[int(np.argmin(np.linalg.norm(mid - near, axis=1)))]
    count = {}
    for ks, use in zip(keys, pick):
        if use:
            for key in ks:
                count[key] = count.get(key, 0) + 1
    if any(c != 2 for c in count.values()):
        return None  # open: a sheet, not a tube
    sp = segs[pick]
    ln = np.linalg.norm(sp[:, 1] - sp[:, 0], axis=1)
    if ln.sum() > max_loop:
        return None
    return (sp.mean(axis=1) * ln[:, None]).sum(axis=0) / max(ln.sum(), 1e-12)


def extend_wire(flow, P, T, f, start, spacing=0.008, smooth=6):
    """From where a strand leaves the melted part to the crown: follow the flow on the surface, but where the
    surface is a tube (a trunk) run through its middle; then smooth. Returns points ordered crown -> strand."""
    line = np.array(flow.line(int(start)))
    if len(line) < 3:
        return None
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    m = max(4, int(cum[-1] / spacing) + 1)
    s = np.linspace(0, cum[-1], m)
    pts = np.stack([np.interp(s, cum, line[:, k]) for k in range(3)], axis=1)
    # value at each sample: from the nearest vertex of the field (good enough to pick the contour level)
    valid = np.nonzero(np.isfinite(f))[0]
    out = pts.copy()
    inside = np.zeros(m, dtype=bool)
    for i in range(m):
        v = valid[int(np.argmin(np.linalg.norm(P[valid] - pts[i], axis=1)))]
        c = iso_centre(P, T, f, float(f[v]), pts[i])
        if c is not None:
            out[i] = c
            inside[i] = True
    for _ in range(smooth):
        out[1:-1] = (out[:-2] + 2 * out[1:-1] + out[2:]) / 4
    return out[::-1], float(inside.mean())


def detect_trunks(P, T, nb, D, owner, strands, windows=(0.05, 0.08), step=0.012, min_stations=4):
    """What the strands run into is often a thicker tube that several strands leave: a trunk.
    Follow those the same way, with a wider reading window, starting next to what is already owned.
    Appends to strands (trunk=True) and fills owner. Returns the number added."""
    added = 0
    for win in windows:
        cand = [int(v) for v in np.nonzero(owner < 0)[0] if any(owner[u] >= 0 for u, _l in nb[v])]
        cand.sort(key=lambda v: -D[v] if np.isfinite(D[v]) else 0.0)
        for v in cand:
            if owner[v] >= 0:
                continue
            ax = W.local_axis(P, T, P[v], win)
            if ax is None:
                continue
            first = W.slice_section(P, T, P[v], ax, win)
            if first is None or first["saturated"] or not first.get("verts"):
                continue
            ids = np.array(first["verts"], dtype=np.int64)
            if (owner[ids] >= 0).mean() > 0.5:
                continue
            a, ea, _p, _r = _march(P, T, first, ax, win, step, 300, 0.02, 1.8, 0.0012, recover=2)
            b, eb, _p, _r = _march(P, T, first, -ax, win, step, 300, 0.02, 1.8, 0.0012, recover=2)
            st = b[::-1] + [first] + a
            if len(st) < min_stations:
                continue
            ids = np.unique(np.concatenate([np.array(s.get("verts", []), dtype=np.int64) for s in st]))
            fresh = ids[owner[ids] < 0]
            if len(fresh) < 0.5 * len(ids) or len(fresh) < 8:
                continue
            e0 = D[int(np.argmin(np.linalg.norm(P - st[0]["centre"], axis=1)))]
            e1 = D[int(np.argmin(np.linalg.norm(P - st[-1]["centre"], axis=1)))]
            if np.isfinite(e0) and np.isfinite(e1) and e0 > e1:
                st = st[::-1]
            owner[fresh] = len(strands)
            strands.append(dict(stations=st, tip=None, trunk=True, fused_root=True, window=win))
            added += 1
    return added


def link_parents(P, D, cent, rad, reach=0.015):
    """For every strand: the strand or trunk its root end runs into, and where along it. {child: (parent, factor)}"""
    rootD = [float(D[int(np.argmin(np.linalg.norm(P - c[0], axis=1)))]) for c in cent]
    parent = {}
    for k, c in enumerate(cent):
        i = min(3, len(c) - 1)
        dv = c[0] - c[i]
        ln = np.linalg.norm(dv)
        probe = np.array([c[0], c[0] + dv / max(ln, 1e-9) * reach, c[0] + dv / max(ln, 1e-9) * reach * 2.5])
        best = None
        for j, cj in enumerate(cent):
            if j == k or len(cj) < 2 or not rootD[j] < rootD[k]:
                continue
            ff, dd = R.nearest_on_polyline(cj, probe)
            m = int(np.argmin(dd))
            if dd[m] < max(rad[j] * 1.6, 0.02) and (best is None or dd[m] < best[0]):
                best = (float(dd[m]), j, float(ff[m]))
        if best is not None:
            parent[k] = (best[1], best[2])
    return parent


def chain_wire(k, cent, parent, depth=8):
    """Centre line of strand k continued up through its parents. Returns (points root -> tip, top ancestor)."""
    pts = cent[k]
    cur = k
    for _ in range(depth):
        if cur not in parent:
            break
        j, fp = parent[cur]
        cj = cent[j]
        cum, total = R.polyline_param(cj)
        keep = cj[cum <= fp * total]
        if len(keep):
            pts = np.vstack([keep, pts])
        cur = j
    return pts, cur


def route_wires(cent, rads, crown_links, leaves, hop=2.0, hop_fee=0.03):
    """Route every leaf strand to the crown through the middles of the tubes.
    Nodes are the section centres of all strands and trunks. Steps: along a tube (its length), from one tube to
    a tube it touches or runs into (dearer), and from a tube that meets the melted part to the crown
    (crown_links: {node: (station index, points crown -> station)}).
    Returns {leaf: (points crown -> tip, hops)} for the leaves that reach the crown."""
    import heapq

    off = np.concatenate([[0], np.cumsum([len(c) for c in cent])]).astype(int)
    pts = np.vstack(cent)
    node = np.concatenate([np.full(len(c), k) for k, c in enumerate(cent)])
    rr = np.concatenate([np.full(len(c), rads[k]) for k, c in enumerate(cent)])
    N = len(pts)
    adj = [[] for _ in range(N + 1)]
    CROWN = N
    for k, c in enumerate(cent):
        for i in range(len(c) - 1):
            a, b = off[k] + i, off[k] + i + 1
            l = float(np.linalg.norm(c[i + 1] - c[i]))
            adj[a].append((b, l, 0))
            adj[b].append((a, l, 0))
    for a in range(N):  # tubes that touch: nearest station of every other tube
        dd = np.linalg.norm(pts - pts[a], axis=1)
        near = np.nonzero((node != node[a]) & (dd < 1.5 * np.maximum(rr, rr[a]) + 0.01))[0]
        best = {}
        for b in near:
            kb = int(node[b])
            if kb not in best or dd[b] < dd[best[kb]]:
                best[kb] = int(b)
        for b in best.values():
            adj[a].append((b, float(dd[b]) * hop + hop_fee, 1))
    ext = {}
    for k, (i, line) in crown_links.items():
        a = off[k] + int(i)
        l = float(np.linalg.norm(np.diff(line, axis=0), axis=1).sum())
        adj[CROWN].append((a, l, 0))
        ext[a] = line
    dist = np.full(N + 1, np.inf)
    prev = np.full(N + 1, -1, dtype=np.int64)
    hops = np.zeros(N + 1, dtype=np.int64)
    dist[CROWN] = 0.0
    heap = [(0.0, CROWN)]
    while heap:
        dv, v = heapq.heappop(heap)
        if dv > dist[v]:
            continue
        for u, l, h in adj[v]:
            if dv + l < dist[u]:
                dist[u] = dv + l
                prev[u] = v
                hops[u] = hops[v] + h
                heapq.heappush(heap, (dist[u], u))
    out = {}
    for k in leaves:
        a = off[k]
        if not np.isfinite(dist[a]):
            continue
        path = [a]
        while prev[path[-1]] >= 0 and path[-1] != CROWN:
            path.append(int(prev[path[-1]]))
        path = path[::-1]  # crown ... leaf root
        if path[0] == CROWN:
            path = path[1:]
        own = [i for i, v in enumerate(path) if node[v] == k]
        cut = own[0] if own else len(path)
        head = path[:cut]
        start = (path[cut] - off[k]) if own else 0  # where the route enters the leaf
        line = [ext[head[0]]] if head and head[0] in ext else ([ext[path[0]]] if path and path[0] in ext else [])
        if head:
            line.append(pts[head])
        line.append(cent[k][start:])
        entry = (int(node[head[-1]]), int(head[-1] - off[node[head[-1]]])) if head else None
        out[k] = (np.vstack(line), int(hops[a]), entry)
    return out


def build_wire_tree(cent, rad, parent, crown_links, has_tip=None):
    """Wires as a tree. A wire runs from where it starts down to one tip, going through a trunk into the longest
    thing that leaves it. A wire that starts at the melted part is a base wire (crown_links gives its way to the
    crown); a wire that starts where it runs into another one is a branch, cut at that point.
    parent: {node: (parent node, factor along the parent)}.
    Returns (wires, wire of every node). wire = dict(nodes, points, kind, parent_wire, joint)."""
    n = len(cent)
    kids = {}
    for k, (j, _f) in parent.items():
        kids.setdefault(j, []).append(k)
    length = [float(np.linalg.norm(np.diff(c, axis=0), axis=1).sum()) for c in cent]
    down = {}

    def reach(k, depth=0):
        if k not in down:
            down[k] = length[k] + (max(reach(c, depth + 1) for c in kids[k]) if k in kids and depth < 20 else 0.0)
        return down[k]

    # a strand with its own tip keeps its wire to that tip; only a trunk hands its wire on
    main = {}
    for j, cs in kids.items():
        if has_tip is not None and has_tip[j]:
            continue
        head_on = [c for c in cs if parent[c][1] >= 0.999]
        main[j] = max(head_on or cs, key=reach)
    starts = [k for k in range(n) if k not in parent or main.get(parent[k][0]) != k]
    wires = []
    of = np.full(n, -1, dtype=np.int64)
    for s in starts:
        nodes = [s]
        pts = [cent[s]]
        while nodes[-1] in main and len(nodes) < 30:
            c = main[nodes[-1]]
            fp = parent[c][1]
            cum, total = R.polyline_param(pts[-1])
            keep = pts[-1][cum <= fp * total + 1e-9]
            pts[-1] = keep if len(keep) >= 1 else pts[-1][:1]
            nodes.append(c)
            pts.append(cent[c])
        kind = "base" if s in crown_links else ("branch" if s in parent else "loose")
        joint = None
        if kind == "base":
            pts.insert(0, crown_links[s][1])
        elif kind == "branch":
            j, fp = parent[s]
            cj = cent[j]
            cum, total = R.polyline_param(cj)
            joint = np.array([np.interp(fp * total, cum, cj[:, q]) for q in range(3)])
            pts.insert(0, joint[None, :])
        for k in nodes:
            of[k] = len(wires)
        wires.append(
            dict(
                nodes=nodes,
                points=np.vstack(pts),
                kind=kind,
                parent_node=parent[s][0] if s in parent else None,
                joint=joint,
            )
        )
    for w in wires:
        w["parent_wire"] = int(of[w["parent_node"]]) if w["parent_node"] is not None else None
    return wires, of


def link_continuations(P, D, cent, is_trunk, reach=0.07):
    """A tube that was followed in two pieces (a strand that stopped early, then a trunk piece above it) is one
    tube: where the root end of a piece meets the far end of a trunk piece head-on, the trunk is its parent at
    its very end. Returns {child: (parent, 1.0)}."""
    rootD = [float(D[int(np.argmin(np.linalg.norm(P - c[0], axis=1)))]) for c in cent]

    def unit(v):
        return v / max(np.linalg.norm(v), 1e-9)

    out = {}
    for k, c in enumerate(cent):
        if len(c) < 2:
            continue
        dk = unit(c[min(3, len(c) - 1)] - c[0])
        best = None
        for j, cj in enumerate(cent):
            if j == k or not is_trunk[j] or len(cj) < 2 or not rootD[j] < rootD[k]:
                continue
            dj = unit(cj[-1] - cj[-min(4, len(cj))])
            gap = c[0] - cj[-1]
            g = float(np.linalg.norm(gap))
            if g < reach and float(dj @ dk) > 0.5 and (g < 0.012 or float(unit(gap) @ dj) > 0.3):
                if best is None or g < best[0]:
                    best = (g, j)
        if best is not None:
            out[k] = (best[1], 1.0)
    return out


def surface_labels(P, strands, limit=1.8):
    """Label every vertex by the tube whose surface it lies on. For each tube: distance from the vertex to the
    tube's centre line, compared with the tube's half thickness and half width there. A vertex between the two
    lies on that tube (cost 0); outside the range the cost grows with the ratio. The cheapest tube wins.
    Vertices farther than `limit` half widths from every centre line get -1."""
    cost = np.full((len(P), len(strands)), np.inf)
    for k, st in enumerate(strands):
        c = np.array([s["centre"] for s in st["stations"]])
        if len(c) < 2:
            continue
        hw = np.array([max(s["hw"], 1e-4) for s in st["stations"]])
        ht = np.array([max(s["ht"], 1e-4) for s in st["stations"]])
        k5 = 5
        pad = lambda a: np.array([np.median(np.pad(a, k5 // 2, mode="edge")[i : i + k5]) for i in range(len(a))])
        hw = pad(hw)
        ht = np.minimum(pad(ht), hw)
        f, dist = R.nearest_on_polyline(c, P)
        cum, total = R.polyline_param(c)
        s = f * total
        w = np.interp(s, cum, hw)
        h = np.interp(s, cum, ht)
        beyond = (f <= 0.0) | (f >= 1.0)  # past the ends of this piece
        over = np.log(np.maximum(dist / w, 1.0))
        under = np.log(np.maximum(h / np.maximum(dist, 1e-6), 1.0)) * 0.5
        cc = over + under + np.where(beyond, 0.15, 0.0)
        cc[dist > limit * w] = np.inf
        cost[:, k] = cc
    lab = np.argmin(cost, axis=1)
    best = cost[np.arange(len(P)), lab]
    lab[~np.isfinite(best)] = -1
    return lab, best


def tidy_labels(nb, lab, rounds=3, keep_min=12):
    """One tube, one piece: for every label keep its largest connected piece (and any other piece of at least
    keep_min vertices); smaller islands take the label that surrounds them. Then a vertex whose neighbours
    mostly have another label takes it. Returns (labels, islands moved)."""
    lab = lab.copy()
    moved = 0
    for _ in range(rounds):
        seen = np.zeros(len(lab), dtype=bool)
        pieces = {}
        for s in np.nonzero(lab >= 0)[0]:
            if seen[s]:
                continue
            k = lab[s]
            stack = [int(s)]
            seen[s] = True
            comp = [int(s)]
            while stack:
                v = stack.pop()
                for u, _l in nb[v]:
                    if not seen[u] and lab[u] == k:
                        seen[u] = True
                        stack.append(u)
                        comp.append(u)
            pieces.setdefault(int(k), []).append(comp)
        changed = 0
        for k, comps in pieces.items():
            comps.sort(key=len, reverse=True)
            for comp in comps[1:]:
                if len(comp) >= keep_min:
                    continue
                around = [int(lab[u]) for v in comp for u, _l in nb[v] if lab[u] != k and lab[u] >= 0]
                if around:
                    vals, cnt = np.unique(around, return_counts=True)
                    lab[comp] = vals[int(np.argmax(cnt))]
                    changed += len(comp)
        new = lab.copy()
        for v in range(len(lab)):
            ks = [int(lab[u]) for u, _l in nb[v] if lab[u] >= 0]
            if len(ks) >= 3:
                vals, cnt = np.unique(ks, return_counts=True)
                i = int(np.argmax(cnt))
                if vals[i] != lab[v] and cnt[i] * 3 >= len(ks) * 2:
                    new[v] = vals[i]
                    changed += 1
        lab = new
        moved += changed
        if not changed:
            break
    return lab, moved


def count_pieces(nb, lab):
    """Connected pieces per label: {label: number of pieces}."""
    seen = np.zeros(len(lab), dtype=bool)
    out = {}
    for s in np.nonzero(lab >= 0)[0]:
        if seen[s]:
            continue
        k = int(lab[s])
        stack = [int(s)]
        seen[s] = True
        while stack:
            v = stack.pop()
            for u, _l in nb[v]:
                if not seen[u] and lab[u] == k:
                    seen[u] = True
                    stack.append(u)
        out[k] = out.get(k, 0) + 1
    return out


def sequential_assign(
    P,
    T,
    lines,
    radii,
    order,
    reach=2.0,
    root_reach=1.25,
    root_part=0.2,
    spacing=0.005,
    spokes=16,
    rounds=2,
    min_radius=0.004,
):
    """One wire at a time. From points along the wire, look outward all the way round (spokes) and take the
    first surface met within reach: that is the hair around this wire. Its vertices go to the wire and are
    locked, so a later wire cannot take them. Near the root the reach is shorter, because there the mesh joins
    its neighbours and spreads sideways. Then each wire is moved to the middle of what it met and the whole
    assignment is done again (rounds).
    lines: polylines root -> tip.  radii: per wire (station centres, half widths).  order: wires, first = first served.
    Returns (owner per vertex, refined lines, stats)."""
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    bvh = BVHTree.FromPolygons([Vector(q) for q in P], [tuple(int(i) for i in tri) for tri in T])
    ang = np.linspace(0, 2 * np.pi, spokes, endpoint=False)
    lines = [np.array(l, float) for l in lines]
    owner = np.full(len(P), -1, dtype=np.int64)
    stats = {}
    for rnd in range(rounds + 1):
        owner[:] = -1
        took = {}
        hits_all = 0
        rays_all = 0
        new_lines = list(lines)
        for w in order:
            line = lines[w]
            if len(line) < 2:
                continue
            cum, total = R.polyline_param(line)
            m = max(3, int(total / spacing) + 1)
            s = np.linspace(0, total, m)
            pts = np.stack([np.interp(s, cum, line[:, q]) for q in range(3)], axis=1)
            tt, nn = R.frames(pts)
            bb = np.cross(tt, nn)
            sc, sh = radii[w]
            near = np.argmin(np.linalg.norm(pts[:, None, :] - sc[None, :, :], axis=2), axis=1)
            rad = np.maximum(sh[near], min_radius)
            u = s / max(total, 1e-9)
            k = root_reach + (reach - root_reach) * np.clip(u / root_part, 0, 1) ** 2
            shift = np.zeros_like(pts)
            mine = set()
            for i in range(m):
                lim = float(k[i] * rad[i])
                dist = np.full(spokes, np.nan)
                for a in range(spokes):
                    dv = nn[i] * np.cos(ang[a]) + bb[i] * np.sin(ang[a])
                    loc, _nrm, idx, dd = bvh.ray_cast(Vector(pts[i]), Vector(dv), lim)
                    rays_all += 1
                    if idx is None:
                        continue
                    tri = T[idx]
                    if (owner[tri] >= 0).all() and not (owner[tri] == w).any():
                        continue  # already someone else's wall
                    hits_all += 1
                    dist[a] = dd
                    for v in tri:
                        if owner[v] < 0:
                            owner[v] = w
                            mine.add(int(v))
                # middle of what was met: opposite spokes pull the point toward the farther wall
                half = spokes // 2
                for a in range(half):
                    da, db = dist[a], dist[a + half]
                    if np.isfinite(da) and np.isfinite(db):
                        dv = nn[i] * np.cos(ang[a]) + bb[i] * np.sin(ang[a])
                        shift[i] += dv * (da - db) / 2 / half * 2
            took[w] = len(mine)
            if rnd < rounds:
                moved = pts + shift
                for _ in range(3):
                    moved[1:-1] = (moved[:-2] + 2 * moved[1:-1] + moved[2:]) / 4
                moved[0] = pts[0]  # the root stays where it is attached
                new_lines[w] = moved
        stats["round_%d" % rnd] = dict(
            assigned=int((owner >= 0).sum()),
            share=float((owner >= 0).mean()),
            hit_rate=float(hits_all / max(rays_all, 1)),
            empty_wires=int(sum(1 for v in took.values() if v == 0)),
        )
        if rnd < rounds:
            lines = new_lines
    return owner, lines, stats


def extend_open_ends(P, T, owner, strands, first_trunk, windows=(0.03, 0.05, 0.08), step=0.008):
    """A trunk piece has no tip, so its far end is never the end of the hair: keep following the tube from there
    until it reaches a tip or runs into hair that another piece already owns. The new sections join the same
    piece (one tube, one piece). Returns (sections added, pieces that reached a tip)."""
    added = 0
    tips = 0
    for k in range(first_trunk, len(strands)):
        st = strands[k]["stations"]
        for win in (strands[k].get("window", windows[0]),) + tuple(windows):
            if len(st) < 3:
                break
            c = np.array([s["centre"] for s in st])
            dv = c[-1] - c[-min(4, len(c))]
            ln = np.linalg.norm(dv)
            if ln < 1e-6:
                break
            out, end, _p, _r = _march(P, T, st[-1], dv / ln, win, step, 300, 0.05, 1.8, 0.0012, recover=3)
            keep = []
            for s in out:
                ids = np.array(s.get("verts", []), dtype=np.int64)
                if len(ids) and ((owner[ids] >= 0) & (owner[ids] != k)).mean() >= 0.6:
                    end = "owned"
                    break
                keep.append(s)
                if len(ids):
                    owner[ids[owner[ids] < 0]] = k
            if keep:
                st.extend(keep)
                added += len(keep)
                if end == "tip":
                    strands[k]["ends_tip"] = True
                    tips += 1
                break
    return added, tips

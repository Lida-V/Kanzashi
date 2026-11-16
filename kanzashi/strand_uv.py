# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""The UV map with one island per strand (LW_StrandUV): unwrapping, packing, and the check."""

import numpy as np

from .edit import HIDE_GROUP, face_strands, set_face_colours, set_hidden


def strand_uv2(
    hair, wires_obj, name="LW_StrandUV", margin=0.004, method="MINIMUM_STRETCH", deep=0.6, squash=0.3, fold_cut=False
):
    """A UV map with one island per strand, made by a real unwrap (no stretching by hand):
    seams on the borders between strands; where a strand is a closed tube, one seam along its length (a path of
    edges from its root end to its tip, kept on one side); Blender's unwrap; then every island at its true size,
    turned so that the root is up and the tip down, and packed without turning.
    Other UV maps, the seams of the mesh, hidden faces and the selection are left as they were."""
    import heapq

    import bpy

    from . import strands as S

    R = S.R
    me = hair.data
    strand = face_strands(me)
    nf = len(strand)
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    _P, _T, _inv, world = R.gather(hair)
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    start = np.array([p.loop_start for p in me.polygons])
    total = np.array([p.loop_total for p in me.polygons])
    face_of_loop = np.repeat(np.arange(nf), total)
    ek = {key: i for i, key in enumerate(me.edge_keys)}
    efaces = [[] for _ in range(len(me.edges))]
    for pg in me.polygons:
        for key in pg.edge_keys:
            efaces[ek[key]].append(pg.index)
    seam0 = np.empty(len(me.edges), dtype=bool)
    me.edges.foreach_get("use_seam", seam0)
    seam = np.zeros(len(me.edges), dtype=bool)
    for ei, fs in enumerate(efaces):
        if len(fs) != 2 or strand[fs[0]] != strand[fs[1]]:
            seam[ei] = True  # borders between strands, open edges, fans
    ev = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    elen = np.linalg.norm(world[ev[:, 0]] - world[ev[:, 1]], axis=1)
    fpar = np.zeros(len(me.loops), dtype=np.float32)  # along the wire, per face corner (to turn the islands)
    n_w = len(wires_obj.data.splines)
    for k in np.unique(strand[strand >= 0]):
        k = int(k)
        if k >= n_w:
            continue
        loops = np.nonzero(strand[face_of_loop] == k)[0]
        vs = np.unique(lvi[loops])
        ff, _d = R.nearest_on_polyline(R.spline_polyline(wires_obj, k), world[vs])
        look = np.full(len(me.vertices), -1, dtype=np.int64)
        look[vs] = np.arange(len(vs))
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
                par[x] = par[par[x]]
                x = par[x]
            return x

        for ei, fs in enumerate(efaces):
            if not seam[ei] and len(fs) == 2:
                ra, rb = find(fs[0]), find(fs[1])
                if ra != rb:
                    par[rb] = ra
        root = np.array([find(f) for f in range(nf)])
        root[strand < 0] = -1
        groups = {}
        for f in np.nonzero(root >= 0)[0]:
            groups.setdefault(int(root[f]), []).append(int(f))
        added = 0
        for faces in groups.values():
            if len(faces) < 4:
                continue
            es = {e for f in faces for e in fedges[f]}
            rim = [e for e in es if seam[e]]
            inner = [e for e in es if not seam[e]]
            adj = {}
            for e in inner:
                a_, b_ = int(ev[e, 0]), int(ev[e, 1])
                c = float(elen[e]) + 1e-9
                adj.setdefault(a_, []).append((b_, c, e))
                adj.setdefault(b_, []).append((a_, c, e))
            if len(adj) < 3:
                continue
            # rims: loops of seam edges round this island
            rp = {}

            def rfind(x):
                while rp.setdefault(x, x) != x:
                    rp[x] = rp[rp[x]]
                    x = rp[x]
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
                dist = {v: 0.0 for v in sources if v in adj}
                prev = {}
                heap = [(0.0, v) for v in dist]
                heapq.heapify(heap)
                while heap:
                    dd, v = heapq.heappop(heap)
                    if dd > dist.get(v, 1e18):
                        continue
                    for u, c, e in adj[v]:
                        nd = dd + c
                        if nd < dist.get(u, 1e18):
                            dist[u] = nd
                            prev[u] = (v, e)
                            heapq.heappush(heap, (nd, u))
                return dist, prev

            def cut_back(v, prev):
                nonlocal added
                while v in prev:
                    v, e = prev[v]
                    seam[e] = True
                    added += 1

            if not rims:  # a bead: slit between its two far ends
                v0 = next(iter(adj))
                d0, _p = spread_from([v0])
                a_ = max(d0, key=d0.get)
                d1, p1 = spread_from([a_])
                b_ = max(d1, key=d1.get)
                cut_back(b_, p1)
                tubes += 1
            elif len(rims) >= 2:  # a tube open at both ends: rim to rim
                d1, p1 = spread_from(rims[0])
                for other in rims[1:]:
                    cand = [v for v in other if v in d1]
                    if cand:
                        cut_back(min(cand, key=lambda v: d1[v]), p1)
                tubes += 1
            else:  # one rim: a sock if it is deep
                d1, p1 = spread_from(rims[0])
                if d1:
                    far = max(d1, key=d1.get)
                    rim_len = float(sum(elen[e] for e in rim))
                    if d1[far] > deep * rim_len:
                        cut_back(far, p1)
                        tubes += 1
        if not added:
            break
    me.edges.foreach_set("use_seam", seam)
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name, do_init=False)
    stage = _stage_enter([hair], name)
    edit = _edit_all

    islands = 0
    try:
        area3 = np.empty(nf, dtype=np.float32)
        me.polygons.foreach_get("area", area3)
        cut_out = 0
        unsolved = 0
        for attempt in range(4):
            me.edges.foreach_set("use_seam", seam)
            try:
                edit(lambda: bpy.ops.uv.unwrap(method=method, margin=0.001))
            except TypeError:  # a Blender without that method
                method = "ANGLE_BASED"
                edit(lambda: bpy.ops.uv.unwrap(method=method, margin=0.001))
            layer = me.uv_layers[name]
            uv = np.empty(len(me.loops) * 2, dtype=np.float32)
            layer.data.foreach_get("uv", uv)
            uv = uv.reshape(-1, 2).astype(np.float64)
            par = np.arange(nf)

            def find(x):
                while par[x] != x:
                    par[x] = par[par[x]]
                    x = par[x]
                return x

            for ei, fs in enumerate(efaces):
                if not seam[ei] and len(fs) == 2:
                    ra, rb = find(fs[0]), find(fs[1])
                    if ra != rb:
                        par[rb] = ra
            root = np.array([find(i) for i in range(nf)])
            root[strand < 0] = -1
            # islands the unwrap could not solve come out collapsed: those alone are unwrapped again the plain way
            _u, isl = np.unique(root, return_inverse=True)
            ua_i = np.bincount(isl, weights=_uv_area(uv, start, total))
            a3_i = np.bincount(isl, weights=area3.astype(np.float64))
            ratio = ua_i / np.maximum(a3_i, 1e-14)
            live = (a3_i > 1e-10) & (_u >= 0)
            if live.any() and method != "ANGLE_BASED":
                failed = live & ~(ratio > 0.02 * np.median(ratio[live]))
                if failed.any():
                    pick = failed[isl]
                    unsolved += int(failed.sum())
                    me.polygons.foreach_set("select", pick)
                    bpy.ops.object.mode_set(mode="EDIT")
                    bpy.ops.mesh.select_mode(type="FACE")
                    bpy.ops.uv.unwrap(method="ANGLE_BASED", margin=0.001)
                    bpy.ops.object.mode_set(mode="OBJECT")
                    layer = me.uv_layers[name]
                    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
                    layer.data.foreach_get("uv", uv)
                    uv = uv.reshape(-1, 2).astype(np.float64)
            if attempt == 3:
                break
            # faces the unwrap squashed (far less room in the UV than their neighbours of the same island get for
            # the same size of surface) are cut out, to become islands of their own at their true size
            dens = _uv_area(uv, start, total) / np.maximum(area3.astype(np.float64), 1e-14)
            real = area3 > 1e-10
            squashed = np.zeros(nf, dtype=bool)
            order = np.argsort(root, kind="stable")
            rs = root[order]
            cuts = np.nonzero(np.diff(rs))[0] + 1
            for grp in np.split(order, cuts):
                if root[grp[0]] < 0 or len(grp) < 2:
                    continue
                g = grp[real[grp]]
                if len(g) < 2:
                    continue
                # against the island's own average (surface-weighted): the median fails when most of it is squashed
                med = float((dens[g] * area3[g]).sum() / max(float(area3[g].sum()), 1e-14))
                squashed[g[dens[g] < squash * med]] = True
            tight = squashed.copy()
            if fold_cut:
                squashed |= _folded_faces(me, uv)  # and faces lying on top of others in the UV
            if not squashed.any():
                break
            alone = attempt == 2  # last try: each face still squashed on its own
            for ei, fs in enumerate(efaces):
                if (
                    not seam[ei]
                    and len(fs) == 2
                    and (squashed[fs[0]] != squashed[fs[1]] or (alone and tight[fs[0]] and tight[fs[1]]))
                ):
                    seam[ei] = True
            cut_out += int(squashed.sum())
        x_at = 0.0
        for r in np.unique(root[root >= 0]):
            faces = np.nonzero(root == r)[0]
            loops = np.concatenate([np.arange(start[f], start[f] + total[f]) for f in faces])
            q = uv[loops]
            ft = fpar[loops].astype(np.float64)
            ua = 0.0
            for f in faces:
                c = uv[start[f] : start[f] + total[f]]
                ua += abs(float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1]))) / 2
            a3 = float(area3[faces].sum())
            if ua < 1e-14 or a3 < 1e-12:
                uv[loops] = (x_at, 0.0)
                continue
            qc = (q - q.mean(axis=0)) * np.sqrt(a3 / ua)  # true size
            _u, sv, vt = np.linalg.svd(qc, full_matrices=False)
            ax = vt[0]
            if sv[0] < sv[1] * 1.3:  # not long: turn by where the wire runs
                g = (qc * (ft - ft.mean())[:, None]).sum(axis=0)
                ax = g / np.linalg.norm(g) if np.linalg.norm(g) > 1e-12 else ax
            if float(((qc @ ax) * (ft - ft.mean())).sum()) < 0:
                ax = -ax  # ax: from root to tip
            rot = np.array([[-ax[1], ax[0]], [-ax[0], -ax[1]]])  # root up, tip down
            qc = qc @ rot.T
            qc -= qc.min(axis=0)
            uv[loops] = qc + (x_at, 0.0)
            x_at += float(qc[:, 0].max()) + 0.01
            islands += 1
        layer.data.foreach_set("uv", uv.astype(np.float32).reshape(-1))
        me.update()
        me.edges.foreach_set("use_seam", seam)
        edit(lambda: _pack(margin))
    finally:
        _stage_exit(stage)
        me.edges.foreach_set("use_seam", seam0)
    return dict(
        strips=int(islands),
        strands=int(len(np.unique(strand[strand >= 0]))),
        tubes_cut=int(tubes),
        squashed_cut_out=int(cut_out),
        unsolved_islands=int(unsolved),
        seam_edges=int(seam.sum()),
        faces=int((strand >= 0).sum()),
    )


def uv_quality(me, name="LW_StrandUV"):
    """How good a UV map is: flipped faces, stretch (edge length in UV against 3D, per island it should be even)."""
    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
    me.uv_layers[name].data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2).astype(np.float64)
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lvi = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get("vertex_index", lvi)
    flipped = 0
    ratio = []
    zero = 0
    for p in me.polygons:
        ls = np.arange(p.loop_start, p.loop_start + p.loop_total)
        c = uv[ls]
        sa = float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1])) / 2
        if abs(sa) < 1e-12:
            zero += 1
            continue
        flipped += sa < 0
        l2 = np.linalg.norm(c - np.roll(c, -1, axis=0), axis=1)
        l3 = np.linalg.norm(co[lvi[ls]] - np.roll(co[lvi[ls]], -1, axis=0), axis=1)
        m = l3 > 1e-6
        ratio += list(l2[m] / l3[m])
    r = np.array(ratio)
    med = np.median(r) if len(r) else 1.0
    flipped = min(int(flipped), len(me.polygons) - zero - int(flipped))  # islands are all one way round
    return dict(
        faces=len(me.polygons),
        flipped=int(flipped),
        zero_area=int(zero),
        stretch_p05=float(np.percentile(r / med, 5)),
        stretch_p95=float(np.percentile(r / med, 95)),
        edges_within_20pct=float((np.abs(r / med - 1) < 0.2).mean()),
    )


def _uv_arrays(me, name):
    uv = np.empty(len(me.loops) * 2, dtype=np.float32)
    me.uv_layers[name].data.foreach_get("uv", uv)
    start = np.array([p.loop_start for p in me.polygons])
    total = np.array([p.loop_total for p in me.polygons])
    return uv.reshape(-1, 2).astype(np.float64), start, total


def _uv_area(uv, start, total):
    out = np.zeros(len(start))
    for f in range(len(start)):
        c = uv[start[f] : start[f] + total[f]]
        out[f] = abs(float(np.sum(c[:, 0] * np.roll(c[:, 1], -1) - np.roll(c[:, 0], -1) * c[:, 1]))) / 2
    return out


def uv_trouble(hair, name="LW_StrandUV", size=2048):
    """Faces of this hair that cannot carry a texture well in the strand UV: folded (on top of others) and squashed."""
    me = hair.data
    uv, start, total = _uv_arrays(me, name)
    folded = _folded_faces(me, uv, size)
    a3 = np.empty(len(me.polygons), dtype=np.float32)
    me.polygons.foreach_get("area", a3)
    dens = _uv_area(uv, start, total) / np.maximum(a3.astype(np.float64), 1e-14)
    real = a3 > 1e-10
    squashed = real & (dens < 0.1 * np.median(dens[real])) if real.any() else np.zeros(len(a3), dtype=bool)
    bad = folded | squashed
    tot = float(a3.sum())
    return dict(
        folded=int(folded.sum()),
        squashed=int(squashed.sum()),
        bad_area=float(a3[bad].sum()),
        area=tot,
        share=float(a3[bad].sum()) / tot if tot > 0 else 0.0,
    )  # share of the surface, not of the count


def strand_uv_auto(hair, wires_obj, name="LW_StrandUV", ok_share=0.01):
    """The strand UV, made the tidy way first; if too many faces fold or are squashed on this hair, made again with
    the folded parts cut out as islands of their own (more islands, no faces on top of each other). The better of
    the tries is kept. Returns the result of strand_uv2 plus what was tried."""
    tries = []
    best = None
    for label, kw in (
        ("tidy", dict(fold_cut=False)),
        ("cut folds", dict(fold_cut=True)),
        ("cut folds, angle", dict(fold_cut=True, method="ANGLE_BASED")),
    ):
        _tell(_tr("UV を展開中（%d 回目）") % (len(tries) + 1), 0.05 + 0.25 * len(tries))
        r = strand_uv2(hair, wires_obj, name=name, **kw)
        _tell(_tr("重なりとつぶれを調べ中"), 0.2 + 0.25 * len(tries))
        tr = uv_trouble(hair, name)
        tries.append(dict(way=label, islands=r["strips"], **tr))
        if best is None or tr["share"] < 0.7 * best[1]["share"]:  # more islands only for a real gain
            uv = np.empty(len(hair.data.loops) * 2, dtype=np.float32)
            hair.data.uv_layers[name].data.foreach_get("uv", uv)
            best = (r, tr, uv, label)
        if tr["share"] <= ok_share:
            break
    if best[3] != tries[-1]["way"]:
        hair.data.uv_layers[name].data.foreach_set("uv", best[2])
        hair.data.update()
    out = dict(best[0])
    out["tries"] = tries
    out["way"] = best[3]
    out.update(best[1])
    return out


PROGRESS = None  # set by the panel: a function (text, share 0-1) called at the slow steps


TRANSLATE = None  # set by the panel: gives a progress text in the language of the panel


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
    tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("loops", tl)
    tl = tl.reshape(-1, 3)
    tp = np.empty(len(me.loop_triangles), dtype=np.int32)
    me.loop_triangles.foreach_get("polygon_index", tp)
    C = uv[tl] * size
    owner = np.full((size, size), -1, dtype=np.int32)
    out = np.zeros(len(me.polygons), dtype=bool)
    den_all = (C[:, 1, 0] - C[:, 0, 0]) * (C[:, 2, 1] - C[:, 0, 1]) - (C[:, 2, 0] - C[:, 0, 0]) * (
        C[:, 1, 1] - C[:, 0, 1]
    )
    for ti in range(len(tl)):
        den = den_all[ti]
        if abs(den) < 1e-9:
            continue
        a_, b_, c_ = C[ti]
        x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))), 0)
        x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))), size - 1)
        y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))), 0)
        y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))), size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
        w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
        ins = (w1 > 0.02) & (w2 > 0.02) & (w1 + w2 < 0.98)
        if not ins.any():
            continue
        view = owner[y0 : y1 + 1, x0 : x1 + 1]
        old = view[ins]
        f = int(tp[ti])
        hit = old[(old >= 0) & (old != f)]
        if len(hit):
            out[f] = True
            out[np.unique(hit)] = True
        old[:] = f
        view[ins] = old
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
        me = h.data
        nf = len(me.polygons)
        hide0 = np.empty(nf, dtype=bool)
        me.polygons.foreach_get("hide", hide0)
        stage["hairs"].append(
            (
                h,
                me.uv_layers.active.name if me.uv_layers.active else None,
                next((l.name for l in me.uv_layers if l.active_render), None),
                h.hide_get(),
                h.hide_select,
                bool(hide0.any()),
            )
        )
        if hide0.any():
            me.polygons.foreach_set("hide", np.zeros(nf, dtype=bool))
            me.vertices.foreach_set("hide", np.zeros(len(me.vertices), dtype=bool))
            me.edges.foreach_set("hide", np.zeros(len(me.edges), dtype=bool))
        me.uv_layers.active = me.uv_layers[name]
        h.hide_set(False)
        h.hide_select = False
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
        h.hide_select = unsel
        h.hide_set(hid)
        if had:
            set_hidden(h, [int(x) for x in h.get("lw_hidden", [])])
    for o in view.objects:
        o.select_set(o in stage["selected"])
    view.objects.active = stage["active"]


def _edit_all(fn):
    """Runs fn in edit mode with every face of the selected objects selected."""
    import bpy

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="FACE")
    bpy.ops.mesh.select_all(action="SELECT")
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
    strand = face_strands(me).copy()
    miss = int((strand < 0).sum())
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
        todo = np.nonzero(strand < 0)[0]
        new = {}
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
        cen = np.empty(len(me.polygons) * 3, dtype=np.float32)
        me.polygons.foreach_get("center", cen)
        cen = cen.reshape(-1, 3)
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

    R = S.R
    gone = []
    for nm in (R.BIND_GROUP, R.GROUP, HIDE_GROUP):
        g = bpy.data.node_groups.get(nm)
        if g is not None and g.users == 0:
            bpy.data.node_groups.remove(g)
            gone.append(nm)
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
    for h in hairs:  # same texel density on every hair
        me = h.data
        uv, start, total = _uv_arrays(me, name)
        a3 = np.empty(len(me.polygons), dtype=np.float32)
        me.polygons.foreach_get("area", a3)
        s = np.abs(np.linalg.det(np.array(h.matrix_world.to_3x3()))) ** (2.0 / 3.0)
        ua = float(_uv_area(uv, start, total).sum())
        wa = float(a3.sum()) * s
        if ua > 1e-12 and wa > 1e-12:
            uv *= np.sqrt(wa / ua)
            me.uv_layers[name].data.foreach_set("uv", uv.astype(np.float32).reshape(-1))
            me.update()
    stage = _stage_enter(hairs, name)
    try:
        _edit_all(lambda: _pack(margin))
    finally:
        _stage_exit(stage)
    return len(hairs)


def uv_check(hairs, name="LW_StrandUV", size=2048, gap=2, max_trouble=0.02):
    """Is the strand UV fit to carry a texture made elsewhere? Everything inside 0-1, no island on top of
    another (drawn into a size x size picture: places covered twice), and at least `gap` pixels between islands."""
    ids = np.zeros((size, size), dtype=np.int32)
    twice = 0
    covered = 0
    lo = np.array([1e9, 1e9])
    hi = -lo
    base = 0
    n_isl = 0
    zero = 0
    faces = 0
    for h in hairs:
        me = h.data
        if name not in me.uv_layers:
            continue
        uv, start, total = _uv_arrays(me, name)
        nf = len(start)
        faces += nf
        lvi = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", lvi)
        lo = np.minimum(lo, uv.min(axis=0))
        hi = np.maximum(hi, uv.max(axis=0))
        par = np.arange(nf)
        seen = {}

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        q = np.round(uv * 1e5).astype(np.int64)
        for f in range(nf):
            for l in range(start[f], start[f] + total[f]):
                key = (int(lvi[l]), int(q[l, 0]), int(q[l, 1]))
                g = seen.get(key)
                if g is None:
                    seen[key] = f
                else:
                    ra, rb = find(g), find(f)
                    if ra != rb:
                        par[rb] = ra
        root = np.array([find(f) for f in range(nf)])
        uniq, isl = np.unique(root, return_inverse=True)
        n_isl += len(uniq)
        for f in range(nf):
            c = uv[start[f] : start[f] + total[f]] * size
            iid = base + int(isl[f]) + 1
            for k in range(1, len(c) - 1):
                a_, b_, c_ = c[0], c[k], c[k + 1]
                den = (b_[0] - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (b_[1] - a_[1])
                if abs(den) < 1e-9:
                    zero += 1
                    continue
                x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))), 0)
                x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))), size - 1)
                y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))), 0)
                y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))), size - 1)
                if x1 < x0 or y1 < y0:
                    continue
                xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
                w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
                ins = (w1 > 1e-4) & (w2 > 1e-4) & (w1 + w2 < 1 - 1e-4)
                if not ins.any():
                    continue
                view = ids[y0 : y1 + 1, x0 : x1 + 1]
                old = view[ins]
                twice += int(((old != 0) & (old != iid)).sum())
                covered += int((old == 0).sum())
                old[:] = iid
                view[ins] = old
        base += len(uniq)
    close = 0
    if gap > 0 and covered:
        for dy, dx in ((0, gap), (gap, 0), (gap, gap), (gap, -gap)):
            a = ids[max(dy, 0) :, max(dx, 0) : size + min(dx, 0)] if dx >= 0 else ids[dy:, : size + dx]
            b = ids[: size - dy, : size - dx] if dx >= 0 else ids[: size - dy, -dx:]
            close += int(((a != 0) & (b != 0) & (a != b)).sum())
    inside = bool(lo.min() >= -1e-6 and hi.max() <= 1 + 1e-6) if faces else False
    folded = 0
    squashed = 0
    bad_area = 0.0
    area = 0.0
    for h in hairs:
        if name not in h.data.uv_layers:
            continue
        tr = uv_trouble(h, name, size)
        folded += tr["folded"]
        squashed += tr["squashed"]
        bad_area += tr["bad_area"]
        area += tr["area"]
    trouble = bad_area / area if area > 0 else 0.0
    return dict(
        faces=int(faces),
        islands=int(n_isl),
        inside_0_1=inside,
        uv_min=[round(float(x), 4) for x in lo],
        uv_max=[round(float(x), 4) for x in hi],
        overlap_pixels=int(twice),
        too_close_pixels=int(close),
        filled=round(covered / float(size * size), 3),
        zero_triangles=int(zero),
        size=int(size),
        gap=int(gap),
        folded_faces=int(folded),
        squashed_faces=int(squashed),
        trouble_share=round(trouble, 4),
        ok=bool(inside and twice == 0 and close == 0 and trouble <= max_trouble),
    )

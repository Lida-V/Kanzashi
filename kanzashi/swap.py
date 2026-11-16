# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Export for texturing, and swapping the hair over to the strand UV (the current images are transferred) and back."""

import numpy as np

from .strand_uv import _tell, _tr, _uv_arrays


def export_for_texture(hairs, path, name="LW_StrandUV"):
    """One file to take to a texturing service: the hairs as they look now (bent), joined into one mesh with ONE
    UV map (the strand UV) and one plain material; no rig, no outline shell, no other UV maps. The scene's hairs
    are not changed: the mesh is built apart, exported and removed again. FBX or GLB by the file's ending."""
    import os

    import bpy

    from . import strands as S

    R = S.R
    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    V = []
    LV = []
    LS = []
    UV = []
    off_v = 0
    off_l = 0
    for h in hairs:
        me = h.data
        if name not in me.uv_layers:
            raise RuntimeError("%s has no strand UV yet" % h.name)
        keep = {m.name: m.show_viewport for m in h.modifiers}
        for m in h.modifiers:
            m.show_viewport = m.name == R.GROUP
        try:
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            ev = h.evaluated_get(dg).data
            if len(ev.vertices) != len(me.vertices):
                raise RuntimeError("%s: the bent mesh has another number of vertices" % h.name)
            co = np.empty(len(ev.vertices) * 3, dtype=np.float32)
            ev.vertices.foreach_get("co", co)
        finally:
            for m in h.modifiers:
                m.show_viewport = keep[m.name]
        co = co.reshape(-1, 3).astype(np.float64)
        M = np.array(h.matrix_world)
        V.append(co @ M[:3, :3].T + M[:3, 3])
        lvi = np.empty(len(me.loops), dtype=np.int32)
        me.loops.foreach_get("vertex_index", lvi)
        uv, start, _total = _uv_arrays(me, name)
        LV.append(lvi + off_v)
        LS.append(start + off_l)
        UV.append(uv)
        off_v += len(co)
        off_l += len(lvi)
    V = np.concatenate(V)
    LV = np.concatenate(LV)
    LS = np.concatenate(LS)
    UV = np.concatenate(UV)
    me2 = bpy.data.meshes.new("LidaHair_ForTexture")
    me2.vertices.add(len(V))
    me2.loops.add(len(LV))
    me2.polygons.add(len(LS))
    me2.vertices.foreach_set("co", V.astype(np.float32).reshape(-1))
    me2.loops.foreach_set("vertex_index", LV.astype(np.int32))
    me2.polygons.foreach_set("loop_start", LS.astype(np.int32))
    me2.update(calc_edges=True)
    me2.validate()
    lay = me2.uv_layers.new(name="UVMap", do_init=False)
    lay.data.foreach_set("uv", UV.astype(np.float32).reshape(-1))
    me2.polygons.foreach_set("use_smooth", np.ones(len(me2.polygons), dtype=bool))
    mat = bpy.data.materials.new("LidaHair_ForTexture")
    me2.materials.append(mat)
    ob = bpy.data.objects.new("LidaHair_ForTexture", me2)
    bpy.context.scene.collection.objects.link(ob)
    view = bpy.context.view_layer
    prev_active = view.objects.active
    prev_sel = [o for o in view.objects if o.select_get()]
    info = dict(vertices=len(V), faces=len(LS), same_faces=bool(len(me2.polygons) == len(LS)))
    try:
        for o in view.objects:
            o.select_set(o == ob)
        view.objects.active = ob
        if path.lower().endswith(".glb"):
            bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_format="GLB", export_animations=False)
        else:
            bpy.ops.export_scene.fbx(
                filepath=path,
                use_selection=True,
                object_types={"MESH"},
                bake_anim=False,
                add_leaf_bones=False,
                mesh_smooth_type="FACE",
                path_mode="AUTO",
            )
    finally:
        for o in view.objects:
            o.select_set(o in prev_sel)
        view.objects.active = prev_active
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me2)
        bpy.data.materials.remove(mat)
    info["bytes"] = os.path.getsize(path)
    info["path"] = path
    return info


# ---- the hair drawn with the strand UV: textures carried over, and back ------------------------------------------


SWAP_KEY = "lw_uv_before"


SWAP_TAG = "_LW"


def _transfer_map(hairs, width, height, dst="LW_StrandUV"):
    """For every texel of the strand UV: where the same spot of the hair lies in the UV the hair is drawn with now.
    Two pictures (u and v), NaN where no face is; then grown a few texels past the islands' edges."""
    _tell(_tr("写す位置を計算中"), 0.1)
    U = np.full((height, width), np.nan, dtype=np.float32)
    V = U.copy()
    scale = np.array([width, height], dtype=np.float64)
    for h in hairs:
        me = h.data
        src = next((l.name for l in me.uv_layers if l.active_render), me.uv_layers[0].name)
        new, start, total = _uv_arrays(me, dst)
        old, _s, _t = _uv_arrays(me, src)
        me.calc_loop_triangles()  # the same triangles the renderer draws
        tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("loops", tl)
        tl = tl.reshape(-1, 3)
        C = new[tl] * scale
        O = old[tl]
        den_all = (C[:, 1, 0] - C[:, 0, 0]) * (C[:, 2, 1] - C[:, 0, 1]) - (C[:, 2, 0] - C[:, 0, 0]) * (
            C[:, 1, 1] - C[:, 0, 1]
        )
        for ti in np.argsort(np.abs(den_all)):  # small ones first; a texel keeps its first owner
            den = den_all[ti]
            if abs(den) < 1e-9:
                continue
            a_, b_, c_ = C[ti]
            o = O[ti]
            x0 = max(int(np.floor(min(a_[0], b_[0], c_[0]))) - 1, 0)
            x1 = min(int(np.ceil(max(a_[0], b_[0], c_[0]))) + 1, width - 1)
            y0 = max(int(np.floor(min(a_[1], b_[1], c_[1]))) - 1, 0)
            y1 = min(int(np.ceil(max(a_[1], b_[1], c_[1]))) + 1, height - 1)
            if x1 < x0 or y1 < y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w1 = ((xs - a_[0]) * (c_[1] - a_[1]) - (c_[0] - a_[0]) * (ys - a_[1])) / den
            w2 = ((b_[0] - a_[0]) * (ys - a_[1]) - (xs - a_[0]) * (b_[1] - a_[1])) / den
            w0 = 1.0 - w1 - w2
            view_u = U[y0 : y1 + 1, x0 : x1 + 1]
            view_v = V[y0 : y1 + 1, x0 : x1 + 1]
            ins = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) & np.isnan(view_u)
            if not ins.any():
                continue
            view_u[ins] = (w0 * o[0, 0] + w1 * o[1, 0] + w2 * o[2, 0])[ins]
            view_v[ins] = (w0 * o[0, 1] + w1 * o[1, 1] + w2 * o[2, 1])[ins]
        for f in range(len(start)):  # faces smaller than a texel: the texel under them
            cx, cy = (new[start[f] : start[f] + total[f]] * scale).mean(axis=0)
            ix, iy = int(cx), int(cy)
            if 0 <= ix < width and 0 <= iy < height and np.isnan(U[iy, ix]):
                U[iy, ix], V[iy, ix] = old[start[f] : start[f] + total[f]].mean(axis=0)
    inside = ~np.isnan(U)
    for _grow in range(8):  # past the edges, so that no seam shows
        miss = np.isnan(U)
        if not miss.any():
            break
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            su = np.roll(U, (dy, dx), axis=(0, 1))
            sv = np.roll(V, (dy, dx), axis=(0, 1))
            take = np.isnan(U) & miss & ~np.isnan(su)
            U[take] = su[take]
            V[take] = sv[take]
    return U, V, inside


def _resample(src, U, V):
    """src: (h, w, 4) picture; returns the picture seen through the map (bilinear, repeating)."""
    h, w = src.shape[:2]
    ok = ~np.isnan(U)
    x = np.where(ok, U, 0.0).astype(np.float64) * w - 0.5
    y = np.where(ok, V, 0.0).astype(np.float64) * h - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    x1 = (x0 + 1) % w
    y1 = (y0 + 1) % h
    x0 %= w
    y0 %= h
    out = (src[y0, x0] * (1 - fx) + src[y0, x1] * fx) * (1 - fy) + (src[y1, x0] * (1 - fx) + src[y1, x1] * fx) * fy
    if ok.any():
        fill = out[ok].mean(axis=0)
        fill[3] = 1.0
        out[~ok] = fill
    return out.astype(np.float32)


def _reads_uv(node, depth=0):
    """Does this image node take its place from the UV map (nothing plugged in, or a UV output, also through a
    Mapping node)?"""
    sock = node.inputs.get("Vector")
    if sock is None or not sock.is_linked:
        return True
    src = sock.links[0].from_node
    out = sock.links[0].from_socket
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
    import json

    import bpy

    hairs = [h for h in hairs if name in h.data.uv_layers and not h.get(SWAP_KEY)]
    if not hairs:
        return dict(hairs=0, images=0, skipped=[])
    maps = {}
    made = {}
    skipped = []
    mats = {}
    befores = {}
    for h in hairs:
        me = h.data
        before = dict(
            render=next((l.name for l in me.uv_layers if l.active_render), None),
            active=me.uv_layers.active.name if me.uv_layers.active else None,
            materials=[m.name if m else "" for m in me.materials],
        )
        for i, m in enumerate(me.materials):
            if m is None or not m.use_nodes:
                continue
            if m.name not in mats:
                c = m.copy()
                c.name = m.name + SWAP_TAG
                mats[m.name] = c
                for nd in c.node_tree.nodes:
                    if nd.type == "UVMAP" and nd.uv_map in ("", before["render"]):
                        nd.uv_map = name
                    if nd.type != "TEX_IMAGE" or nd.image is None or not _reads_uv(nd):
                        continue  # matcaps and the like do not go by the UV
                    img = nd.image
                    if img.name not in made:
                        w, hh = img.size[0], img.size[1]
                        if w == 0 or hh == 0 or len(img.pixels) != w * hh * 4:
                            skipped.append(img.name)
                            made[img.name] = None
                        else:
                            ow, oh = min(w, max_size), min(hh, max_size)
                            if (ow, oh) not in maps:
                                maps[(ow, oh)] = _transfer_map(hairs, ow, oh, name)
                            _tell(_tr("画像を写し中：%s") % img.name[:14], 0.2 + 0.1 * min(len(made), 6))
                            px = np.empty(w * hh * 4, dtype=np.float32)
                            img.pixels.foreach_get(px)
                            out = _resample(px.reshape(hh, w, 4), maps[(ow, oh)][0], maps[(ow, oh)][1])
                            ni = bpy.data.images.new(img.name + SWAP_TAG, ow, oh, alpha=True, float_buffer=img.is_float)
                            ni.colorspace_settings.name = img.colorspace_settings.name
                            ni.alpha_mode = img.alpha_mode
                            ni.pixels.foreach_set(out.reshape(-1))
                            ni.update()
                            ni.pack()
                            made[img.name] = ni
                    if made[img.name] is not None:
                        nd.image = made[img.name]
            me.materials[i] = mats[m.name]
        h[SWAP_KEY] = json.dumps(before)
        befores[h.name] = before["render"]
        me.uv_layers[name].active_render = True
        me.uv_layers.active = me.uv_layers[name]
        me.update()
    _tell(_tr("色の答え合わせ中"), 0.9)
    return dict(
        hairs=len(hairs),
        images=len([x for x in made.values() if x is not None]),
        skipped=sorted(set(skipped)),
        materials=len(mats),
        **_swap_answer(hairs, made, befores, name),
    )


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
        w, hh = im.size
        px = np.empty(w * hh * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(hh, w, 4)

    src = load(src_img)
    dst = load(dst_img)

    def samp(im, uv):
        hh, w = im.shape[:2]
        return im[
            np.clip((uv[:, 1] % 1.0 * hh).astype(int), 0, hh - 1),
            np.clip((uv[:, 0] % 1.0 * w).astype(int), 0, w - 1),
            :3,
        ]

    n = 0
    bad = 0
    for h in hairs:
        me = h.data
        new, _s, _t = _uv_arrays(me, name)
        old, _s, _t = _uv_arrays(me, befores[h.name])
        me.calc_loop_triangles()
        tl = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("loops", tl)
        tl = tl.reshape(-1, 3)
        co = samp(src, old[tl].mean(axis=1))
        cn = samp(dst, new[tl].mean(axis=1))
        even = (np.abs(samp(src, old[tl][:, 0]) - samp(src, old[tl][:, 1])).max(axis=1) <= limit) & (
            np.abs(samp(src, old[tl][:, 1]) - samp(src, old[tl][:, 2])).max(axis=1) <= limit
        )
        n += int(even.sum())
        bad += int((even & (np.abs(co - cn).max(axis=1) > limit)).sum())
    return dict(triangles=n, differ=bad)


def revert_uv(hairs):
    """Back to how the hairs were drawn before swap_uv; the copies made for the strand UV are removed if nothing uses them."""
    import json

    import bpy

    done = 0
    for h in hairs:
        raw = h.get(SWAP_KEY)
        if not raw:
            continue
        before = json.loads(raw)
        me = h.data
        for i, nm in enumerate(before["materials"]):
            if i < len(me.materials) and nm and nm in bpy.data.materials:
                me.materials[i] = bpy.data.materials[nm]
        if before["render"] in me.uv_layers:
            me.uv_layers[before["render"]].active_render = True
        if before["active"] in me.uv_layers:
            me.uv_layers.active = me.uv_layers[before["active"]]
        del h[SWAP_KEY]
        me.update()
        done += 1
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
            me.uv_layers.remove(me.uv_layers[nm])
            gone.append("%s/%s" % (h.name, nm))
        me.uv_layers[name].active_render = True
        me.uv_layers.active = me.uv_layers[name]
        del h[SWAP_KEY]
        h["lw_uv_only"] = 1
        me.update()
    return gone

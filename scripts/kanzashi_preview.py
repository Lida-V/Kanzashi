# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Pictures of the hair in its strand colours, for checking a detection without opening Blender.

    blender -b model_kanzashi.blend --python kanzashi_preview.py -- --out-dir preview

Writes strands_front.png, strands_back.png, strands_left.png, strands_right.png (one flat colour per strand, the
hair only), strands_uv.png when the strand UV exists (the islands in the same colours), and preview.json.
The opened file is never saved. --out-dir must be empty or not exist yet."""

import argparse
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

VIEWS = (("front", (0, -1, 0)), ("back", (0, 1, 0)), ("left", (1, 0, 0)), ("right", (-1, 0, 0)))


def fail(msg):
    print("KANZASHI " + json.dumps(dict(ok=False, error=msg), ensure_ascii=False))
    sys.exit(1)


def detected_hairs(names):
    obs = (
        [bpy.data.objects[n] for n in names if n in bpy.data.objects] if names else list(bpy.context.view_layer.objects)
    )
    return [o for o in obs if o.type == "MESH" and "lw_strand_col" in o.data.color_attributes]


def world_points(depsgraph, hairs):
    pts = []
    for h in hairs:
        ev = h.evaluated_get(depsgraph)
        me = ev.data
        co = np.empty(len(me.vertices) * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        M = np.array(ev.matrix_world)
        pts.append(co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3])
    return np.concatenate(pts)


def uv_picture(hairs, path, size):
    """The islands of the strand UV, each in the colour of its strand."""
    img = np.full((size, size, 4), (0.12, 0.12, 0.12, 1.0), dtype=np.float32)
    n = 0
    for h in hairs:
        me = h.data
        if "LW_StrandUV" not in me.uv_layers:
            continue
        uv = np.empty(len(me.loops) * 2, dtype=np.float32)
        me.uv_layers["LW_StrandUV"].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        col = np.empty(len(me.loops) * 4, dtype=np.float32)
        me.color_attributes["lw_strand_col"].data.foreach_get("color", col)
        col = col.reshape(-1, 4)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("loops", tri)
        for a, b, c in tri.reshape(-1, 3):
            p = uv[[a, b, c]] * (size - 1)
            lo = np.floor(p.min(0)).astype(int).clip(0, size - 1)
            hi = np.ceil(p.max(0)).astype(int).clip(0, size - 1)
            xs, ys = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
            d = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
            if abs(d) < 1e-9:
                continue
            w0 = ((p[1, 1] - p[2, 1]) * (xs - p[2, 0]) + (p[2, 0] - p[1, 0]) * (ys - p[2, 1])) / d
            w1 = ((p[2, 1] - p[0, 1]) * (xs - p[2, 0]) + (p[0, 0] - p[2, 0]) * (ys - p[2, 1])) / d
            inside = (w0 >= -0.01) & (w1 >= -0.01) & (w0 + w1 <= 1.01)
            img[ys[inside], xs[inside], :3] = np.clip(col[a, :3], 0.0, 1.0) ** (1 / 2.2)  # as the viewport shows it
        n += 1
    if not n:
        return False
    out = bpy.data.images.new("kanzashi_uv_preview", size, size, alpha=False)
    out.pixels.foreach_set(img.ravel())
    out.filepath_raw = path
    out.file_format = "PNG"
    out.save()
    bpy.data.images.remove(out)
    return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="kanzashi_preview.py")
    ap.add_argument("--out-dir", required=True, help="folder for the pictures (empty or new)")
    ap.add_argument("--hair", action="append", default=[], help="name of a hair mesh (repeat); default: all detected")
    ap.add_argument("--size", type=int, default=1200, help="longer side of the pictures in pixels")
    a = ap.parse_args(argv)
    out_dir = os.path.abspath(a.out_dir)
    if os.path.isdir(out_dir) and os.listdir(out_dir):
        fail("the folder is not empty (nothing is overwritten): %s" % out_dir)
    hairs = detected_hairs(a.hair)
    if not hairs:
        fail("no detected hair in this file (run kanzashi_run.py first)")
    os.makedirs(out_dir, exist_ok=True)
    sc = bpy.context.scene
    for o in bpy.data.objects:  # the hair only (this file is not saved)
        o.hide_render = o not in hairs
    for h in hairs:
        h.hide_set(False)
        h.data.color_attributes.active_color = h.data.color_attributes["lw_strand_col"]
        h.data.color_attributes.render_color_index = list(h.data.color_attributes).index(
            h.data.color_attributes["lw_strand_col"]
        )
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading
    sh.light = "FLAT"
    sh.color_type = "VERTEX"
    sh.show_object_outline = True
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new("kanzashi_preview")
    sc.world.color = (0.12, 0.12, 0.12)
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "PNG"
    P = world_points(bpy.context.evaluated_depsgraph_get(), hairs)
    lo, hi = P.min(0), P.max(0)
    centre = (lo + hi) / 2
    cam_data = bpy.data.cameras.new("kanzashi_preview")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("kanzashi_preview", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    files = []
    for name, d in VIEWS:
        d = Vector(d)
        width = (hi[1] - lo[1]) if abs(d.x) > 0.5 else (hi[0] - lo[0])
        height = hi[2] - lo[2]
        margin = 1.08
        if height >= width:
            sc.render.resolution_y = a.size
            sc.render.resolution_x = max(int(a.size * max(width / height, 0.3)), 64)
        else:
            sc.render.resolution_x = a.size
            sc.render.resolution_y = max(int(a.size * height / width), 64)
        cam_data.ortho_scale = max(width, height) * margin
        cam.location = Vector(centre) - d * 10.0
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cam_data.clip_end = 100.0
        path = os.path.join(out_dir, "strands_%s.png" % name)
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        files.append(path)
    uv_path = os.path.join(out_dir, "strands_uv.png")
    if uv_picture(hairs, uv_path, 1024):
        files.append(uv_path)
    rep = dict(ok=True, hairs=[h.name for h in hairs], files=files)
    json.dump(rep, open(os.path.join(out_dir, "preview.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("KANZASHI " + json.dumps(rep, ensure_ascii=True))


if __name__ == "__main__":
    main()

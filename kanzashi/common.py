# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""What the operators and the panel share: which meshes are hair, the registered list, the ways the viewport is set up
for each step, picking and painting faces under the mouse, and the handles for bending."""

import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import kdtree

from . import edit as ED
from . import i18n as LANG
from . import strand_uv as UV
from . import strands as S
from . import tree as TR

T = LANG.T


UV.TRANSLATE = T  # the progress texts of the slow steps


R = S.R


TOOL = "kanzashi.face_tool"


WORDS = ("hair", "bangs", "braid", "ponytail", "sidelock", "ahoge", "髪", "前髪", "毛")


NOT_WORDS = ("flower", "acc_", "pin", "ribbon", "tiara", "outline", "hairband", "chain", "飾")


def looks_like_hair(ob):
    """A mesh whose name says hair, or most of whose faces use a material whose name says hair."""
    if ob.type != "MESH" or len(ob.data.polygons) == 0:
        return False
    name = ob.name.lower()
    if any(w in name for w in NOT_WORDS):
        return False
    if any(w in name for w in WORDS):
        return True
    slots = {
        i for i, s in enumerate(ob.material_slots) if s.material and any(w in s.material.name.lower() for w in WORDS)
    }
    if not slots:
        return False
    mi = np.empty(len(ob.data.polygons), dtype=np.int32)
    ob.data.polygons.foreach_get("material_index", mi)
    return float(np.isin(mi, list(slots)).mean()) >= 0.6


def registered(context):
    return [it.obj for it in context.scene.lida_hs_list if it.obj is not None and it.obj.type == "MESH"]


def _add(context, ob):
    if ob is None or ob.type != "MESH" or ob in registered(context):
        return False
    context.scene.lida_hs_list.add().obj = ob
    return True


def _detected(hair):
    return hair is not None and "lw_strand" in hair.data.attributes


def _current(context):
    sc = context.scene
    hs = registered(context)
    if sc.lida_hs_hair in hs:
        return sc.lida_hs_hair
    if context.active_object in hs:
        return context.active_object
    det = [h for h in hs if _detected(h)]
    return det[0] if det else (hs[0] if hs else None)


def _wires(context, hair):
    name = hair.get("lw_wires") or ("LS_Wires_" + hair.name)
    hair["lw_wires"] = name
    return R.ensure_wires(name, context.scene.collection)


def only_hair(context, on):
    """Hides everything that is not a registered hair or one of its wires; `on=False` brings it back."""
    sc = context.scene
    if on:
        keep = set(registered(context))
        keep |= {bpy.data.objects.get(h.get("lw_wires", "")) for h in keep}
        hidden = list(sc.get("lida_hs_hidden", []))
        for o in context.view_layer.objects:
            if o not in keep and not o.hide_get():
                o.hide_set(True)
                hidden.append(o.name)
        for o in keep:
            if o is not None and o.hide_get():
                o.hide_set(False)
        sc["lida_hs_hidden"] = hidden
    else:
        for nm in sc.get("lida_hs_hidden", []):
            o = bpy.data.objects.get(nm)
            if o is not None and o.name in context.view_layer.objects:
                o.hide_set(False)
        sc["lida_hs_hidden"] = []
    return len(sc["lida_hs_hidden"])


def work_view(context, on):
    """While colours are fixed: Blender's own brush circle is off (ours is drawn instead) and outline shells of
    the hair are not shown (their lines stay when faces are hidden). `on=False` puts both back."""
    sc = context.scene
    vp = context.tool_settings.vertex_paint
    if on:
        off = []
        for h in registered(context):
            for m in h.modifiers:
                if m.type == "SOLIDIFY" and m.show_viewport:
                    m.show_viewport = False
                    off.append("%s|%s" % (h.name, m.name))
        sc["lida_hs_mods"] = list(sc.get("lida_hs_mods", [])) + off
        if vp is not None and vp.show_brush:
            vp.show_brush = False
            sc["lida_hs_brush"] = 1
    else:
        for key in sc.get("lida_hs_mods", []):
            hn, mn = key.split("|", 1)
            h = bpy.data.objects.get(hn)
            if h is not None and mn in h.modifiers:
                h.modifiers[mn].show_viewport = True
        sc["lida_hs_mods"] = []
        if vp is not None and sc.get("lida_hs_brush"):
            vp.show_brush = True
            sc["lida_hs_brush"] = 0


def flat_colour_view(context):
    sc = context.scene
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            sh = area.spaces.active.shading
            if not (sh.type == "SOLID" and sh.color_type == "VERTEX" and sh.light == "FLAT") and not sc.get(
                "lida_hs_shading"
            ):
                sc["lida_hs_shading"] = [sh.type, sh.color_type, sh.light]  # how the view was before the tool
            sh.type = "SOLID"
            sh.color_type = "VERTEX"
            sh.light = "FLAT"


def normal_view(context):
    """The 3D views back to how they were before the tool (if that is not known: Blender's usual solid view)."""
    sc = context.scene
    was = list(sc.get("lida_hs_shading", [])) or ["SOLID", "MATERIAL", "STUDIO"]
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            sh = area.spaces.active.shading
            if sh.type == "SOLID" and sh.color_type == "VERTEX" and sh.light == "FLAT":
                try:
                    sh.type = was[0]
                    sh.color_type = was[1]
                    sh.light = was[2]
                except Exception:
                    sh.type = "SOLID"
                    sh.color_type = "MATERIAL"
                    sh.light = "STUDIO"
    if "lida_hs_shading" in sc:
        del sc["lida_hs_shading"]


_syncing = [False]


def sync_list(context, hair=None):
    """The list of colours in the panel: one row per wire of the current hair."""
    sc = context.scene
    hair = hair or _current(context)
    _syncing[0] = True
    try:
        sc.lida_hs_wires.clear()
        if not _detected(hair):
            return
        hidden = {int(x) for x in hair.get("lw_hidden", [])}
        for k, faces, kind in ED.wire_table(hair, _wires(context, hair)):
            it = sc.lida_hs_wires.add()
            it.wire = k
            it.faces = faces
            it.kind = kind
            it.hidden = k in hidden
            it.color = tuple(float(x) for x in TR.PAL[k])
        cur = int(hair.get("lw_current", -1))
        sc.lida_hs_wire_index = cur if 0 <= cur < len(sc.lida_hs_wires) else -1
    finally:
        _syncing[0] = False


def set_current(context, hair, k):
    hair["lw_current"] = int(k)
    got = [int(x) for x in hair.get("lw_picked", [])]
    if int(k) not in got:
        hair["lw_picked"] = got + [int(k)]
    context.scene.lida_hs_hair = hair
    _syncing[0] = True
    try:
        if 0 <= k < len(context.scene.lida_hs_wires):
            context.scene.lida_hs_wire_index = int(k)
    finally:
        _syncing[0] = False


def _row_picked(self, context):
    if _syncing[0]:
        return
    hair = _current(context)
    k = context.scene.lida_hs_wire_index
    if _detected(hair) and k >= 0:
        set_current(context, hair, k)
        context.scene.lida_hs_mode = "PAINT"
        if bending(context) and context.mode == "OBJECT" and k != int(context.scene.get("lida_hs_bend_wire", -1)):
            start_bend(context, hair, k)


def enter_paint(context, hair):
    """Shows `hair` with its wire colours as they are and switches to the face tool."""
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for o in context.view_layer.objects:
        o.select_set(o == hair)
    context.view_layer.objects.active = hair
    ca = hair.data.color_attributes.get("lw_strand_col")
    if ca is None:
        return False
    hair.data.color_attributes.active_color = ca
    if ED.HIDE_GROUP in hair.modifiers:
        ED.hide_modifier(hair, False)
    bpy.ops.object.mode_set(mode="VERTEX_PAINT")
    flat_colour_view(context)
    context.scene.lida_hs_hair = hair
    try:
        bpy.ops.wm.tool_set_by_id(name=TOOL)
    except Exception:
        pass
    sync_list(context, hair)
    return True


def cast(context, hair, origin, direction):
    """First face of `hair` along the ray that is not hidden. Returns (local point, face index, distance) or None."""
    mwi = hair.matrix_world.inverted()
    dg = context.evaluated_depsgraph_get()
    o = mwi @ origin
    d = (mwi.to_3x3() @ direction).normalized()
    me = hair.data
    for _ in range(40):
        ok, loc, _nrm, index = hair.ray_cast(o, d, depsgraph=dg)
        if not ok:
            return None
        # faces made by modifiers (an outline shell) and hidden faces are passed through
        if 0 <= index < len(me.polygons) and not me.polygons[index].hide:
            return loc, index, ((hair.matrix_world @ loc) - origin).length
        o = loc + d * 1e-5
    return None


def pick_ray(context, origin, direction):
    """Eyedropper: the nearest face of a registered, detected hair. Returns (hair, wire id) or (None, -1)."""
    best = None
    for hair in registered(context):
        if _detected(hair) and hair.visible_get():
            hit = cast(context, hair, origin, direction)
            if hit is not None and (best is None or hit[2] < best[0]):
                best = (hit[2], hair, hit[1])
    if best is None:
        return None, -1
    _d, hair, index = best
    k = int(ED.face_strands(hair.data)[index])
    if k < 0:
        return None, -1
    set_current(context, hair, k)
    return hair, k


def pick_shown(context, origin, direction):
    """Like pick_ray, for Object Mode: what is hit is the mesh as shown (hidden colours left out, outline shell
    included), so the wire is read from the shown mesh itself."""
    dg = context.evaluated_depsgraph_get()
    best = None
    for hair in registered(context):
        if not _detected(hair) or not hair.visible_get():
            continue
        mwi = hair.matrix_world.inverted()
        ok, loc, _nrm, index = hair.ray_cast(mwi @ origin, (mwi.to_3x3() @ direction).normalized(), depsgraph=dg)
        if ok:
            dist = ((hair.matrix_world @ loc) - origin).length
            if best is None or dist < best[0]:
                best = (dist, hair, index)
    if best is None:
        return None, -1
    _d, hair, index = best
    at = hair.evaluated_get(dg).data.attributes.get("lw_strand")
    if at is None or at.domain != "FACE" or not (0 <= index < len(at.data)):
        return None, -1
    k = int(at.data[index].value)
    if k < 0:
        return None, -1
    set_current(context, hair, k)
    return hair, k


_trees = {}


def _draw_cursor(xy):
    """Drawn at the mouse while "fix colours" is on: a ring the size of the brush in the colour in hand
    (brush), a small ring (eyedropper) or a double ring (show two colours)."""
    try:
        import math

        import gpu
        from gpu_extras.batch import batch_for_shader

        context = bpy.context
        sc = context.scene
        if not getattr(sc, "lida_hs_on", False) or context.mode != "PAINT_VERTEX":
            return
        area = context.area
        region = context.region
        if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW":
            return
        rv3d = area.spaces.active.region_3d
        hair = _current(context)
        k = int(hair.get("lw_current", -1)) if hair is not None else -1
        mode = sc.lida_hs_mode
        if mode == "PAINT":
            c = rv3d.view_location
            right = rv3d.view_rotation @ __import__("mathutils").Vector((1.0, 0.0, 0.0))
            try:  # as large as it is on the hair under the mouse
                co = (xy[0] - region.x, xy[1] - region.y)
                o = view3d_utils.region_2d_to_origin_3d(region, rv3d, co)
                dv = view3d_utils.region_2d_to_vector_3d(region, rv3d, co)
                hit = cast(context, hair, o, dv) if _detected(hair) else None
                if hit is not None:
                    c = hair.matrix_world @ hit[0]
            except Exception:
                pass
            a2 = view3d_utils.location_3d_to_region_2d(region, rv3d, c)
            b2 = view3d_utils.location_3d_to_region_2d(region, rv3d, c + right * sc.lida_hs_radius)
            rad = max((b2 - a2).length, 3.0) if a2 is not None and b2 is not None else 10.0
        else:
            rad = 7.0
        col = tuple(float(x) for x in TR.to_srgb(TR.PAL[k])) + (1.0,) if k >= 0 else (1.0, 1.0, 1.0, 1.0)
        x, y = xy
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        gpu.state.blend_set("ALPHA")

        def ring(r, colour, width):
            pts = [(x + r * math.cos(i * math.tau / 48), y + r * math.sin(i * math.tau / 48)) for i in range(49)]
            gpu.state.line_width_set(width)
            shader.bind()
            shader.uniform_float("color", colour)
            batch_for_shader(shader, "LINE_STRIP", {"pos": pts}).draw(shader)

        ring(rad, (0.0, 0.0, 0.0, 0.9), 4.0)
        ring(rad, col if mode != "PICK" else (1.0, 1.0, 1.0, 1.0), 2.0)
        if mode == "FOCUS":
            ring(rad + 5.0, (1.0, 1.0, 1.0, 1.0), 1.5)
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")
    except Exception:
        pass


def paint_ray(context, hair, origin, direction, radius):
    """Gives every face within `radius` of the point under the ray the colour of the current wire (whole faces,
    one flat colour; faces turned away and hidden faces are left alone). Returns faces painted."""
    k = int(hair.get("lw_current", -1))
    if k < 0:
        return 0
    hit = cast(context, hair, origin, direction)
    if hit is None:
        return 0
    me = hair.data
    key = (hair.name, len(me.polygons))
    nf = len(me.polygons)
    if key not in _trees:
        # where the faces are on screen: after the armature and the wires (the first faces of the evaluated
        # mesh are the mesh's own faces, in the same order)
        ev = hair.evaluated_get(context.evaluated_depsgraph_get()).data
        src = ev if len(ev.polygons) >= nf else me
        kd = kdtree.KDTree(nf)
        nrm = []
        for i in range(nf):
            p = src.polygons[i]
            kd.insert(p.center, i)
            nrm.append(p.normal.copy())
        kd.balance()
        _trees.clear()
        _trees[key] = (kd, nrm)
    kd, nrm = _trees[key]
    d = (hair.matrix_world.inverted().to_3x3() @ direction).normalized()
    scale = max(hair.matrix_world.to_scale())
    ca = me.color_attributes["lw_strand_col"]
    rgb = tuple(float(x) for x in TR.PAL[k]) + (1.0,)
    faces = {hit[1]} | {i for _co, i, _dist in kd.find_range(hit[0], radius / max(scale, 1e-9))}
    n = 0
    for fi in faces:
        p = me.polygons[fi]
        if p.hide or (fi != hit[1] and nrm[fi].dot(d) > 0.2):
            continue
        for li in range(p.loop_start, p.loop_start + p.loop_total):
            ca.data[li].color = rgb
        n += 1
    me.update()
    return n


def apply_hair(context, hair):
    """Moves the painted faces to their wires (works in any mode) and refreshes the list."""
    r = ED.apply_repaint(hair, _wires(context, hair))
    hidden = [int(x) for x in hair.get("lw_hidden", [])]
    if hidden:
        ED.set_hidden(hair, hidden)
    _trees.clear()
    sync_list(context, hair)
    return r


def _view_ray(context, event):
    region = context.region
    rv3d = context.region_data
    if region is None or rv3d is None:
        return None
    co = (event.mouse_region_x, event.mouse_region_y)
    return view3d_utils.region_2d_to_origin_3d(region, rv3d, co), view3d_utils.region_2d_to_vector_3d(region, rv3d, co)


def _picked_to_add(self, context):
    ob = context.scene.lida_hs_pick_add
    if ob is not None:
        if _add(context, ob) and context.scene.get("lida_hs_hidden"):
            only_hair(context, True)
        context.scene.lida_hs_pick_add = None


def _grips(context):
    return [bpy.data.objects[nm] for nm in context.scene.get("lida_hs_grips", []) if nm in bpy.data.objects]


def end_bend(context):
    """Writes where the grips are into the wire and removes the grips."""
    sc = context.scene
    hair = bpy.data.objects.get(sc.get("lida_hs_bend_hair", ""))
    k = int(sc.get("lida_hs_bend_wire", -1))
    grips = _grips(context)
    if hair is not None and grips and k >= 0:
        w = _wires(context, hair)
        inv = w.matrix_world.inverted()
        moves = {}  # grip number -> what its hook does to the three points it holds (wire space)
        for i, g in enumerate(grips):
            md = w.modifiers.get("lida_grip_%02d" % i)
            if md is not None:
                moves[i] = inv @ g.matrix_world @ md.matrix_inverse
        for m in [m for m in w.modifiers if m.name.startswith("lida_grip")]:
            w.modifiers.remove(m)
        if k < len(w.data.splines):
            sp = w.data.splines[k]
            for i, (g, bp) in enumerate(zip(grips, sp.bezier_points)):
                m = moves.get(i)
                r = m.to_3x3() if m is not None else None
                turned = (
                    r is not None
                    and max(abs(r[a][b] - (1.0 if a == b else 0.0)) for a in range(3) for b in range(3)) > 1e-4
                )
                if turned or (m is not None and bp.handle_left_type != "AUTO"):
                    # a grip that was turned (now or earlier): its handles keep the direction it was given
                    co, hl, hr = m @ bp.co, m @ bp.handle_left, m @ bp.handle_right
                    bp.handle_left_type = bp.handle_right_type = "ALIGNED"
                    bp.co, bp.handle_left, bp.handle_right = co, hl, hr
                else:  # only moved: smooth handles for the new position
                    bp.co = inv @ g.matrix_world.translation
                    bp.handle_left_type = bp.handle_right_type = "AUTO"
        w.data.update_tag()
        w.hide_select = False
        if ED.HIDE_GROUP in hair.modifiers and not sc.get("lida_hs_bend_switch"):
            ED.hide_modifier(hair, False)
        hair.hide_select = bool(sc.get("lida_hs_bend_sel", 0))
    for g in grips:
        bpy.data.objects.remove(g, do_unlink=True)
    sc["lida_hs_grips"] = []
    sc["lida_hs_bend_wire"] = -1
    return hair


def start_bend(context, hair, k):
    """Puts round grips on wire k of `hair` (grips of another wire are written back first). Returns grips made."""
    sc = context.scene
    sc["lida_hs_bend_switch"] = 1
    try:
        end_bend(context)
    finally:
        sc["lida_hs_bend_switch"] = 0
    for h in registered(context):  # only the hair being bent leaves its hidden colours out
        if h != hair and ED.HIDE_GROUP in h.modifiers:
            ED.hide_modifier(h, False)
    w = _wires(context, hair)
    if not (0 <= k < len(w.data.splines)):
        return 0
    w.hide_set(False)
    w.show_in_front = True
    sp = w.data.splines[k]
    first = sum(len(s.bezier_points) * 3 for s in list(w.data.splines)[:k])
    co = np.empty(len(hair.data.vertices) * 3, dtype=np.float32)
    hair.data.vertices.foreach_get("co", co)
    size = float(
        np.clip(np.ptp(co.reshape(-1, 3), axis=0).max() * max(hair.matrix_world.to_scale()) * 0.03, 0.010, 0.04)
    )
    col = tuple(float(x) for x in TR.to_srgb(TR.PAL[k])) + (1.0,)
    names = []
    for i, bp in enumerate(sp.bezier_points):
        g = bpy.data.objects.new("LS_Grip_%02d" % i, None)
        g.empty_display_type = "SPHERE"
        g.empty_display_size = size
        g.show_in_front = True
        g.color = col
        g.matrix_world.translation = w.matrix_world @ bp.co
        context.scene.collection.objects.link(g)
        names.append(g.name)
    context.view_layer.update()
    for i, nm in enumerate(names):
        g = bpy.data.objects[nm]
        md = w.modifiers.new("lida_grip_%02d" % i, "HOOK")
        md.object = g
        md.vertex_indices_set([first + i * 3, first + i * 3 + 1, first + i * 3 + 2])
        md.matrix_inverse = g.matrix_world.inverted() @ w.matrix_world
    sc["lida_hs_grips"] = names
    sc["lida_hs_bend_wire"] = int(k)
    sc["lida_hs_bend_hair"] = hair.name
    sc["lida_hs_bend_sel"] = (
        int(hair.hide_select) if not sc.get("lida_hs_bend_keep") else int(sc.get("lida_hs_bend_sel", 0))
    )
    sc["lida_hs_bend_keep"] = 1
    hair.hide_select = True
    ED.set_hidden(hair, [int(x) for x in hair.get("lw_hidden", [])])
    ED.hide_modifier(hair, True)
    w.hide_select = True
    for area in context.screen.areas if context.screen else []:  # the dotted lines from the grips are only noise
        if area.type == "VIEW_3D" and area.spaces.active.overlay.show_relationship_lines:
            area.spaces.active.overlay.show_relationship_lines = False
            sc["lida_hs_bend_lines"] = 1
    for o in context.view_layer.objects:
        o.select_set(False)
    last = bpy.data.objects[names[-1]]
    last.select_set(True)
    context.view_layer.objects.active = last
    return len(names)


def bending(context):
    return bool(context.scene.get("lida_hs_grips"))

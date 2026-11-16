# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
# The panel of Kanzashi. As an add-on it is registered by __init__.py; to try it without installing:
#   blender file.blend --python panel.py
# Sidebar (N) > "Kanzashi". Steps: 1 register the hair meshes, 2 find the strands (one wire and one colour per
# strand), 3 fix wrong colours by painting, 4 bend by wires, 5 the strand UV, 6 finish.

import bpy
import numpy as np
from bpy_extras import view3d_utils
from mathutils import kdtree

from . import strands as S
from . import tree as TR
from . import i18n as LANG

T = LANG.T
TR.TRANSLATE = T                # the progress texts of the slow steps

R = S.R
TOOL = "lida.hs_face_tool"
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
    slots = {i for i, s in enumerate(ob.material_slots) if s.material and any(w in s.material.name.lower() for w in WORDS)}
    if not slots:
        return False
    mi = np.empty(len(ob.data.polygons), dtype=np.int32); ob.data.polygons.foreach_get("material_index", mi)
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
    sc = context.scene; hs = registered(context)
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
                o.hide_set(True); hidden.append(o.name)
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
                    m.show_viewport = False; off.append("%s|%s" % (h.name, m.name))
        sc["lida_hs_mods"] = list(sc.get("lida_hs_mods", [])) + off
        if vp is not None and vp.show_brush:
            vp.show_brush = False; sc["lida_hs_brush"] = 1
    else:
        for key in sc.get("lida_hs_mods", []):
            hn, mn = key.split("|", 1); h = bpy.data.objects.get(hn)
            if h is not None and mn in h.modifiers:
                h.modifiers[mn].show_viewport = True
        sc["lida_hs_mods"] = []
        if vp is not None and sc.get("lida_hs_brush"):
            vp.show_brush = True; sc["lida_hs_brush"] = 0


def flat_colour_view(context):
    sc = context.scene
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            sh = area.spaces.active.shading
            if not (sh.type == "SOLID" and sh.color_type == "VERTEX" and sh.light == "FLAT") and not sc.get("lida_hs_shading"):
                sc["lida_hs_shading"] = [sh.type, sh.color_type, sh.light]      # how the view was before the tool
            sh.type = "SOLID"; sh.color_type = "VERTEX"; sh.light = "FLAT"


def normal_view(context):
    """The 3D views back to how they were before the tool (if that is not known: Blender's usual solid view)."""
    sc = context.scene; was = list(sc.get("lida_hs_shading", [])) or ["SOLID", "MATERIAL", "STUDIO"]
    for area in context.screen.areas if context.screen else []:
        if area.type == "VIEW_3D":
            sh = area.spaces.active.shading
            if sh.type == "SOLID" and sh.color_type == "VERTEX" and sh.light == "FLAT":
                try:
                    sh.type = was[0]; sh.color_type = was[1]; sh.light = was[2]
                except Exception:
                    sh.type = "SOLID"; sh.color_type = "MATERIAL"; sh.light = "STUDIO"
    if "lida_hs_shading" in sc:
        del sc["lida_hs_shading"]


_syncing = [False]


def sync_list(context, hair=None):
    """The list of colours in the panel: one row per wire of the current hair."""
    sc = context.scene; hair = hair or _current(context)
    _syncing[0] = True
    try:
        sc.lida_hs_wires.clear()
        if not _detected(hair):
            return
        hidden = {int(x) for x in hair.get("lw_hidden", [])}
        for k, faces, kind in TR.wire_table(hair, _wires(context, hair)):
            it = sc.lida_hs_wires.add()
            it.wire = k; it.faces = faces; it.kind = kind; it.hidden = k in hidden
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
    hair = _current(context); k = context.scene.lida_hs_wire_index
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
    if TR.HIDE_GROUP in hair.modifiers:
        TR.hide_modifier(hair, False)
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
    mwi = hair.matrix_world.inverted(); dg = context.evaluated_depsgraph_get()
    o = mwi @ origin; d = (mwi.to_3x3() @ direction).normalized(); me = hair.data
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
    k = int(TR.face_strands(hair.data)[index])
    if k < 0:
        return None, -1
    set_current(context, hair, k)
    return hair, k


def pick_shown(context, origin, direction):
    """Like pick_ray, for Object Mode: what is hit is the mesh as shown (hidden colours left out, outline shell
    included), so the wire is read from the shown mesh itself."""
    dg = context.evaluated_depsgraph_get(); best = None
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
_keys = []
_cursor = None


def _draw_cursor(xy):
    """Drawn at the mouse while "fix colours" is on: a ring the size of the brush in the colour in hand
    (brush), a small ring (eyedropper) or a double ring (show two colours)."""
    try:
        import math
        import gpu
        from gpu_extras.batch import batch_for_shader
        context = bpy.context; sc = context.scene
        if not getattr(sc, "lida_hs_on", False) or context.mode != "PAINT_VERTEX":
            return
        area = context.area; region = context.region
        if area is None or area.type != "VIEW_3D" or region is None or region.type != "WINDOW":
            return
        rv3d = area.spaces.active.region_3d; hair = _current(context)
        k = int(hair.get("lw_current", -1)) if hair is not None else -1
        mode = sc.lida_hs_mode
        if mode == "PAINT":
            c = rv3d.view_location; right = rv3d.view_rotation @ __import__("mathutils").Vector((1.0, 0.0, 0.0))
            try:                                   # as large as it is on the hair under the mouse
                co = (xy[0] - region.x, xy[1] - region.y)
                o = view3d_utils.region_2d_to_origin_3d(region, rv3d, co); dv = view3d_utils.region_2d_to_vector_3d(region, rv3d, co)
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
            shader.bind(); shader.uniform_float("color", colour)
            batch_for_shader(shader, "LINE_STRIP", {"pos": pts}).draw(shader)

        ring(rad, (0.0, 0.0, 0.0, 0.9), 4.0)
        ring(rad, col if mode != "PICK" else (1.0, 1.0, 1.0, 1.0), 2.0)
        if mode == "FOCUS":
            ring(rad + 5.0, (1.0, 1.0, 1.0, 1.0), 1.5)
        gpu.state.line_width_set(1.0); gpu.state.blend_set("NONE")
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
    me = hair.data; key = (hair.name, len(me.polygons)); nf = len(me.polygons)
    if key not in _trees:
        # where the faces are on screen: after the armature and the wires (the first faces of the evaluated
        # mesh are the mesh's own faces, in the same order)
        ev = hair.evaluated_get(context.evaluated_depsgraph_get()).data
        src = ev if len(ev.polygons) >= nf else me
        kd = kdtree.KDTree(nf); nrm = []
        for i in range(nf):
            p = src.polygons[i]; kd.insert(p.center, i); nrm.append(p.normal.copy())
        kd.balance(); _trees.clear(); _trees[key] = (kd, nrm)
    kd, nrm = _trees[key]
    d = (hair.matrix_world.inverted().to_3x3() @ direction).normalized()
    scale = max(hair.matrix_world.to_scale())
    ca = me.color_attributes["lw_strand_col"]; rgb = tuple(float(x) for x in TR.PAL[k]) + (1.0,)
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
    r = TR.apply_repaint(hair, _wires(context, hair))
    hidden = [int(x) for x in hair.get("lw_hidden", [])]
    if hidden:
        TR.set_hidden(hair, hidden)
    _trees.clear(); sync_list(context, hair)
    return r


def _view_ray(context, event):
    region = context.region; rv3d = context.region_data
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


class LidaHsItem(bpy.types.PropertyGroup):
    obj: bpy.props.PointerProperty(type=bpy.types.Object)


class LidaHsWire(bpy.types.PropertyGroup):
    wire: bpy.props.IntProperty()
    faces: bpy.props.IntProperty()
    kind: bpy.props.StringProperty()
    hidden: bpy.props.BoolProperty()
    color: bpy.props.FloatVectorProperty(subtype="COLOR", size=3, min=0.0, max=1.0)


class LIDA_UL_hs_wires(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        sw = row.row(align=True); sw.ui_units_x = 1.6; sw.prop(item, "color", text="")
        kind = {"base": T("基準"), "branch": T("枝"), "loose": T("部品"), "new": T("新規")}.get(item.kind, item.kind)
        row.label(text=T("%d  %s  %d 面") % (item.wire, kind, item.faces))
        row.operator("lida.hs_solo", text="", icon="RESTRICT_SELECT_OFF", emboss=False).wire = item.wire
        row.operator("lida.hs_eye", text="", icon="HIDE_ON" if item.hidden else "HIDE_OFF", emboss=False).wire = item.wire


class LIDA_OT_hs_auto(bpy.types.Operator):
    bl_idname = "lida.hs_auto"; bl_label = "髪を自動で登録"
    bl_description = "見えているメッシュのうち、名前か材質の名前から髪と判断した物を登録し、ほかを隠します"; bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = sum(1 for o in context.view_layer.objects if o.visible_get() and looks_like_hair(o) and _add(context, o))
        if registered(context):
            only_hair(context, True)
        self.report({"INFO"}, T("登録 %d 個（合計 %d 個）。ほかの物は隠しました") % (n, len(registered(context))))
        return {"FINISHED"}


class LIDA_OT_hs_add(bpy.types.Operator):
    bl_idname = "lida.hs_add"; bl_label = "選んだメッシュを足す"; bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        cand = list(context.selected_objects)
        if context.active_object is not None and context.active_object not in cand:
            cand.append(context.active_object)
        meshes = [o for o in cand if o.type == "MESH"]
        new = [o for o in meshes if _add(context, o)]
        if new:
            if context.scene.get("lida_hs_hidden"):
                only_hair(context, True)
            self.report({"INFO"}, T("足しました：") + T("、").join(o.name for o in new))
        elif meshes:
            self.report({"WARNING"}, T("選んだメッシュはもう登録済みです"))
        else:
            self.report({"WARNING"}, T("メッシュが選ばれていません。下の欄から名前で選んで足すこともできます"))
        return {"FINISHED"}


class LIDA_OT_hs_remove(bpy.types.Operator):
    bl_idname = "lida.hs_remove"; bl_label = "登録から外す"; bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        lst = context.scene.lida_hs_list
        if self.index < 0:
            lst.clear()
        elif self.index < len(lst):
            lst.remove(self.index)
        return {"FINISHED"}


class LIDA_OT_hs_isolate(bpy.types.Operator):
    bl_idname = "lida.hs_isolate"; bl_label = "髪だけ表示"
    bl_description = "登録した髪とそのワイヤー以外を隠す／隠した物を戻す"
    on: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        n = only_hair(context, self.on)
        self.report({"INFO"}, T("隠している物 %d 個") % n)
        return {"FINISHED"}


class LIDA_OT_hs_detect(bpy.types.Operator):
    bl_idname = "lida.hs_detect"; bl_label = "毛束を検出してワイヤーを作る"
    bl_description = "登録した髪すべてが対象。メッシュを切るので、写しのファイルで行ってください"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if any(_detected(h) for h in registered(context)):      # a second detection throws the edits away: ask
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        hs = registered(context); sc = context.scene
        if not hs:
            self.report({"ERROR"}, T("先に ① で髪を登録してください")); return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if sc.lida_hs_autotop:                      # the crown: the highest point of the registered hair
            best = None
            for h in hs:
                co = np.empty(len(h.data.vertices) * 3, dtype=np.float32); h.data.vertices.foreach_get("co", co)
                w = co.reshape(-1, 3) @ np.array(h.matrix_world)[:3, :3].T + np.array(h.matrix_world)[:3, 3]
                i = int(np.argmax(w[:, 2]))
                if best is None or w[i, 2] > best[2]:
                    best = w[i]
            sc.cursor.location = tuple(float(x) for x in best)
        total = 0; failed = []
        for hair in hs:
            try:
                st = TR.detect_and_bind(hair, _wires(context, hair), tuple(sc.cursor.location), cap_len=sc.lida_hs_cap)
                total += st["wires"]; TR.fill_strandless(hair.data)
            except Exception as e:
                failed.append(T("%s：%s") % (hair.name, e))
        TR.drop_unused_groups()
        only_hair(context, True); flat_colour_view(context); _trees.clear(); sync_list(context)
        if failed:
            self.report({"ERROR"}, T("失敗した物は曲げる仕組みを外しました。") + " / ".join(failed))
        self.report({"INFO"}, T("髪 %d 個、ワイヤー %d 本") % (len(hs) - len(failed), total))
        return {"FINISHED"}


class LIDA_OT_hs_start(bpy.types.Operator):
    bl_idname = "lida.hs_start"; bl_label = "色を直すモードに入る"
    bl_description = "髪を色そのままで表示し、スポイトとブラシが使える状態にします"

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair) or not enter_paint(context, hair):
            self.report({"ERROR"}, T("先に ② の検出を実行してください")); return {"CANCELLED"}
        if int(hair.get("lw_current", -1)) < 0:
            context.scene.lida_hs_mode = "PICK"
        context.scene.lida_hs_on = True
        work_view(context, True)
        return {"FINISHED"}


class LIDA_OT_hs_stop(bpy.types.Operator):
    bl_idname = "lida.hs_stop"; bl_label = "色を直すモードを終わる"
    bl_description = "通常のモードへ戻ります（塗った結果は残ります）"

    def execute(self, context):
        context.scene.lida_hs_on = False
        work_view(context, False)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        flat_colour_view(context)
        return {"FINISHED"}


class LIDA_OT_hs_stroke(bpy.types.Operator):
    bl_idname = "lida.hs_stroke"; bl_label = "毛束の色を塗る"
    bl_description = "スポイト：クリックした面の色を拾う。ブラシ：なぞった面を今の色にして、そのワイヤーへ付け替える"
    bl_options = {"REGISTER", "UNDO"}
    pick: bpy.props.BoolProperty(default=False)
    focus: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        sc = context.scene
        if not sc.lida_hs_on or not _detected(context.active_object) or context.active_object not in registered(context):
            return {"PASS_THROUGH"}                 # not our business: Blender's own painting goes on as usual
        ray = _view_ray(context, event)
        if ray is None:
            return {"PASS_THROUGH"}
        if self.focus or sc.lida_hs_mode == "FOCUS":
            hair = _current(context); cur = int(hair.get("lw_current", -1)) if _detected(hair) else -1
            hit = cast(context, hair, *ray) if _detected(hair) else None
            if hit is None:
                self.report({"WARNING"}, T("髪の面に当たりませんでした")); return {"CANCELLED"}
            k2 = int(TR.face_strands(hair.data)[hit[1]])
            keep = {k2} | ({cur} if cur >= 0 else set())
            nw = len(_wires(context, hair).data.splines)
            TR.set_hidden(hair, [k for k in range(nw) if k not in keep]); _trees.clear(); sync_list(context, hair)
            sc.lida_hs_mode = "PAINT" if cur >= 0 else "PICK"
            self.report({"INFO"}, T("ワイヤー %s と %d だけ表示しています") % (cur if cur >= 0 else "-", k2))
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        if self.pick or sc.lida_hs_mode == "PICK":
            hair, k = pick_ray(context, *ray)
            if k < 0:
                self.report({"WARNING"}, T("検出済みの髪の面に当たりませんでした")); return {"CANCELLED"}
            if context.active_object != hair:
                enter_paint(context, hair)
            sc.lida_hs_mode = "PAINT"
            self.report({"INFO"}, T("ワイヤー %d の色を拾いました（ブラシに切り替え）") % k)
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        hair = _current(context)
        if not _detected(hair) or int(hair.get("lw_current", -1)) < 0:
            self.report({"WARNING"}, T("先にスポイトか一覧で色を選んでください")); return {"CANCELLED"}
        _trees.clear()
        self._hair = hair.name; self._n = paint_ray(context, hair, ray[0], ray[1], sc.lida_hs_radius)
        self._last = (event.mouse_region_x, event.mouse_region_y)
        context.window_manager.modal_handler_add(self)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        hair = bpy.data.objects.get(self._hair)
        if hair is None:
            return {"CANCELLED"}
        if event.type == "MOUSEMOVE":
            region = context.region; rv3d = context.region_data
            if region is not None and rv3d is not None:
                x0, y0 = self._last; x1, y1 = event.mouse_region_x, event.mouse_region_y
                steps = max(1, min(40, int(max(abs(x1 - x0), abs(y1 - y0)) / 3)))     # no gaps on a fast drag
                for s in range(1, steps + 1):
                    co = (x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps)
                    self._n += paint_ray(context, hair, view3d_utils.region_2d_to_origin_3d(region, rv3d, co),
                                         view3d_utils.region_2d_to_vector_3d(region, rv3d, co), context.scene.lida_hs_radius)
                self._last = (x1, y1)
                if context.area:
                    context.area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type in {"LEFTMOUSE", "ESC", "RIGHTMOUSE"} and event.value in {"RELEASE", "PRESS"}:
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                return {"RUNNING_MODAL"}
            r = apply_hair(context, hair)
            self.report({"INFO"}, T("付け替えた面 %d") % r["faces_moved"])
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class LIDA_OT_hs_eye(bpy.types.Operator):
    bl_idname = "lida.hs_eye"; bl_label = "この色を隠す／表示する"
    wire: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair):
            return {"CANCELLED"}
        hidden = {int(x) for x in hair.get("lw_hidden", [])}
        if self.wire < 0:
            hidden = set()
        elif self.wire in hidden:
            hidden.discard(self.wire)
        else:
            hidden.add(self.wire)
        TR.set_hidden(hair, sorted(hidden)); _trees.clear(); sync_list(context, hair)
        if bending(context):
            hair.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class LIDA_OT_hs_solo(bpy.types.Operator):
    bl_idname = "lida.hs_solo"; bl_label = "この色だけ表示する"
    wire: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair):
            return {"CANCELLED"}
        n = len(_wires(context, hair).data.splines)
        TR.set_hidden(hair, [k for k in range(n) if k != self.wire]); _trees.clear(); sync_list(context, hair)
        if bending(context):
            hair.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class LIDA_OT_hs_new(bpy.types.Operator):
    bl_idname = "lida.hs_new"; bl_label = "新しい色（ワイヤー）を足す"
    bl_description = "新しい色を作ります。その色で面を塗ると、塗った面の真ん中を通るワイヤーが自動で引かれます"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair):
            self.report({"ERROR"}, T("先に ② の検出を実行してください")); return {"CANCELLED"}
        k = TR.new_wire(hair, _wires(context, hair))
        sync_list(context, hair); set_current(context, hair, k); context.scene.lida_hs_mode = "PAINT"
        self.report({"INFO"}, T("新しい色 %d を作りました。この色で面を塗ってください") % k)
        return {"FINISHED"}


class LIDA_OT_hs_size(bpy.types.Operator):
    bl_idname = "lida.hs_size"; bl_label = "ブラシの太さを変える"
    factor: bpy.props.FloatProperty(default=1.25)

    def execute(self, context):
        sc = context.scene
        sc.lida_hs_radius = min(max(sc.lida_hs_radius * self.factor, 0.001), 0.2)
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


def _grips(context):
    return [bpy.data.objects[nm] for nm in context.scene.get("lida_hs_grips", []) if nm in bpy.data.objects]


def end_bend(context):
    """Writes where the grips are into the wire and removes the grips."""
    sc = context.scene; hair = bpy.data.objects.get(sc.get("lida_hs_bend_hair", "")); k = int(sc.get("lida_hs_bend_wire", -1))
    grips = _grips(context)
    if hair is not None and grips and k >= 0:
        w = _wires(context, hair)
        for m in [m for m in w.modifiers if m.name.startswith("lida_grip")]:
            w.modifiers.remove(m)
        if k < len(w.data.splines):
            inv = w.matrix_world.inverted(); sp = w.data.splines[k]
            for g, bp in zip(grips, sp.bezier_points):
                bp.co = inv @ g.matrix_world.translation
            for bp in sp.bezier_points:                      # smooth handles for the new positions
                bp.handle_left_type = bp.handle_right_type = "AUTO"
        w.data.update_tag(); w.hide_select = False
        if TR.HIDE_GROUP in hair.modifiers and not sc.get("lida_hs_bend_switch"):
            TR.hide_modifier(hair, False)
        hair.hide_select = bool(sc.get("lida_hs_bend_sel", 0))
    for g in grips:
        bpy.data.objects.remove(g, do_unlink=True)
    sc["lida_hs_grips"] = []; sc["lida_hs_bend_wire"] = -1
    return hair


def start_bend(context, hair, k):
    """Puts round grips on wire k of `hair` (grips of another wire are written back first). Returns grips made."""
    sc = context.scene
    sc["lida_hs_bend_switch"] = 1
    try:
        end_bend(context)
    finally:
        sc["lida_hs_bend_switch"] = 0
    for h in registered(context):                     # only the hair being bent leaves its hidden colours out
        if h != hair and TR.HIDE_GROUP in h.modifiers:
            TR.hide_modifier(h, False)
    w = _wires(context, hair)
    if not (0 <= k < len(w.data.splines)):
        return 0
    w.hide_set(False); w.show_in_front = True
    sp = w.data.splines[k]; first = sum(len(s.bezier_points) * 3 for s in list(w.data.splines)[:k])
    co = np.empty(len(hair.data.vertices) * 3, dtype=np.float32); hair.data.vertices.foreach_get("co", co)
    size = float(np.clip(np.ptp(co.reshape(-1, 3), axis=0).max() * max(hair.matrix_world.to_scale()) * 0.03, 0.010, 0.04))
    col = tuple(float(x) for x in TR.to_srgb(TR.PAL[k])) + (1.0,)
    names = []
    for i, bp in enumerate(sp.bezier_points):
        g = bpy.data.objects.new("LS_Grip_%02d" % i, None)
        g.empty_display_type = "SPHERE"; g.empty_display_size = size; g.show_in_front = True; g.color = col
        g.matrix_world.translation = w.matrix_world @ bp.co
        context.scene.collection.objects.link(g); names.append(g.name)
    context.view_layer.update()
    for i, nm in enumerate(names):
        g = bpy.data.objects[nm]
        md = w.modifiers.new("lida_grip_%02d" % i, "HOOK"); md.object = g
        md.vertex_indices_set([first + i * 3, first + i * 3 + 1, first + i * 3 + 2])
        md.matrix_inverse = g.matrix_world.inverted() @ w.matrix_world
    sc["lida_hs_grips"] = names; sc["lida_hs_bend_wire"] = int(k); sc["lida_hs_bend_hair"] = hair.name
    sc["lida_hs_bend_sel"] = int(hair.hide_select) if not sc.get("lida_hs_bend_keep") else int(sc.get("lida_hs_bend_sel", 0))
    sc["lida_hs_bend_keep"] = 1; hair.hide_select = True
    TR.set_hidden(hair, [int(x) for x in hair.get("lw_hidden", [])]); TR.hide_modifier(hair, True)
    w.hide_select = True
    for area in context.screen.areas if context.screen else []:      # the dotted lines from the grips are only noise
        if area.type == "VIEW_3D" and area.spaces.active.overlay.show_relationship_lines:
            area.spaces.active.overlay.show_relationship_lines = False; sc["lida_hs_bend_lines"] = 1
    for o in context.view_layer.objects:
        o.select_set(False)
    last = bpy.data.objects[names[-1]]; last.select_set(True); context.view_layer.objects.active = last
    return len(names)


def bending(context):
    return bool(context.scene.get("lida_hs_grips"))


class LIDA_OT_hs_bend(bpy.types.Operator):
    bl_idname = "lida.hs_bend"; bl_label = "ワイヤーのつまみを出して髪を曲げる"
    bl_description = "選んである色のワイヤーに、丸いつまみを出します。つまみを動かすと、その毛束が付いてきます"
    bl_options = {"REGISTER", "UNDO"}
    on: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        sc = context.scene
        if sc.lida_hs_on:
            sc.lida_hs_on = False; work_view(context, False)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not self.on:
            hair = end_bend(context) or _current(context); sc["lida_hs_bend_keep"] = 0
            if sc.get("lida_hs_bend_lines"):
                for area in context.screen.areas if context.screen else []:
                    if area.type == "VIEW_3D":
                        area.spaces.active.overlay.show_relationship_lines = True
                sc["lida_hs_bend_lines"] = 0
            if hair is not None:
                for o in context.view_layer.objects:
                    o.select_set(o == hair)
                context.view_layer.objects.active = hair
            return {"FINISHED"}
        hair = _current(context)
        if not _detected(hair):
            self.report({"ERROR"}, T("先に ② の検出を実行してください")); return {"CANCELLED"}
        k = int(hair.get("lw_current", -1))
        if k < 0:
            k = int(np.argmax([f for _k, f, _kind in TR.wire_table(hair, _wires(context, hair))]))
            set_current(context, hair, k)
        made = start_bend(context, hair, k); flat_colour_view(context); sync_list(context, hair)
        self.report({"INFO"}, T("ワイヤー %d のつまみ %d 個を出しました。つまみをクリックして G で動かします") % (k, made))
        return {"FINISHED"}


class LIDA_OT_hs_bend_pick(bpy.types.Operator):
    bl_idname = "lida.hs_bend_pick"; bl_label = "曲げる毛束を選ぶ"
    bl_description = "つまみが出ている間、髪の面をクリックすると、その色のワイヤーのつまみに切り替わります"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if not bending(context) or context.mode != "OBJECT":
            return {"PASS_THROUGH"}
        region = context.region; rv3d = context.region_data
        if region is None or rv3d is None:
            return {"PASS_THROUGH"}
        mouse = __import__("mathutils").Vector((event.mouse_region_x, event.mouse_region_y))
        right = rv3d.view_rotation @ __import__("mathutils").Vector((1.0, 0.0, 0.0))
        best = None
        for g in _grips(context):                      # a click anywhere inside a grip's circle selects that grip
            c = g.matrix_world.translation
            a2 = view3d_utils.location_3d_to_region_2d(region, rv3d, c)
            b2 = view3d_utils.location_3d_to_region_2d(region, rv3d, c + right * g.empty_display_size)
            if a2 is not None and b2 is not None and (mouse - a2).length <= max((b2 - a2).length * 1.3, 10.0):
                if best is None or (mouse - a2).length < best[0]:
                    best = ((mouse - a2).length, g)
        if best is not None:
            g = best[1]
            if not event.shift:
                for o in context.view_layer.objects:
                    o.select_set(False)
            g.select_set(True); context.view_layer.objects.active = g
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        ray = _view_ray(context, event)
        hair, k = pick_shown(context, *ray) if ray is not None else (None, -1)
        if k < 0:
            return {"PASS_THROUGH"}
        if k != int(context.scene.get("lida_hs_bend_wire", -1)) or hair.name != context.scene.get("lida_hs_bend_hair"):
            start_bend(context, hair, k)
        self.report({"INFO"}, T("ワイヤー %d のつまみに切り替えました") % k)
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class LIDA_OT_hs_escape(bpy.types.Operator):
    bl_idname = "lida.hs_escape"; bl_label = "一つ戻る／終わる"
    bl_description = "Esc：今の道具や絞り込みをやめる。何も選んでいない状態なら、そのモード自体を終わる"

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        sc = context.scene
        if sc.lida_hs_on and context.mode == "PAINT_VERTEX":
            hair = _current(context)
            hidden = bool(hair is not None and len(hair.get("lw_hidden", [])))
            if sc.lida_hs_mode != "PICK" or hidden:           # first: back to the plain state (eyedropper, all shown)
                if hidden:
                    TR.set_hidden(hair, []); _trees.clear(); sync_list(context, hair)
                sc.lida_hs_mode = "PICK"
                self.report({"INFO"}, T("スポイトに戻しました（もう一度 Esc で、色を直すモードを終わります）"))
            else:
                bpy.ops.lida.hs_stop()
                self.report({"INFO"}, T("色を直すモードを終わりました"))
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        if bending(context) and context.mode == "OBJECT":
            sel = [g for g in _grips(context) if g.select_get()]
            if sel:
                for g in sel:
                    g.select_set(False)
                self.report({"INFO"}, T("つまみの選択を外しました（もう一度 Esc で、曲げるモードを終わります）"))
            else:
                bpy.ops.lida.hs_bend(on=False)
                self.report({"INFO"}, T("曲げるモードを終わりました"))
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        return {"PASS_THROUGH"}


def leave_modes(context):
    """Out of the colour mode and the bend mode, everything shown again as it was."""
    sc = context.scene
    if bending(context):
        end_bend(context); sc["lida_hs_bend_keep"] = 0
        if sc.get("lida_hs_bend_lines"):
            for area in context.screen.areas if context.screen else []:
                if area.type == "VIEW_3D":
                    area.spaces.active.overlay.show_relationship_lines = True
            sc["lida_hs_bend_lines"] = 0
    if sc.lida_hs_on:
        sc.lida_hs_on = False
    work_view(context, False)
    if context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for h in registered(context):
        h.hide_select = False
        if _detected(h):
            TR.set_hidden(h, [])
            if TR.HIDE_GROUP in h.modifiers:
                TR.hide_modifier(h, False)
    _trees.clear()


class LIDA_OT_hs_quit(bpy.types.Operator):
    bl_idname = "lida.hs_quit"; bl_label = "ツールを終わる"
    bl_description = "色を直すモード・曲げるモードを終わり、隠した物と面をすべて表示に戻します。曲げる仕組みとワイヤーは残るので、後で続きができます"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        leave_modes(context)
        only_hair(context, False)
        normal_view(context)
        hs = registered(context)
        if hs:
            for o in context.view_layer.objects:
                o.select_set(o == hs[0])
            context.view_layer.objects.active = hs[0]
        self.report({"INFO"}, T("ツールを終わりました（表示を元に戻しました）"))
        return {"FINISHED"}


class LIDA_OT_hs_finalize(bpy.types.Operator):
    bl_idname = "lida.hs_finalize"; bl_label = "曲げた形を確定して仕組みを外す"
    bl_description = "曲げた形をメッシュに書き込み、曲げる仕組み・ワイヤー・結び付けの情報を外します。毛束ごとの色と UV は残ります。確定後にまた曲げるには、検出からやり直します"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        leave_modes(context)
        normal_view(context)
        done = []; failed = []
        for h in registered(context):
            if not _detected(h):
                continue
            try:
                r = TR.finalize(h, bpy.data.objects.get(h.get("lw_wires", "")))
                done.append(T("%s（最大 %.1f mm）") % (h.name, r["moved_mm"]))
            except Exception as e:
                failed.append(T("%s：%s") % (h.name, e))
        only_hair(context, False); context.scene.lida_hs_wires.clear()
        if failed:
            self.report({"ERROR"}, T("確定できなかった物：") + " / ".join(failed))
        self.report({"INFO"}, T("確定しました：") + (T("、").join(done) if done else T("なし")))
        TR.drop_unused_groups()
        return {"FINISHED"}


class _BusyOp:
    """For slow operators: the panel and the status bar say what is going on before the work starts, the mouse
    pointer becomes the waiting one, and the slow steps report as they go. From scripts, execute() just does the work."""
    busy_text = "処理中です"

    def execute(self, context):
        return self.work(context)

    def invoke(self, context, event):
        sc = context.scene; wm = context.window_manager
        sc["lida_hs_busy"] = T(self.busy_text); sc["lida_hs_busy_pct"] = 0
        context.window.cursor_modal_set("WAIT"); context.workspace.status_text_set(sc["lida_hs_busy"])
        for a in context.screen.areas:
            a.tag_redraw()
        self._ticks = 0; self._timer = wm.event_timer_add(0.1, window=context.window); wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}                     # nothing else gets through while it runs
        self._ticks += 1
        if self._ticks < 3:                              # let the panel draw the notice first
            return {"RUNNING_MODAL"}
        wm = context.window_manager; sc = context.scene
        wm.event_timer_remove(self._timer); wm.progress_begin(0, 100)

        def tell(text, share):
            sc["lida_hs_busy"] = text; sc["lida_hs_busy_pct"] = int(share * 100)
            wm.progress_update(int(share * 100)); context.workspace.status_text_set(sc["lida_hs_busy"])
            try:
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except Exception:
                pass
            shot = sc.get("lida_hs_shot")                # for the test of this notice: one picture of the screen
            if shot and share >= 0.3:
                sc["lida_hs_shot"] = ""
                try:
                    bpy.ops.screen.screenshot(filepath=shot)
                except Exception:
                    pass
        TR.PROGRESS = tell
        try:
            return self.work(context)
        finally:
            TR.PROGRESS = None; wm.progress_end(); sc["lida_hs_busy"] = ""
            context.window.cursor_modal_restore(); context.workspace.status_text_set(None)
            for a in context.screen.areas:
                a.tag_redraw()


class LIDA_OT_hs_uvshow(bpy.types.Operator):
    bl_idname = "lida.hs_uvshow"; bl_label = "作った UV を選ぶ／元の UV に戻す"
    bl_description = "UV エディターに出す UV マップを、毛束ごとの UV（LW_StrandUV）と元の UV の間で切り替えます。描画に使う UV は変えません"
    strand: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        n = 0
        for h in registered(context):
            uvs = h.data.uv_layers
            if self.strand and "LW_StrandUV" in uvs:
                uvs.active = uvs["LW_StrandUV"]; n += 1
            elif not self.strand:
                first = next((l for l in uvs if l.name != "LW_StrandUV"), None)
                if first is not None:
                    uvs.active = first; n += 1
        self.report({"INFO"}, T("切り替えた髪 %d 個") % n)
        return {"FINISHED"}


class LIDA_OT_hs_uv(_BusyOp, bpy.types.Operator):
    bl_idname = "lida.hs_uv"; bl_label = "毛束ごとの UV を作る"; bl_options = {"REGISTER", "UNDO"}
    bl_description = "毛束ごとの UV を作って検査します。数十秒かかります（進み具合はパネルの上と画面の下に出ます）"
    busy_text = "毛束ごとの UV を作っています"

    def work(self, context):
        hs = [h for h in registered(context) if _detected(h)]
        if not hs:
            self.report({"ERROR"}, T("先に ② の検出を実行してください")); return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        back_on = context.scene.lida_hs_on
        if bending(context) or back_on:
            leave_modes(context)
        made = [TR.strand_uv_auto(h, _wires(context, h)) for h in hs]; n = sum(r["strips"] for r in made)
        context.scene["lida_hs_uvways"] = T("、").join(T("%s＝%s") % (h.name, r["way"]) for h, r in zip(hs, made))
        TR.pack_together(hs)                             # one 0-1 square for all the hairs (one texture)
        TR._tell(T("UV を検査中"), 0.85); c = TR.uv_check(hs); context.scene["lida_hs_uvcheck"] = _check_text(c)
        self.report({"INFO"}, T("島 %d 個（UV マップ LW_StrandUV。元の UV はそのまま）。%s") % (n, _check_text(c)))
        return {"FINISHED"}


def _check_text(c):
    extra = T("。重なる面 %d・つぶれた面 %d（表面の %.2f %%）") % (c.get("folded_faces", 0), c.get("squashed_faces", 0), c.get("trouble_share", 0) * 100)
    if c["ok"]:
        return T("検査 OK：0〜1 の中・島の重なりなし・島の間 %d px 以上") % c["gap"] + extra
    bad = []
    if c.get("trouble_share", 0) > 0.02:
        bad.append(T("重なる面・つぶれた面が多い（表面の %.1f %%）") % (c["trouble_share"] * 100))
    if not c["inside_0_1"]:
        bad.append(T("0〜1 の外に出ている"))
    if c["overlap_pixels"]:
        bad.append(T("重なり %d px") % c["overlap_pixels"])
    if c["too_close_pixels"]:
        bad.append(T("島が近すぎる所 %d px") % c["too_close_pixels"])
    return T("検査 NG：") + T("、").join(bad)


class LIDA_OT_hs_uvswap(_BusyOp, bpy.types.Operator):
    bl_idname = "lida.hs_uvswap"; bl_label = "UV を張り替える"; bl_options = {"REGISTER", "UNDO"}
    bl_description = ("on：髪を毛束ごとの UV で描くように切り替えます。今のテクスチャは新しい UV へ写した画像に置き換わるので、見た目は変わりません"
                      "（髪だけが使う材質の写しを作ります。元の UV・材質・画像は残ります）。off：元の UV・材質に戻します")
    on: bpy.props.BoolProperty(default=True)
    busy_text = "UV を張り替えています"

    def work(self, context):
        hs = [h for h in registered(context) if "LW_StrandUV" in h.data.uv_layers]
        if bending(context) or context.scene.lida_hs_on:
            leave_modes(context)
        if not self.on:
            n_ = TR.revert_uv(hs); self.report({"INFO"}, T("元の UV・材質に戻しました（髪 %d 個）") % n_); return {"FINISHED"}
        if not hs:
            self.report({"ERROR"}, T("先に「毛束ごとの UV を作る」を押してください")); return {"CANCELLED"}
        TR._tell(T("UV を検査中"), 0.85); c = TR.uv_check(hs); context.scene["lida_hs_uvcheck"] = _check_text(c)
        if not c["ok"]:
            self.report({"ERROR"}, _check_text(c) + T("。「毛束ごとの UV を作る」を押し直してください")); return {"CANCELLED"}
        r = TR.swap_uv(hs)
        msg = T("張り替えました：髪 %d 個、写した画像 %d 枚、材質の写し %d 個") % (r["hairs"], r["images"], r.get("materials", 0))
        check = ""
        if r.get("triangles"):
            check = T("色の答え合わせ：%d 個中 %d 個の三角形で色が違う（%.2f %%）") % (r["triangles"], r["differ"], 100.0 * r["differ"] / r["triangles"])
            msg += T("。") + check
        context.scene["lida_hs_swapcheck"] = check
        if r["skipped"]:
            self.report({"WARNING"}, msg + T("。写せなかった画像：") + T("、").join(r["skipped"]))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class LIDA_OT_hs_uvdrop(bpy.types.Operator):
    bl_idname = "lida.hs_uvdrop"; bl_label = "古い UV を消す（戻せません）"; bl_options = {"REGISTER", "UNDO"}
    bl_description = "張り替え済みの髪から、毛束ごとの UV 以外の UV マップを消します。消した後は「元の UV に戻す」は使えません。元の材質と画像は消しません"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        gone = TR.drop_old_uv(registered(context))
        self.report({"INFO"}, T("消した UV：%s") % (T("、").join(gone) if gone else T("なし（張り替え済みの髪がありません）")))
        return {"FINISHED"}


class LIDA_OT_hs_export(bpy.types.Operator):
    bl_idname = "lida.hs_export"; bl_label = "テクスチャ用に書き出す"
    bl_description = ("登録した髪を 1 つのメッシュにまとめ、毛束ごとの UV だけを持たせて FBX（または .glb）で書き出します。"
                      "曲げた形で出ます。骨・輪郭線の殻・ほかの UV は入りません。今の髪は変えません")
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.glb", options={"HIDDEN"})

    def invoke(self, context, event):
        import os
        if not self.filepath:
            base = os.path.splitext(bpy.data.filepath)[0] if bpy.data.filepath else os.path.join(os.path.expanduser("~"), "hair")
            self.filepath = base + "_hair_for_texture.fbx"
        context.window_manager.fileselect_add(self); return {"RUNNING_MODAL"}

    def execute(self, context):
        hs = [h for h in registered(context) if _detected(h) and "LW_StrandUV" in h.data.uv_layers]
        if not hs:
            self.report({"ERROR"}, T("先に「毛束ごとの UV を作る」を押してください")); return {"CANCELLED"}
        if bending(context) or context.scene.lida_hs_on:
            leave_modes(context)
        TR._tell(T("UV を検査中"), 0.85); c = TR.uv_check(hs); context.scene["lida_hs_uvcheck"] = _check_text(c)
        if not c["ok"]:
            self.report({"ERROR"}, _check_text(c) + T("。「毛束ごとの UV を作る」を押し直してください")); return {"CANCELLED"}
        path = bpy.path.abspath(self.filepath)
        if not path.lower().endswith((".fbx", ".glb")):
            path += ".fbx"
        info = TR.export_for_texture(hs, path)
        mb = info["bytes"] / 1048576.0
        self.report({"WARNING"} if mb > 150 else {"INFO"}, T("書き出し：%s（%.1f MB、面 %d）%s") % (path, mb, info["faces"], T("。150 MB を超えています") if mb > 150 else ""))
        return {"FINISHED"}


class LidaHsFaceTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"; bl_context_mode = "PAINT_VERTEX"
    bl_idname = TOOL; bl_label = "毛束の色"
    bl_description = "スポイトで色を拾い、ブラシで面をその色にします（パネル「Kanzashi」で切り替え。Ctrl+クリックはいつでもスポイト）"
    bl_icon = "brush.paint_vertex.draw"
    bl_keymap = (
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS"}, {"properties": [("pick", False)]}),
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True}, {"properties": [("pick", True)]}),
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS", "shift": True}, {"properties": [("focus", True)]}),
    )


class LIDA_PT_hs(bpy.types.Panel):
    bl_label = "Kanzashi（かんざし）試作"; bl_idname = "LIDA_PT_hs"
    bl_space_type = "VIEW_3D"; bl_region_type = "UI"; bl_category = "Kanzashi"

    def draw(self, context):
        lay = self.layout; sc = context.scene
        row = lay.row(align=True); row.alignment = "RIGHT"
        row.prop(context.window_manager, "lida_hs_lang", text="", icon="WORLD")
        hs = registered(context); det = [h for h in hs if _detected(h)]
        if sc.get("lida_hs_busy"):
            box = lay.box(); box.alert = True
            box.label(text=T("処理中（%d %%）。待ってください") % sc.get("lida_hs_busy_pct", 0), icon="TIME")
            box.label(text=sc["lida_hs_busy"])
        hair = _current(context); painting = sc.lida_hs_on and context.mode == "PAINT_VERTEX" and _detected(context.active_object)
        if not hs:
            nxt = T("① の「自動で登録」を押す")
        elif not det:
            nxt = T("② の「毛束を検出」を押す")
        elif not painting:
            nxt = T("③ の「色を直すモードに入る」（検出はもう不要）")
        elif int(hair.get("lw_current", -1)) < 0:
            nxt = T("スポイトで、合わせたい色の面をクリック")
        else:
            nxt = T("色の違う所をなぞる（戻すのは Ctrl+Z）")
        box = lay.box(); box.alert = True; box.label(text=T("次：") + nxt, icon="INFO")

        box = lay.box(); box.label(text=T("① 対象の髪を決める"), icon="OUTLINER_OB_MESH")
        row = box.row(align=True)
        row.operator("lida.hs_auto", text=T("自動で登録"), icon="VIEWZOOM")
        row.operator("lida.hs_add", text=T("選択を足す"), icon="ADD")
        for i, it in enumerate(sc.lida_hs_list):
            row = box.row(align=True)
            if it.obj is None:
                row.label(text=T("（消えた物体）"), icon="ERROR")
            else:
                row.label(text=it.obj.name, icon="CHECKMARK" if _detected(it.obj) else "MESH_DATA")
            row.operator("lida.hs_remove", text="", icon="X").index = i
        box.prop(sc, "lida_hs_pick_add", text=T("名前で足す"))
        row = box.row(align=True)
        row.operator("lida.hs_isolate", text=T("髪だけ表示"), icon="HIDE_ON").on = True
        row.operator("lida.hs_isolate", text=T("隠した物を戻す"), icon="HIDE_OFF").on = False

        box = lay.box(); box.label(text=T("② 毛束を検出する"), icon="OUTLINER_OB_CURVES"); box.enabled = bool(hs)
        box.prop(sc, "lida_hs_autotop", text=T("頭頂を自動で決める（いちばん高い点）"))
        if not sc.lida_hs_autotop:
            box.label(text=T("3D カーソルを頭頂に置いてから押す"))
        if det:
            col = box.column(align=True)
            col.label(text=T("検出済み：%s") % T("、").join(h.name for h in det), icon="CHECKMARK")
            col.label(text=T("続きの編集は、検出せずに ③ へ進む"))
            col.alert = True
            col.label(text=T("もう一度検出すると、塗り直しと"), icon="ERROR")
            col.label(text=T("曲げた形が作り直されて消えます"))
            box.operator("lida.hs_detect", text=T("検出をやり直す（確認が出ます）"))
        else:
            box.operator("lida.hs_detect", text=T("毛束を検出（1 本ごとに色が付く）"))
        box.label(text=T("写しのファイルで行う（メッシュを切ります）"))

        box = lay.box(); box.label(text=T("③ 色の違う所を直す"), icon="BRUSH_DATA"); box.enabled = bool(det)
        if not painting:
            box.operator("lida.hs_start", text=T(LIDA_OT_hs_start._ja[0]), icon="PLAY")
        else:
            box.operator("lida.hs_stop", text=T(LIDA_OT_hs_stop._ja[0]), icon="PAUSE")
            row = box.row(align=True); row.scale_y = 1.4
            row.prop_enum(sc, "lida_hs_mode", "PICK", text=T("スポイト"), icon="EYEDROPPER")
            row.prop_enum(sc, "lida_hs_mode", "PAINT", text=T("ブラシ"), icon="BRUSH_DATA")
            row = box.row(align=True); row.scale_y = 1.2
            row.prop_enum(sc, "lida_hs_mode", "FOCUS", text=T("塗りたい相手をクリック → 2 色だけ表示"), icon="ZOOM_SELECTED")
            row.operator("lida.hs_eye", text="", icon="HIDE_OFF").wire = -1
            row = box.row(align=True)
            row.prop(sc, "lida_hs_radius", text=T("ブラシの太さ"))
            row.operator("lida.hs_size", text="", icon="REMOVE").factor = 0.8
            row.operator("lida.hs_size", text="", icon="ADD").factor = 1.25
            box.label(text=T("[ ] キーでも太さを変えられます。面 1 枚が最小です"))
            col = box.column(align=True)
            col.label(text=T("スポイト：面をクリックで色を拾う"))
            col.label(text=T("ブラシ：なぞった面がその色になる"))
            col.label(text=T("Ctrl+クリックはいつでもスポイト"))
            col.label(text=T("Shift+クリック：今の色とその色だけ表示"))
            col.label(text=T("戻す Ctrl+Z／やり直す Ctrl+Shift+Z"))
            col.label(text=T("Esc：スポイトへ戻る → もう一度で終わる"))
            col.label(text=T("左のツールバーの筆は使いません"), icon="ERROR")
        if det and hair is not None:
            cur = int(hair.get("lw_current", -1))
            box.label(text=T("色の一覧（%s）　今の色：%s") % (hair.name, cur if cur >= 0 else T("なし")))
            box.template_list("LIDA_UL_hs_wires", "", sc, "lida_hs_wires", sc, "lida_hs_wire_index", rows=8)
            row = box.row(align=True)
            row.operator("lida.hs_eye", text=T("全部表示"), icon="HIDE_OFF").wire = -1
            row.operator("lida.hs_new", text=T("新しい色を足す"), icon="ADD")
            box.label(text=T("行をクリック：その色を選ぶ／目：隠す／矢印：その色だけ"))

        box = lay.box(); box.label(text=T("④ ワイヤーで髪を曲げる"), icon="CURVE_BEZCURVE"); box.enabled = bool(det)
        editing = bool(sc.get("lida_hs_grips"))
        if not editing:
            box.operator("lida.hs_bend", text=T(LIDA_OT_hs_bend._ja[0]), icon="PLAY").on = True
            box.label(text=T("押した後、曲げたい毛束の面をクリック"))
        else:
            box.label(text=T("ワイヤー %d を曲げています") % int(sc.get("lida_hs_bend_wire", -1)))
            col = box.column(align=True)
            col.label(text=T("丸いつまみをクリックして G で動かす"))
            col.label(text=T("髪の面か一覧をクリック：その毛束に切り替え"))
            col.label(text=T("Esc：選択を外す → もう一度で終わる"))
            col.label(text=T("Shift+クリックで複数選べます"))
            col.label(text=T("根元の 5 cm は動きません（その先が曲がる）"))
            col.label(text=T("色の一覧の目・矢印で、見せる毛束を絞れます"))
            box.operator("lida.hs_bend", text=T("曲げ終わる（つまみを消す）"), icon="PAUSE").on = False

        box = lay.box(); box.label(text=T("⑤ 毛束ごとの UV"), icon="UV"); box.enabled = bool(det)
        box.operator("lida.hs_uv", text=T(LIDA_OT_hs_uv._ja[0]))
        box.label(text=T("数十秒かかります（進み具合が上に出ます）"))
        have = [h.name for h in det if "LW_StrandUV" in h.data.uv_layers]
        if have:
            box.label(text=T("作成済み：%s") % T("、").join(have), icon="CHECKMARK")
            box.label(text=T("UV マップ名は LW_StrandUV（元の UV はそのまま）"))
            row = box.row(align=True)
            row.operator("lida.hs_uvshow", text=T("作った UV を選ぶ")).strand = True
            row.operator("lida.hs_uvshow", text=T("元の UV に戻す")).strand = False
            chk = sc.get("lida_hs_uvcheck", "")
            if chk:
                box.label(text=chk, icon="CHECKMARK" if chk.startswith(("検査 OK", "Check OK")) else "ERROR")
            box.operator("lida.hs_export", text=T(LIDA_OT_hs_export._ja[0]), icon="EXPORT")
            box.label(text=T("髪を 1 つにまとめ、この UV だけで FBX に出す"))
            swapped = [h.name for h in det if h.get(TR.SWAP_KEY)]
            col = box.column(align=True)
            if swapped:
                col.label(text=T("張り替え済み：%s") % T("、").join(swapped), icon="CHECKMARK")
                if sc.get("lida_hs_swapcheck", ""):
                    col.label(text=sc["lida_hs_swapcheck"])
                col.operator("lida.hs_uvswap", text=T("元の UV・材質に戻す"), icon="LOOP_BACK").on = False
            else:
                col.operator("lida.hs_uvswap", text=T("この UV に張り替える（見た目はそのまま）"), icon="UV_SYNC_SELECT").on = True
                col.label(text=T("今のテクスチャを新しい UV へ写します"))
        else:
            box.label(text=T("まだ作っていません"))

        box = lay.box(); box.label(text=T("⑥ 終わる"), icon="CHECKMARK")
        box.operator("lida.hs_quit", text=T(LIDA_OT_hs_quit._ja[0]), icon="PAUSE")
        box.label(text=T("表示を元に戻す。後で続きができます"))
        if any(h.get(TR.SWAP_KEY) for h in det):
            sub = box.column(); sub.alert = True
            sub.operator("lida.hs_uvdrop", text=T(LIDA_OT_hs_uvdrop._ja[0]), icon="TRASH")
        sub = box.column(); sub.enabled = bool(det)
        sub.operator("lida.hs_finalize", text=T(LIDA_OT_hs_finalize._ja[0]), icon="LOCKED")
        sub.label(text=T("形をメッシュに書き込み、ワイヤーを外す"))


CLASSES = (LidaHsItem, LidaHsWire, LIDA_UL_hs_wires, LIDA_OT_hs_auto, LIDA_OT_hs_add, LIDA_OT_hs_remove, LIDA_OT_hs_isolate,
           LIDA_OT_hs_detect, LIDA_OT_hs_start, LIDA_OT_hs_stop, LIDA_OT_hs_stroke, LIDA_OT_hs_eye, LIDA_OT_hs_solo,
           LIDA_OT_hs_new, LIDA_OT_hs_size, LIDA_OT_hs_bend, LIDA_OT_hs_bend_pick, LIDA_OT_hs_escape, LIDA_OT_hs_quit, LIDA_OT_hs_finalize, LIDA_OT_hs_uvshow, LIDA_OT_hs_uv, LIDA_OT_hs_uvswap, LIDA_OT_hs_uvdrop, LIDA_OT_hs_export, LIDA_PT_hs)


def _tip(cls, context, properties):
    return T(cls._ja[1])


def _localize():
    """The labels and tooltips that Blender reads once, at registration, in the language in use now. The Japanese
    originals are kept in _ja; operator tooltips are also answered live (description), so they follow a later switch."""
    for c in CLASSES + (LidaHsFaceTool,):
        if "_ja" not in c.__dict__:
            c._ja = (c.__dict__.get("bl_label", ""), c.__dict__.get("bl_description", ""))
        if c._ja[0]:
            c.bl_label = T(c._ja[0])
        if c._ja[1]:
            c.bl_description = T(c._ja[1])
            if issubclass(c, bpy.types.Operator):
                c.description = classmethod(_tip)


def _lang_changed(self, context):
    LANG.set_choice(self.lida_hs_lang)
    for w in context.window_manager.windows:
        for a in w.screen.areas:
            a.tag_redraw()


def register():
    _localize()
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.lida_hs_lang = bpy.props.EnumProperty(
        name="Language", description="Language of the Kanzashi panel / パネルの言語",
        items=(("AUTO", "Auto / 自動", "Follows Blender's interface language / Blender の表示言語に合わせる"),
               ("JA", "日本語", "Japanese"), ("EN", "English", "English")),
        default=LANG.choice(), update=_lang_changed)
    sc = bpy.types.Scene
    sc.lida_hs_list = bpy.props.CollectionProperty(type=LidaHsItem)
    sc.lida_hs_wires = bpy.props.CollectionProperty(type=LidaHsWire)
    sc.lida_hs_wire_index = bpy.props.IntProperty(default=-1, update=_row_picked)
    sc.lida_hs_hair = bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda s, o: o.type == "MESH")
    sc.lida_hs_cap = bpy.props.FloatProperty(default=0.40, min=0.05, max=2.0, subtype="DISTANCE")
    sc.lida_hs_radius = bpy.props.FloatProperty(default=0.008, min=0.001, max=0.2, soft_min=0.001, soft_max=0.04,
                                                 step=0.05, precision=4, subtype="DISTANCE")
    sc.lida_hs_autotop = bpy.props.BoolProperty(default=True)
    sc.lida_hs_mode = bpy.props.EnumProperty(items=(("PICK", T("スポイト"), T("クリックした面の色を拾う")),
                                                    ("PAINT", T("ブラシ"), T("なぞった面を今の色にする")),
                                                    ("FOCUS", T("2 色だけ"), T("クリックした面の色と今の色だけを表示する"))), default="PICK")
    sc.lida_hs_on = bpy.props.BoolProperty(default=False)
    sc.lida_hs_pick_add = bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda s, o: o.type == "MESH", update=_picked_to_add)
    try:
        bpy.utils.register_tool(LidaHsFaceTool, separator=True)
    except Exception as e:
        print("lida hair: the tool could not be registered:", e)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:                          # so the click is ours with any toolbar tool, Blender's brushes included
        km = kc.keymaps.new(name="Vertex Paint", space_type="EMPTY")
        for name in ("Object Mode", "3D View"):
            km2 = kc.keymaps.new(name=name, space_type="EMPTY" if name == "Object Mode" else "VIEW_3D")
            for value in ("PRESS",):
                for shift in (False, True):
                    kmi = km2.keymap_items.new("lida.hs_bend_pick", "LEFTMOUSE", value, shift=shift, head=True); _keys.append((km2, kmi))
        for name in ("Vertex Paint", "Object Mode"):
            km3 = kc.keymaps.new(name=name, space_type="EMPTY")
            kmi = km3.keymap_items.new("lida.hs_escape", "ESC", "PRESS", head=True); _keys.append((km3, kmi))
        for key, fac in (("LEFT_BRACKET", 0.8), ("RIGHT_BRACKET", 1.25)):
            kmi = km.keymap_items.new("lida.hs_size", key, "PRESS", head=True); kmi.properties.factor = fac; _keys.append((km, kmi))
        for ctrl, shift in ((False, False), (True, False), (False, True)):
            kmi = km.keymap_items.new("lida.hs_stroke", "LEFTMOUSE", "PRESS", ctrl=ctrl, shift=shift, head=True)
            kmi.properties.pick = ctrl; kmi.properties.focus = shift; _keys.append((km, kmi))
    global _cursor
    if _cursor is None:
        _cursor = bpy.types.WindowManager.draw_cursor_add(_draw_cursor, (), "VIEW_3D", "WINDOW")


def unregister():
    try:
        bpy.utils.unregister_tool(LidaHsFaceTool)
    except Exception:
        pass
    global _cursor
    if _cursor is not None:
        try:
            bpy.types.WindowManager.draw_cursor_remove(_cursor)
        except Exception:
            pass
        _cursor = None
    for km, kmi in _keys:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keys.clear()
    del bpy.types.Scene.lida_hs_on, bpy.types.Scene.lida_hs_pick_add
    del bpy.types.WindowManager.lida_hs_lang
    sc = bpy.types.Scene
    del sc.lida_hs_list, sc.lida_hs_wires, sc.lida_hs_wire_index, sc.lida_hs_hair, sc.lida_hs_cap, sc.lida_hs_radius
    del sc.lida_hs_autotop, sc.lida_hs_mode
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()

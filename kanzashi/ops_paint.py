# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Step 3: fixing the colours (eyedropper, brush, the list of colours)."""

import bpy
from bpy_extras import view3d_utils

from . import edit as ED
from .common import (
    T,
    _current,
    _detected,
    _trees,
    _view_ray,
    _wires,
    apply_hair,
    bending,
    cast,
    enter_paint,
    flat_colour_view,
    paint_ray,
    pick_ray,
    registered,
    set_current,
    sync_list,
    work_view,
)


class KANZASHI_OT_start(bpy.types.Operator):
    bl_idname = "kanzashi.start"
    bl_label = "色を直すモードに入る"
    bl_description = "髪を色そのままで表示し、スポイトとブラシが使える状態にします"

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair) or not enter_paint(context, hair):
            self.report({"ERROR"}, T("先に ② の検出を実行してください"))
            return {"CANCELLED"}
        if int(hair.get("lw_current", -1)) < 0:
            context.scene.lida_hs_mode = "PICK"
        context.scene.lida_hs_on = True
        work_view(context, True)
        return {"FINISHED"}


class KANZASHI_OT_stop(bpy.types.Operator):
    bl_idname = "kanzashi.stop"
    bl_label = "色を直すモードを終わる"
    bl_description = "通常のモードへ戻ります（塗った結果は残ります）"

    def execute(self, context):
        context.scene.lida_hs_on = False
        work_view(context, False)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        flat_colour_view(context)
        return {"FINISHED"}


class KANZASHI_OT_stroke(bpy.types.Operator):
    bl_idname = "kanzashi.stroke"
    bl_label = "毛束の色を塗る"
    bl_description = "スポイト：クリックした面の色を拾う。ブラシ：なぞった面を今の色にして、そのワイヤーへ付け替える"
    bl_options = {"REGISTER", "UNDO"}
    pick: bpy.props.BoolProperty(default=False)
    focus: bpy.props.BoolProperty(default=False)

    def invoke(self, context, event):
        sc = context.scene
        if (
            not sc.lida_hs_on
            or not _detected(context.active_object)
            or context.active_object not in registered(context)
        ):
            return {"PASS_THROUGH"}  # not our business: Blender's own painting goes on as usual
        ray = _view_ray(context, event)
        if ray is None:
            return {"PASS_THROUGH"}
        if self.focus or sc.lida_hs_mode == "FOCUS":
            hair = _current(context)
            cur = int(hair.get("lw_current", -1)) if _detected(hair) else -1
            hit = cast(context, hair, *ray) if _detected(hair) else None
            if hit is None:
                self.report({"WARNING"}, T("髪の面に当たりませんでした"))
                return {"CANCELLED"}
            k2 = int(ED.face_strands(hair.data)[hit[1]])
            keep = {k2} | ({cur} if cur >= 0 else set())
            nw = len(_wires(context, hair).data.splines)
            ED.set_hidden(hair, [k for k in range(nw) if k not in keep])
            _trees.clear()
            sync_list(context, hair)
            sc.lida_hs_mode = "PAINT" if cur >= 0 else "PICK"
            self.report({"INFO"}, T("ワイヤー %s と %d だけ表示しています") % (cur if cur >= 0 else "-", k2))
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        if self.pick or sc.lida_hs_mode == "PICK":
            hair, k = pick_ray(context, *ray)
            if k < 0:
                self.report({"WARNING"}, T("検出済みの髪の面に当たりませんでした"))
                return {"CANCELLED"}
            if context.active_object != hair:
                enter_paint(context, hair)
            sc.lida_hs_mode = "PAINT"
            self.report({"INFO"}, T("ワイヤー %d の色を拾いました（ブラシに切り替え）") % k)
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        hair = _current(context)
        if not _detected(hair) or int(hair.get("lw_current", -1)) < 0:
            self.report({"WARNING"}, T("先にスポイトか一覧で色を選んでください"))
            return {"CANCELLED"}
        _trees.clear()
        self._hair = hair.name
        self._n = paint_ray(context, hair, ray[0], ray[1], sc.lida_hs_radius)
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
            region = context.region
            rv3d = context.region_data
            if region is not None and rv3d is not None:
                x0, y0 = self._last
                x1, y1 = event.mouse_region_x, event.mouse_region_y
                steps = max(1, min(40, int(max(abs(x1 - x0), abs(y1 - y0)) / 3)))  # no gaps on a fast drag
                for s in range(1, steps + 1):
                    co = (x0 + (x1 - x0) * s / steps, y0 + (y1 - y0) * s / steps)
                    self._n += paint_ray(
                        context,
                        hair,
                        view3d_utils.region_2d_to_origin_3d(region, rv3d, co),
                        view3d_utils.region_2d_to_vector_3d(region, rv3d, co),
                        context.scene.lida_hs_radius,
                    )
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


class KANZASHI_OT_eye(bpy.types.Operator):
    bl_idname = "kanzashi.eye"
    bl_label = "この色を隠す／表示する"
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
        ED.set_hidden(hair, sorted(hidden))
        _trees.clear()
        sync_list(context, hair)
        if bending(context):
            hair.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class KANZASHI_OT_solo(bpy.types.Operator):
    bl_idname = "kanzashi.solo"
    bl_label = "この色だけ表示する"
    wire: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair):
            return {"CANCELLED"}
        n = len(_wires(context, hair).data.splines)
        ED.set_hidden(hair, [k for k in range(n) if k != self.wire])
        _trees.clear()
        sync_list(context, hair)
        if bending(context):
            hair.update_tag()
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}


class KANZASHI_OT_new(bpy.types.Operator):
    bl_idname = "kanzashi.new"
    bl_label = "新しい色（ワイヤー）を足す"
    bl_description = "新しい色を作ります。その色で面を塗ると、塗った面の真ん中を通るワイヤーが自動で引かれます"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        hair = _current(context)
        if not _detected(hair):
            self.report({"ERROR"}, T("先に ② の検出を実行してください"))
            return {"CANCELLED"}
        k = ED.new_wire(hair, _wires(context, hair))
        sync_list(context, hair)
        set_current(context, hair, k)
        context.scene.lida_hs_mode = "PAINT"
        self.report({"INFO"}, T("新しい色 %d を作りました。この色で面を塗ってください") % k)
        return {"FINISHED"}


class KANZASHI_OT_size(bpy.types.Operator):
    bl_idname = "kanzashi.size"
    bl_label = "ブラシの太さを変える"
    factor: bpy.props.FloatProperty(default=1.25)

    def execute(self, context):
        sc = context.scene
        sc.lida_hs_radius = min(max(sc.lida_hs_radius * self.factor, 0.001), 0.2)
        if context.area:
            context.area.tag_redraw()
        return {"FINISHED"}

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Steps 4 and 6: bending by the handles of a wire, leaving the modes, and writing the shape into the mesh."""

import bpy
import numpy as np
from bpy_extras import view3d_utils

from . import edit as ED
from . import strand_uv as UV
from .common import (
    T,
    _current,
    _detected,
    _grips,
    _trees,
    _view_ray,
    _wires,
    bending,
    end_bend,
    flat_colour_view,
    normal_view,
    only_hair,
    pick_shown,
    registered,
    set_current,
    start_bend,
    sync_list,
    work_view,
)


class KANZASHI_OT_bend(bpy.types.Operator):
    bl_idname = "kanzashi.bend"
    bl_label = "ワイヤーのつまみを出して髪を曲げる"
    bl_description = "選んである色のワイヤーに、丸いつまみを出します。つまみを動かすと、その毛束が付いてきます"
    bl_options = {"REGISTER", "UNDO"}
    on: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        sc = context.scene
        if sc.lida_hs_on:
            sc.lida_hs_on = False
            work_view(context, False)
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not self.on:
            hair = end_bend(context) or _current(context)
            sc["lida_hs_bend_keep"] = 0
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
            self.report({"ERROR"}, T("先に ② の検出を実行してください"))
            return {"CANCELLED"}
        k = int(hair.get("lw_current", -1))
        if k < 0:
            k = int(np.argmax([f for _k, f, _kind in ED.wire_table(hair, _wires(context, hair))]))
            set_current(context, hair, k)
        made = start_bend(context, hair, k)
        flat_colour_view(context)
        sync_list(context, hair)
        self.report(
            {"INFO"}, T("ワイヤー %d のつまみ %d 個を出しました。つまみをクリックして G で動かします") % (k, made)
        )
        return {"FINISHED"}


class KANZASHI_OT_bend_pick(bpy.types.Operator):
    bl_idname = "kanzashi.bend_pick"
    bl_label = "曲げる毛束を選ぶ"
    bl_description = "つまみが出ている間、髪の面をクリックすると、その色のワイヤーのつまみに切り替わります"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if not bending(context) or context.mode != "OBJECT":
            return {"PASS_THROUGH"}
        region = context.region
        rv3d = context.region_data
        if region is None or rv3d is None:
            return {"PASS_THROUGH"}
        mouse = __import__("mathutils").Vector((event.mouse_region_x, event.mouse_region_y))
        right = rv3d.view_rotation @ __import__("mathutils").Vector((1.0, 0.0, 0.0))
        best = None
        for g in _grips(context):  # a click anywhere inside a grip's circle selects that grip
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
            g.select_set(True)
            context.view_layer.objects.active = g
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


class KANZASHI_OT_escape(bpy.types.Operator):
    bl_idname = "kanzashi.escape"
    bl_label = "一つ戻る／終わる"
    bl_description = "Esc：今の道具や絞り込みをやめる。何も選んでいない状態なら、そのモード自体を終わる"

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        sc = context.scene
        if sc.lida_hs_on and context.mode == "PAINT_VERTEX":
            hair = _current(context)
            hidden = bool(hair is not None and len(hair.get("lw_hidden", [])))
            if sc.lida_hs_mode != "PICK" or hidden:  # first: back to the plain state (eyedropper, all shown)
                if hidden:
                    ED.set_hidden(hair, [])
                    _trees.clear()
                    sync_list(context, hair)
                sc.lida_hs_mode = "PICK"
                self.report({"INFO"}, T("スポイトに戻しました（もう一度 Esc で、色を直すモードを終わります）"))
            else:
                bpy.ops.kanzashi.stop()
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
                bpy.ops.kanzashi.bend(on=False)
                self.report({"INFO"}, T("曲げるモードを終わりました"))
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        return {"PASS_THROUGH"}


def leave_modes(context):
    """Out of the colour mode and the bend mode, everything shown again as it was."""
    sc = context.scene
    if bending(context):
        end_bend(context)
        sc["lida_hs_bend_keep"] = 0
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
            ED.set_hidden(h, [])
            if ED.HIDE_GROUP in h.modifiers:
                ED.hide_modifier(h, False)
    _trees.clear()


class KANZASHI_OT_quit(bpy.types.Operator):
    bl_idname = "kanzashi.quit"
    bl_label = "ツールを終わる"
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


class KANZASHI_OT_finalize(bpy.types.Operator):
    bl_idname = "kanzashi.finalize"
    bl_label = "曲げた形を確定して仕組みを外す"
    bl_description = "曲げた形をメッシュに書き込み、曲げる仕組み・ワイヤー・結び付けの情報を外します。毛束ごとの色と UV は残ります。確定後にまた曲げるには、検出からやり直します"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        leave_modes(context)
        normal_view(context)
        done = []
        failed = []
        for h in registered(context):
            if not _detected(h):
                continue
            try:
                r = ED.finalize(h, bpy.data.objects.get(h.get("lw_wires", "")))
                done.append(T("%s（最大 %.1f mm）") % (h.name, r["moved_mm"]))
            except Exception as e:
                failed.append(T("%s：%s") % (h.name, e))
        only_hair(context, False)
        context.scene.lida_hs_wires.clear()
        if failed:
            self.report({"ERROR"}, T("確定できなかった物：") + " / ".join(failed))
        self.report({"INFO"}, T("確定しました：") + (T("、").join(done) if done else T("なし")))
        UV.drop_unused_groups()
        return {"FINISHED"}

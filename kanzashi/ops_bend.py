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


class KANZASHI_OT_grip(bpy.types.Operator):
    bl_idname = "kanzashi.grip"
    bl_label = "つまみを動かす／回す"
    bl_description = (
        "つまみを選んでいる間の G（動かす）と R（回す）。最中も、中ボタンのドラッグやホイールで視点を変えられます"
    )
    bl_options = {"REGISTER", "UNDO"}

    kind: bpy.props.EnumProperty(items=[("MOVE", "Move", ""), ("TURN", "Turn", "")], default="MOVE")

    # Blender's own G and R use the middle button for the axis; here it is left to the view, so the hair can be
    # looked at from another side in the middle of a move. Each mouse step is applied with the view as it is then.

    def invoke(self, context, event):
        if not bending(context) or context.mode != "OBJECT" or context.region_data is None:
            return {"PASS_THROUGH"}  # not ours: Blender's own G and R
        names = list(context.scene.get("lida_hs_grips", []))
        self._grips = [g for g in _grips(context) if g.select_get()]
        if not self._grips:
            return {"PASS_THROUGH"}
        self._start = [g.matrix_world.copy() for g in self._grips]
        self._prev = None
        self._axis = None
        self._types = []
        self._nav = False
        if self.kind == "TURN":  # a turned grip must hold its handles itself, or Blender smooths the turn away
            hair = bpy.data.objects.get(context.scene.get("lida_hs_bend_hair", ""))
            k = int(context.scene.get("lida_hs_bend_wire", -1))
            w = _wires(context, hair) if hair is not None else None
            if w is not None and 0 <= k < len(w.data.splines):
                pts = w.data.splines[k].bezier_points
                for g in self._grips:
                    i = names.index(g.name) if g.name in names else -1
                    if 0 <= i < len(pts):
                        self._types.append((pts[i], pts[i].handle_left_type, pts[i].handle_right_type))
                        pts[i].handle_left_type = pts[i].handle_right_type = "ALIGNED"
        self._mouse = (event.mouse_region_x, event.mouse_region_y)
        self._prev = self._mouse
        self._hint(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _hint(self, context):
        if context.area:
            lock = (" [%s]" % "XYZ"[self._axis]) if self._axis is not None else ""
            context.area.header_text_set(
                T("つまみ：クリックで決定、右クリックで取り消し、X・Y・Z で軸、中ボタンで視点") + lock
            )

    def _finish(self, context, cancel):
        if cancel:
            for g, m in zip(self._grips, self._start):
                g.matrix_world = m
            for bp, tl, tr in self._types:
                bp.handle_left_type = tl
                bp.handle_right_type = tr
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        return {"CANCELLED"} if cancel else {"FINISHED"}

    def modal(self, context, event):
        from mathutils import Matrix, Vector

        if event.type == "MIDDLEMOUSE":  # the view is being turned: everything goes to it until the button is up
            self._nav = event.value != "RELEASE"
            self._prev = None  # the next step starts from where the mouse is then
            return {"PASS_THROUGH"}
        if getattr(self, "_nav", False):
            self._prev = None
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"} or event.type.startswith(
            ("NUMPAD_", "NDOF")
        ):
            if event.type == "NUMPAD_ENTER":
                return self._finish(context, False) if event.value == "PRESS" else {"RUNNING_MODAL"}
            self._prev = None
            return {"PASS_THROUGH"}
        if event.type in {"LEFTMOUSE", "RET"} and event.value == "PRESS":
            return self._finish(context, False)
        if event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            return self._finish(context, True)
        if event.type in {"X", "Y", "Z"} and event.value == "PRESS":
            i = "XYZ".index(event.type)
            self._axis = None if self._axis == i else i
            self._hint(context)
            return {"RUNNING_MODAL"}
        if event.type != "MOUSEMOVE":
            return {"RUNNING_MODAL"}
        region = context.region
        rv3d = context.region_data
        now = (event.mouse_region_x, event.mouse_region_y)
        if self._prev is None or region is None or rv3d is None:
            self._prev = now
            return {"RUNNING_MODAL"}
        slow = 0.1 if event.shift else 1.0
        if self.kind == "MOVE":
            c = sum((g.matrix_world.translation for g in self._grips), Vector()) / len(self._grips)
            a = view3d_utils.region_2d_to_location_3d(region, rv3d, self._prev, c)
            b = view3d_utils.region_2d_to_location_3d(region, rv3d, now, c)
            d = (b - a) * slow
            if self._axis is not None:
                ax = Vector([1.0 if j == self._axis else 0.0 for j in range(3)])
                d = ax * d.dot(ax)
            for g in self._grips:
                m = g.matrix_world.copy()
                m.translation = m.translation + d
                g.matrix_world = m
        else:
            view = rv3d.view_rotation @ Vector((0.0, 0.0, 1.0))
            for g in self._grips:
                c = g.matrix_world.translation.copy()
                c2 = view3d_utils.location_3d_to_region_2d(region, rv3d, c)
                if c2 is None:
                    continue
                p0 = Vector(self._prev) - c2
                p1 = Vector(now) - c2
                if p0.length < 2.0 or p1.length < 2.0:
                    continue
                ang = p0.angle_signed(p1) * slow
                if self._axis is not None:
                    ax = Vector([1.0 if j == self._axis else 0.0 for j in range(3)])
                    ang = ang if view.dot(ax) >= 0 else -ang
                else:
                    ax = view
                rot = Matrix.Rotation(-ang, 4, ax)
                g.matrix_world = Matrix.Translation(c) @ rot @ Matrix.Translation(-c) @ g.matrix_world
        self._prev = now
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


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

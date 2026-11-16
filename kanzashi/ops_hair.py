# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Steps 1 and 2: the list of hair meshes, and the detection."""

import bpy
import numpy as np

from . import strand_uv as UV
from . import tree as TR
from .common import (
    T,
    _add,
    _detected,
    _trees,
    _wires,
    flat_colour_view,
    looks_like_hair,
    only_hair,
    registered,
    sync_list,
)


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
        sw = row.row(align=True)
        sw.ui_units_x = 1.6
        sw.prop(item, "color", text="")
        kind = {"base": T("基準"), "branch": T("枝"), "loose": T("部品"), "new": T("新規")}.get(item.kind, item.kind)
        row.label(text=T("%d  %s  %d 面") % (item.wire, kind, item.faces))
        row.operator("lida.hs_solo", text="", icon="RESTRICT_SELECT_OFF", emboss=False).wire = item.wire
        row.operator(
            "lida.hs_eye", text="", icon="HIDE_ON" if item.hidden else "HIDE_OFF", emboss=False
        ).wire = item.wire


class LIDA_OT_hs_auto(bpy.types.Operator):
    bl_idname = "lida.hs_auto"
    bl_label = "髪を自動で登録"
    bl_description = "見えているメッシュのうち、名前か材質の名前から髪と判断した物を登録し、ほかを隠します"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = sum(1 for o in context.view_layer.objects if o.visible_get() and looks_like_hair(o) and _add(context, o))
        if registered(context):
            only_hair(context, True)
        self.report({"INFO"}, T("登録 %d 個（合計 %d 個）。ほかの物は隠しました") % (n, len(registered(context))))
        return {"FINISHED"}


class LIDA_OT_hs_add(bpy.types.Operator):
    bl_idname = "lida.hs_add"
    bl_label = "選んだメッシュを足す"
    bl_options = {"REGISTER", "UNDO"}

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
    bl_idname = "lida.hs_remove"
    bl_label = "登録から外す"
    bl_options = {"REGISTER", "UNDO"}
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        lst = context.scene.lida_hs_list
        if self.index < 0:
            lst.clear()
        elif self.index < len(lst):
            lst.remove(self.index)
        return {"FINISHED"}


class LIDA_OT_hs_isolate(bpy.types.Operator):
    bl_idname = "lida.hs_isolate"
    bl_label = "髪だけ表示"
    bl_description = "登録した髪とそのワイヤー以外を隠す／隠した物を戻す"
    on: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        n = only_hair(context, self.on)
        self.report({"INFO"}, T("隠している物 %d 個") % n)
        return {"FINISHED"}


class LIDA_OT_hs_detect(bpy.types.Operator):
    bl_idname = "lida.hs_detect"
    bl_label = "毛束を検出してワイヤーを作る"
    bl_description = "登録した髪すべてが対象。メッシュを切るので、写しのファイルで行ってください"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if any(_detected(h) for h in registered(context)):  # a second detection throws the edits away: ask
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        hs = registered(context)
        sc = context.scene
        if not hs:
            self.report({"ERROR"}, T("先に ① で髪を登録してください"))
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if sc.lida_hs_autotop:  # the crown: the highest point of the registered hair
            best = None
            for h in hs:
                co = np.empty(len(h.data.vertices) * 3, dtype=np.float32)
                h.data.vertices.foreach_get("co", co)
                w = co.reshape(-1, 3) @ np.array(h.matrix_world)[:3, :3].T + np.array(h.matrix_world)[:3, 3]
                i = int(np.argmax(w[:, 2]))
                if best is None or w[i, 2] > best[2]:
                    best = w[i]
            sc.cursor.location = tuple(float(x) for x in best)
        total = 0
        failed = []
        for hair in hs:
            try:
                st = TR.detect_and_bind(hair, _wires(context, hair), tuple(sc.cursor.location), cap_len=sc.lida_hs_cap)
                total += st["wires"]
                UV.fill_strandless(hair.data)
            except Exception as e:
                failed.append(T("%s：%s") % (hair.name, e))
        UV.drop_unused_groups()
        only_hair(context, True)
        flat_colour_view(context)
        _trees.clear()
        sync_list(context)
        if failed:
            self.report({"ERROR"}, T("失敗した物は曲げる仕組みを外しました。") + " / ".join(failed))
        self.report({"INFO"}, T("髪 %d 個、ワイヤー %d 本") % (len(hs) - len(failed), total))
        return {"FINISHED"}

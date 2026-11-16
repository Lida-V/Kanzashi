# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""The panel of Kanzashi (Sidebar (N) > Kanzashi) and the registration of everything.
Steps: 1 register the hair meshes, 2 find the strands (one wire and one colour per strand), 3 fix wrong colours by
painting, 4 bend by wires, 5 the strand UV, 6 finish."""

import bpy

from . import i18n as LANG
from . import swap as SW
from .common import TOOL, T, _current, _detected, _draw_cursor, _picked_to_add, _row_picked, registered
from .ops_bend import LIDA_OT_hs_bend, LIDA_OT_hs_bend_pick, LIDA_OT_hs_escape, LIDA_OT_hs_finalize, LIDA_OT_hs_quit
from .ops_hair import (
    LIDA_OT_hs_add,
    LIDA_OT_hs_auto,
    LIDA_OT_hs_detect,
    LIDA_OT_hs_isolate,
    LIDA_OT_hs_remove,
    LIDA_UL_hs_wires,
    LidaHsItem,
    LidaHsWire,
)
from .ops_paint import (
    LIDA_OT_hs_eye,
    LIDA_OT_hs_new,
    LIDA_OT_hs_size,
    LIDA_OT_hs_solo,
    LIDA_OT_hs_start,
    LIDA_OT_hs_stop,
    LIDA_OT_hs_stroke,
)
from .ops_uv import LIDA_OT_hs_export, LIDA_OT_hs_uv, LIDA_OT_hs_uvdrop, LIDA_OT_hs_uvshow, LIDA_OT_hs_uvswap

_keys = []  # the keymap items added at registration
_cursor = None  # the handle of the brush circle


class LidaHsFaceTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "PAINT_VERTEX"
    bl_idname = TOOL
    bl_label = "毛束の色"
    bl_description = "スポイトで色を拾い、ブラシで面をその色にします（パネル「Kanzashi」で切り替え。Ctrl+クリックはいつでもスポイト）"
    bl_icon = "brush.paint_vertex.draw"
    bl_keymap = (
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS"}, {"properties": [("pick", False)]}),
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True}, {"properties": [("pick", True)]}),
        ("lida.hs_stroke", {"type": "LEFTMOUSE", "value": "PRESS", "shift": True}, {"properties": [("focus", True)]}),
    )


class LIDA_PT_hs(bpy.types.Panel):
    bl_label = "Kanzashi（かんざし）試作"
    bl_idname = "LIDA_PT_hs"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Kanzashi"

    def draw(self, context):
        lay = self.layout
        sc = context.scene
        row = lay.row(align=True)
        row.alignment = "RIGHT"
        row.prop(context.window_manager, "lida_hs_lang", text="", icon="WORLD")
        hs = registered(context)
        det = [h for h in hs if _detected(h)]
        if sc.get("lida_hs_busy"):
            box = lay.box()
            box.alert = True
            box.label(text=T("処理中（%d %%）。待ってください") % sc.get("lida_hs_busy_pct", 0), icon="TIME")
            box.label(text=sc["lida_hs_busy"])
        hair = _current(context)
        painting = sc.lida_hs_on and context.mode == "PAINT_VERTEX" and _detected(context.active_object)
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
        box = lay.box()
        box.alert = True
        box.label(text=T("次：") + nxt, icon="INFO")

        box = lay.box()
        box.label(text=T("① 対象の髪を決める"), icon="OUTLINER_OB_MESH")
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

        box = lay.box()
        box.label(text=T("② 毛束を検出する"), icon="OUTLINER_OB_CURVES")
        box.enabled = bool(hs)
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

        box = lay.box()
        box.label(text=T("③ 色の違う所を直す"), icon="BRUSH_DATA")
        box.enabled = bool(det)
        if not painting:
            box.operator("lida.hs_start", text=T(LIDA_OT_hs_start._ja[0]), icon="PLAY")
        else:
            box.operator("lida.hs_stop", text=T(LIDA_OT_hs_stop._ja[0]), icon="PAUSE")
            row = box.row(align=True)
            row.scale_y = 1.4
            row.prop_enum(sc, "lida_hs_mode", "PICK", text=T("スポイト"), icon="EYEDROPPER")
            row.prop_enum(sc, "lida_hs_mode", "PAINT", text=T("ブラシ"), icon="BRUSH_DATA")
            row = box.row(align=True)
            row.scale_y = 1.2
            row.prop_enum(
                sc, "lida_hs_mode", "FOCUS", text=T("塗りたい相手をクリック → 2 色だけ表示"), icon="ZOOM_SELECTED"
            )
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

        box = lay.box()
        box.label(text=T("④ ワイヤーで髪を曲げる"), icon="CURVE_BEZCURVE")
        box.enabled = bool(det)
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

        box = lay.box()
        box.label(text=T("⑤ 毛束ごとの UV"), icon="UV")
        box.enabled = bool(det)
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
            swapped = [h.name for h in det if h.get(SW.SWAP_KEY)]
            col = box.column(align=True)
            if swapped:
                col.label(text=T("張り替え済み：%s") % T("、").join(swapped), icon="CHECKMARK")
                if sc.get("lida_hs_swapcheck", ""):
                    col.label(text=sc["lida_hs_swapcheck"])
                col.operator("lida.hs_uvswap", text=T("元の UV・材質に戻す"), icon="LOOP_BACK").on = False
            else:
                col.operator(
                    "lida.hs_uvswap", text=T("この UV に張り替える（見た目はそのまま）"), icon="UV_SYNC_SELECT"
                ).on = True
                col.label(text=T("今のテクスチャを新しい UV へ写します"))
        else:
            box.label(text=T("まだ作っていません"))

        box = lay.box()
        box.label(text=T("⑥ 終わる"), icon="CHECKMARK")
        box.operator("lida.hs_quit", text=T(LIDA_OT_hs_quit._ja[0]), icon="PAUSE")
        box.label(text=T("表示を元に戻す。後で続きができます"))
        if any(h.get(SW.SWAP_KEY) for h in det):
            sub = box.column()
            sub.alert = True
            sub.operator("lida.hs_uvdrop", text=T(LIDA_OT_hs_uvdrop._ja[0]), icon="TRASH")
        sub = box.column()
        sub.enabled = bool(det)
        sub.operator("lida.hs_finalize", text=T(LIDA_OT_hs_finalize._ja[0]), icon="LOCKED")
        sub.label(text=T("形をメッシュに書き込み、ワイヤーを外す"))


CLASSES = (
    LidaHsItem,
    LidaHsWire,
    LIDA_UL_hs_wires,
    LIDA_OT_hs_auto,
    LIDA_OT_hs_add,
    LIDA_OT_hs_remove,
    LIDA_OT_hs_isolate,
    LIDA_OT_hs_detect,
    LIDA_OT_hs_start,
    LIDA_OT_hs_stop,
    LIDA_OT_hs_stroke,
    LIDA_OT_hs_eye,
    LIDA_OT_hs_solo,
    LIDA_OT_hs_new,
    LIDA_OT_hs_size,
    LIDA_OT_hs_bend,
    LIDA_OT_hs_bend_pick,
    LIDA_OT_hs_escape,
    LIDA_OT_hs_quit,
    LIDA_OT_hs_finalize,
    LIDA_OT_hs_uvshow,
    LIDA_OT_hs_uv,
    LIDA_OT_hs_uvswap,
    LIDA_OT_hs_uvdrop,
    LIDA_OT_hs_export,
    LIDA_PT_hs,
)


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
        name="Language",
        description="Language of the Kanzashi panel / パネルの言語",
        items=(
            ("AUTO", "Auto / 自動", "Follows Blender's interface language / Blender の表示言語に合わせる"),
            ("JA", "日本語", "Japanese"),
            ("EN", "English", "English"),
        ),
        default=LANG.choice(),
        update=_lang_changed,
    )
    sc = bpy.types.Scene
    sc.lida_hs_list = bpy.props.CollectionProperty(type=LidaHsItem)
    sc.lida_hs_wires = bpy.props.CollectionProperty(type=LidaHsWire)
    sc.lida_hs_wire_index = bpy.props.IntProperty(default=-1, update=_row_picked)
    sc.lida_hs_hair = bpy.props.PointerProperty(type=bpy.types.Object, poll=lambda s, o: o.type == "MESH")
    sc.lida_hs_cap = bpy.props.FloatProperty(default=0.40, min=0.05, max=2.0, subtype="DISTANCE")
    sc.lida_hs_radius = bpy.props.FloatProperty(
        default=0.008, min=0.001, max=0.2, soft_min=0.001, soft_max=0.04, step=0.05, precision=4, subtype="DISTANCE"
    )
    sc.lida_hs_autotop = bpy.props.BoolProperty(default=True)
    sc.lida_hs_mode = bpy.props.EnumProperty(
        items=(
            ("PICK", T("スポイト"), T("クリックした面の色を拾う")),
            ("PAINT", T("ブラシ"), T("なぞった面を今の色にする")),
            ("FOCUS", T("2 色だけ"), T("クリックした面の色と今の色だけを表示する")),
        ),
        default="PICK",
    )
    sc.lida_hs_on = bpy.props.BoolProperty(default=False)
    sc.lida_hs_pick_add = bpy.props.PointerProperty(
        type=bpy.types.Object, poll=lambda s, o: o.type == "MESH", update=_picked_to_add
    )
    try:
        bpy.utils.register_tool(LidaHsFaceTool, separator=True)
    except Exception as e:
        print("lida hair: the tool could not be registered:", e)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is not None:  # so the click is ours with any toolbar tool, Blender's brushes included
        km = kc.keymaps.new(name="Vertex Paint", space_type="EMPTY")
        for name in ("Object Mode", "3D View"):
            km2 = kc.keymaps.new(name=name, space_type="EMPTY" if name == "Object Mode" else "VIEW_3D")
            for value in ("PRESS",):
                for shift in (False, True):
                    kmi = km2.keymap_items.new("lida.hs_bend_pick", "LEFTMOUSE", value, shift=shift, head=True)
                    _keys.append((km2, kmi))
        for name in ("Vertex Paint", "Object Mode"):
            km3 = kc.keymaps.new(name=name, space_type="EMPTY")
            kmi = km3.keymap_items.new("lida.hs_escape", "ESC", "PRESS", head=True)
            _keys.append((km3, kmi))
        for key, fac in (("LEFT_BRACKET", 0.8), ("RIGHT_BRACKET", 1.25)):
            kmi = km.keymap_items.new("lida.hs_size", key, "PRESS", head=True)
            kmi.properties.factor = fac
            _keys.append((km, kmi))
        for ctrl, shift in ((False, False), (True, False), (False, True)):
            kmi = km.keymap_items.new("lida.hs_stroke", "LEFTMOUSE", "PRESS", ctrl=ctrl, shift=shift, head=True)
            kmi.properties.pick = ctrl
            kmi.properties.focus = shift
            _keys.append((km, kmi))
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

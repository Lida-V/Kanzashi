# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Step 5: the strand UV, its check, the swap, and the export. Slow operators show their progress."""

import bpy

from . import strand_uv as UV
from . import swap as SW
from .common import T, _detected, _wires, bending, registered
from .ops_bend import leave_modes


class _BusyOp:
    """For slow operators: the panel and the status bar say what is going on before the work starts, the mouse
    pointer becomes the waiting one, and the slow steps report as they go. From scripts, execute() just does the work."""

    busy_text = "処理中です"

    def execute(self, context):
        return self.work(context)

    def invoke(self, context, event):
        sc = context.scene
        wm = context.window_manager
        sc["lida_hs_busy"] = T(self.busy_text)
        sc["lida_hs_busy_pct"] = 0
        context.window.cursor_modal_set("WAIT")
        context.workspace.status_text_set(sc["lida_hs_busy"])
        for a in context.screen.areas:
            a.tag_redraw()
        self._ticks = 0
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"RUNNING_MODAL"}  # nothing else gets through while it runs
        self._ticks += 1
        if self._ticks < 3:  # let the panel draw the notice first
            return {"RUNNING_MODAL"}
        wm = context.window_manager
        sc = context.scene
        wm.event_timer_remove(self._timer)
        wm.progress_begin(0, 100)

        def tell(text, share):
            sc["lida_hs_busy"] = text
            sc["lida_hs_busy_pct"] = int(share * 100)
            wm.progress_update(int(share * 100))
            context.workspace.status_text_set(sc["lida_hs_busy"])
            try:
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            except Exception:
                pass
            shot = sc.get("lida_hs_shot")  # for the test of this notice: one picture of the screen
            if shot and share >= 0.3:
                sc["lida_hs_shot"] = ""
                try:
                    bpy.ops.screen.screenshot(filepath=shot)
                except Exception:
                    pass

        UV.PROGRESS = tell
        try:
            return self.work(context)
        finally:
            UV.PROGRESS = None
            wm.progress_end()
            sc["lida_hs_busy"] = ""
            context.window.cursor_modal_restore()
            context.workspace.status_text_set(None)
            for a in context.screen.areas:
                a.tag_redraw()


class LIDA_OT_hs_uvshow(bpy.types.Operator):
    bl_idname = "lida.hs_uvshow"
    bl_label = "作った UV を選ぶ／元の UV に戻す"
    bl_description = "UV エディターに出す UV マップを、毛束ごとの UV（LW_StrandUV）と元の UV の間で切り替えます。描画に使う UV は変えません"
    strand: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        n = 0
        for h in registered(context):
            uvs = h.data.uv_layers
            if self.strand and "LW_StrandUV" in uvs:
                uvs.active = uvs["LW_StrandUV"]
                n += 1
            elif not self.strand:
                first = next((l for l in uvs if l.name != "LW_StrandUV"), None)
                if first is not None:
                    uvs.active = first
                    n += 1
        self.report({"INFO"}, T("切り替えた髪 %d 個") % n)
        return {"FINISHED"}


class LIDA_OT_hs_uv(_BusyOp, bpy.types.Operator):
    bl_idname = "lida.hs_uv"
    bl_label = "毛束ごとの UV を作る"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "毛束ごとの UV を作って検査します。数十秒かかります（進み具合はパネルの上と画面の下に出ます）"
    busy_text = "毛束ごとの UV を作っています"

    def work(self, context):
        hs = [h for h in registered(context) if _detected(h)]
        if not hs:
            self.report({"ERROR"}, T("先に ② の検出を実行してください"))
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        back_on = context.scene.lida_hs_on
        if bending(context) or back_on:
            leave_modes(context)
        made = [UV.strand_uv_auto(h, _wires(context, h)) for h in hs]
        n = sum(r["strips"] for r in made)
        context.scene["lida_hs_uvways"] = T("、").join(T("%s＝%s") % (h.name, r["way"]) for h, r in zip(hs, made))
        UV.pack_together(hs)  # one 0-1 square for all the hairs (one texture)
        UV._tell(T("UV を検査中"), 0.85)
        c = UV.uv_check(hs)
        context.scene["lida_hs_uvcheck"] = _check_text(c)
        self.report({"INFO"}, T("島 %d 個（UV マップ LW_StrandUV。元の UV はそのまま）。%s") % (n, _check_text(c)))
        return {"FINISHED"}


def _check_text(c):
    extra = T("。重なる面 %d・つぶれた面 %d（表面の %.2f %%）") % (
        c.get("folded_faces", 0),
        c.get("squashed_faces", 0),
        c.get("trouble_share", 0) * 100,
    )
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
    bl_idname = "lida.hs_uvswap"
    bl_label = "UV を張り替える"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = (
        "on：髪を毛束ごとの UV で描くように切り替えます。今のテクスチャは新しい UV へ写した画像に置き換わるので、見た目は変わりません"
        "（髪だけが使う材質の写しを作ります。元の UV・材質・画像は残ります）。off：元の UV・材質に戻します"
    )
    on: bpy.props.BoolProperty(default=True)
    busy_text = "UV を張り替えています"

    def work(self, context):
        hs = [h for h in registered(context) if "LW_StrandUV" in h.data.uv_layers]
        if bending(context) or context.scene.lida_hs_on:
            leave_modes(context)
        if not self.on:
            n_ = SW.revert_uv(hs)
            self.report({"INFO"}, T("元の UV・材質に戻しました（髪 %d 個）") % n_)
            return {"FINISHED"}
        if not hs:
            self.report({"ERROR"}, T("先に「毛束ごとの UV を作る」を押してください"))
            return {"CANCELLED"}
        UV._tell(T("UV を検査中"), 0.85)
        c = UV.uv_check(hs)
        context.scene["lida_hs_uvcheck"] = _check_text(c)
        if not c["ok"]:
            self.report({"ERROR"}, _check_text(c) + T("。「毛束ごとの UV を作る」を押し直してください"))
            return {"CANCELLED"}
        r = SW.swap_uv(hs)
        msg = T("張り替えました：髪 %d 個、写した画像 %d 枚、材質の写し %d 個") % (
            r["hairs"],
            r["images"],
            r.get("materials", 0),
        )
        check = ""
        if r.get("triangles"):
            check = T("色の答え合わせ：%d 個中 %d 個の三角形で色が違う（%.2f %%）") % (
                r["triangles"],
                r["differ"],
                100.0 * r["differ"] / r["triangles"],
            )
            msg += T("。") + check
        context.scene["lida_hs_swapcheck"] = check
        if r["skipped"]:
            self.report({"WARNING"}, msg + T("。写せなかった画像：") + T("、").join(r["skipped"]))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class LIDA_OT_hs_uvdrop(bpy.types.Operator):
    bl_idname = "lida.hs_uvdrop"
    bl_label = "古い UV を消す（戻せません）"
    bl_options = {"REGISTER", "UNDO"}
    bl_description = "張り替え済みの髪から、毛束ごとの UV 以外の UV マップを消します。消した後は「元の UV に戻す」は使えません。元の材質と画像は消しません"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        gone = SW.drop_old_uv(registered(context))
        self.report(
            {"INFO"}, T("消した UV：%s") % (T("、").join(gone) if gone else T("なし（張り替え済みの髪がありません）"))
        )
        return {"FINISHED"}


class LIDA_OT_hs_export(bpy.types.Operator):
    bl_idname = "lida.hs_export"
    bl_label = "テクスチャ用に書き出す"
    bl_description = (
        "登録した髪を 1 つのメッシュにまとめ、毛束ごとの UV だけを持たせて FBX（または .glb）で書き出します。"
        "曲げた形で出ます。骨・輪郭線の殻・ほかの UV は入りません。今の髪は変えません"
    )
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.fbx;*.glb", options={"HIDDEN"})

    def invoke(self, context, event):
        import os

        if not self.filepath:
            base = (
                os.path.splitext(bpy.data.filepath)[0]
                if bpy.data.filepath
                else os.path.join(os.path.expanduser("~"), "hair")
            )
            self.filepath = base + "_hair_for_texture.fbx"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        hs = [h for h in registered(context) if _detected(h) and "LW_StrandUV" in h.data.uv_layers]
        if not hs:
            self.report({"ERROR"}, T("先に「毛束ごとの UV を作る」を押してください"))
            return {"CANCELLED"}
        if bending(context) or context.scene.lida_hs_on:
            leave_modes(context)
        UV._tell(T("UV を検査中"), 0.85)
        c = UV.uv_check(hs)
        context.scene["lida_hs_uvcheck"] = _check_text(c)
        if not c["ok"]:
            self.report({"ERROR"}, _check_text(c) + T("。「毛束ごとの UV を作る」を押し直してください"))
            return {"CANCELLED"}
        path = bpy.path.abspath(self.filepath)
        if not path.lower().endswith((".fbx", ".glb")):
            path += ".fbx"
        info = SW.export_for_texture(hs, path)
        mb = info["bytes"] / 1048576.0
        self.report(
            {"WARNING"} if mb > 150 else {"INFO"},
            T("書き出し：%s（%.1f MB、面 %d）%s")
            % (path, mb, info["faces"], T("。150 MB を超えています") if mb > 150 else ""),
        )
        return {"FINISHED"}

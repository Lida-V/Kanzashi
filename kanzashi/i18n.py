# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""The two languages of the panel. The texts in the code are Japanese; EN maps each of them to English.
T(text) gives the text in the language in use: "AUTO" follows Blender's interface language (Japanese when that is
Japanese, English otherwise), "JA" and "EN" fix it. The choice is kept in kanzashi.json in Blender's config folder."""

import json
import os

import bpy

CHOICES = ("AUTO", "JA", "EN")
_choice = None


def _config_path():
    folder = bpy.utils.user_resource("CONFIG")
    return os.path.join(folder, "kanzashi.json") if folder else ""


def choice():
    global _choice
    if _choice is None:
        _choice = "AUTO"
        try:
            with open(_config_path(), encoding="utf-8") as f:
                v = json.load(f).get("language", "AUTO")
            if v in CHOICES:
                _choice = v
        except Exception:
            pass
    return _choice


def set_choice(value, save=True):
    global _choice
    if value not in CHOICES:
        return
    _choice = value
    if not save:
        return
    try:
        path = _config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"language": value}, f)
    except Exception as e:
        print("Kanzashi: the language could not be saved:", e)


def lang():
    c = choice()
    if c == "AUTO":
        return "ja" if (bpy.app.translations.locale or "").lower().startswith("ja") else "en"
    return "ja" if c == "JA" else "en"


def T(text):
    if lang() == "ja":
        return text
    return EN.get(text, text)


EN = {
    # separators
    "、": ", ",
    "。": ". ",
    "%s＝%s": "%s = %s",
    "%s：%s": "%s: %s",
    # the list of colours
    "基準": "base",
    "枝": "branch",
    "部品": "part",
    "新規": "new",
    "%d  %s  %d 面": "%d  %s  %d faces",
    # 1 hair
    "髪を自動で登録": "Register Hair Automatically",
    "見えているメッシュのうち、名前か材質の名前から髪と判断した物を登録し、ほかを隠します": "Registers the visible meshes whose name or material names say hair, and hides the rest",
    "登録 %d 個（合計 %d 個）。ほかの物は隠しました": "Registered %d (%d in total). The other objects are hidden",
    "選んだメッシュを足す": "Add Selected Meshes",
    "足しました：": "Added: ",
    "選んだメッシュはもう登録済みです": "The selected meshes are already registered",
    "メッシュが選ばれていません。下の欄から名前で選んで足すこともできます": "No mesh is selected. You can also add one by name in the field below",
    "登録から外す": "Remove from the List",
    "髪だけ表示": "Show Hair Only",
    "登録した髪とそのワイヤー以外を隠す／隠した物を戻す": "Hides everything but the registered hair and its wires / shows the hidden objects again",
    "隠している物 %d 個": "%d objects hidden",
    # 2 detect
    "毛束を検出してワイヤーを作る": "Detect Strands and Make Wires",
    "登録した髪すべてが対象。メッシュを切るので、写しのファイルで行ってください": "Works on all the registered hair. It cuts the mesh, so do it in a copy of your file",
    "先に ① で髪を登録してください": "Register the hair in step 1 first",
    "失敗した物は曲げる仕組みを外しました。": "The bending setup was removed from the ones that failed. ",
    "髪 %d 個、ワイヤー %d 本": "%d hair meshes, %d wires",
    # 3 repaint
    "色を直すモードに入る": "Start Fixing Colours",
    "髪を色そのままで表示し、スポイトとブラシが使える状態にします": "Shows the hair in flat strand colours and makes the eyedropper and the brush ready",
    "先に ② の検出を実行してください": "Run the detection of step 2 first",
    "色を直すモードを終わる": "Stop Fixing Colours",
    "通常のモードへ戻ります（塗った結果は残ります）": "Goes back to the normal mode (what you painted stays)",
    "毛束の色を塗る": "Paint Strand Colour",
    "スポイト：クリックした面の色を拾う。ブラシ：なぞった面を今の色にして、そのワイヤーへ付け替える": "Eyedropper: picks the colour of the clicked face. Brush: gives the stroked faces the current colour and moves them to that wire",
    "髪の面に当たりませんでした": "No face of the hair was hit",
    "ワイヤー %s と %d だけ表示しています": "Showing only wires %s and %d",
    "検出済みの髪の面に当たりませんでした": "No face of a detected hair was hit",
    "ワイヤー %d の色を拾いました（ブラシに切り替え）": "Picked the colour of wire %d (switched to the brush)",
    "先にスポイトか一覧で色を選んでください": "Choose a colour with the eyedropper or in the list first",
    "付け替えた面 %d": "%d faces moved",
    "この色を隠す／表示する": "Hide / Show This Colour",
    "この色だけ表示する": "Show Only This Colour",
    "新しい色（ワイヤー）を足す": "Add a New Colour (Wire)",
    "新しい色を作ります。その色で面を塗ると、塗った面の真ん中を通るワイヤーが自動で引かれます": "Makes a new colour. When you paint faces with it, a wire through the middle of the painted faces is drawn automatically",
    "新しい色 %d を作りました。この色で面を塗ってください": "Made the new colour %d. Paint faces with it",
    "ブラシの太さを変える": "Change the Brush Size",
    # 4 bend
    "ワイヤーのつまみを出して髪を曲げる": "Show Handles and Bend",
    "選んである色のワイヤーに、丸いつまみを出します。つまみを動かすと、その毛束が付いてきます": "Puts round handles on the wire of the chosen colour. Move a handle and its strand follows",
    "ワイヤー %d のつまみ %d 個を出しました。つまみをクリックして G で動かします": "Wire %d: %d handles are out. Click a handle and move it with G",
    "曲げる毛束を選ぶ": "Choose the Strand to Bend",
    "つまみが出ている間、髪の面をクリックすると、その色のワイヤーのつまみに切り替わります": "While handles are out, clicking a face of the hair switches to the handles of the wire of that colour",
    "ワイヤー %d のつまみに切り替えました": "Switched to the handles of wire %d",
    "一つ戻る／終わる": "Step Back / Finish",
    "Esc：今の道具や絞り込みをやめる。何も選んでいない状態なら、そのモード自体を終わる": "Esc: leaves the current tool or filter. With nothing chosen, it ends the mode itself",
    "スポイトに戻しました（もう一度 Esc で、色を直すモードを終わります）": "Back to the eyedropper (Esc once more stops fixing colours)",
    "色を直すモードを終わりました": "Stopped fixing colours",
    "つまみの選択を外しました（もう一度 Esc で、曲げるモードを終わります）": "Handles deselected (Esc once more ends bending)",
    "曲げるモードを終わりました": "Ended bending",
    # 6 finish
    "ツールを終わる": "Close the Tool",
    "色を直すモード・曲げるモードを終わり、隠した物と面をすべて表示に戻します。曲げる仕組みとワイヤーは残るので、後で続きができます": "Ends the colour-fixing and bending modes and shows all the hidden objects and faces again. The bending setup and the wires stay, so you can go on later",
    "ツールを終わりました（表示を元に戻しました）": "Closed the tool (the view is back to normal)",
    "曲げた形を確定して仕組みを外す": "Apply Shape and Remove Setup",
    "曲げた形をメッシュに書き込み、曲げる仕組み・ワイヤー・結び付けの情報を外します。毛束ごとの色と UV は残ります。確定後にまた曲げるには、検出からやり直します": "Writes the bent shape into the mesh and removes the bending setup, the wires and the binding data. The strand colours and UV stay. To bend again afterwards, start over from the detection",
    "%s（最大 %.1f mm）": "%s (max %.1f mm)",
    "確定できなかった物：": "Could not apply: ",
    "確定しました：": "Applied: ",
    "なし": "none",
    "処理中です": "Working",
    # 5 UV
    "作った UV を選ぶ／元の UV に戻す": "Select the Strand UV / the Original UV",
    "UV エディターに出す UV マップを、毛束ごとの UV（LW_StrandUV）と元の UV の間で切り替えます。描画に使う UV は変えません": "Switches the UV map shown in the UV editor between the strand UV (LW_StrandUV) and the original one. The UV used for rendering is not changed",
    "切り替えた髪 %d 個": "Switched %d hair meshes",
    "毛束ごとの UV を作る": "Make the Strand UV",
    "毛束ごとの UV を作って検査します。数十秒かかります（進み具合はパネルの上と画面の下に出ます）": "Makes a UV map with one island per strand and checks it. Takes tens of seconds (progress is shown at the top of the panel and at the bottom of the window)",
    "毛束ごとの UV を作っています": "Making the strand UV",
    "UV を検査中": "Checking the UV",
    "島 %d 個（UV マップ LW_StrandUV。元の UV はそのまま）。%s": "%d islands (UV map LW_StrandUV; the original UV is untouched). %s",
    "。重なる面 %d・つぶれた面 %d（表面の %.2f %%）": ". Folded faces %d, squashed faces %d (%.2f %% of the surface)",
    "検査 OK：0〜1 の中・島の重なりなし・島の間 %d px 以上": "Check OK: inside 0-1, no overlapping islands, at least %d px between islands",
    "重なる面・つぶれた面が多い（表面の %.1f %%）": "too many folded or squashed faces (%.1f %% of the surface)",
    "0〜1 の外に出ている": "outside 0-1",
    "重なり %d px": "overlap %d px",
    "島が近すぎる所 %d px": "islands too close %d px",
    "検査 NG：": "Check failed: ",
    "UV を張り替える": "Swap the UV",
    "on：髪を毛束ごとの UV で描くように切り替えます。今のテクスチャは新しい UV へ写した画像に置き換わるので、見た目は変わりません"
    "（髪だけが使う材質の写しを作ります。元の UV・材質・画像は残ります）。off：元の UV・材質に戻します": "On: the hair is drawn with the strand UV. The current textures are replaced by images transferred to the new UV, so the look stays the same "
    "(copies of the materials are made for the hair only; the original UV, materials and images stay). Off: back to the original UV and materials",
    "UV を張り替えています": "Swapping the UV",
    "元の UV・材質に戻しました（髪 %d 個）": "Back to the original UV and materials (%d hair meshes)",
    "先に「毛束ごとの UV を作る」を押してください": 'Press "Make the Strand UV" first',
    "。「毛束ごとの UV を作る」を押し直してください": '. Press "Make the Strand UV" again',
    "張り替えました：髪 %d 個、写した画像 %d 枚、材質の写し %d 個": "Swapped: %d hair meshes, %d images transferred, %d material copies",
    "色の答え合わせ：%d 個中 %d 個の三角形で色が違う（%.2f %%）": "Colour check: of %d triangles, %d differ in colour (%.2f %%)",
    "。写せなかった画像：": ". Images that could not be transferred: ",
    "古い UV を消す（戻せません）": "Delete the Old UV (permanent)",
    "張り替え済みの髪から、毛束ごとの UV 以外の UV マップを消します。消した後は「元の UV に戻す」は使えません。元の材質と画像は消しません": 'Deletes every UV map but the strand UV from the swapped hair. After that "Back to original UV & materials" no longer works. The original materials and images are not deleted',
    "消した UV：%s": "Deleted UV maps: %s",
    "なし（張り替え済みの髪がありません）": "none (no hair has been swapped)",
    "テクスチャ用に書き出す": "Export for Texturing",
    "登録した髪を 1 つのメッシュにまとめ、毛束ごとの UV だけを持たせて FBX（または .glb）で書き出します。"
    "曲げた形で出ます。骨・輪郭線の殻・ほかの UV は入りません。今の髪は変えません": "Joins the registered hair into one mesh that has only the strand UV and exports it as FBX (or .glb). "
    "The bent shape is exported. No bones, outline shells or other UV maps. The hair in the scene is not changed",
    "書き出し：%s（%.1f MB、面 %d）%s": "Exported: %s (%.1f MB, %d faces)%s",
    "。150 MB を超えています": ". Larger than 150 MB",
    "毛束の色": "Strand Colour",
    "スポイトで色を拾い、ブラシで面をその色にします（パネル「Kanzashi」で切り替え。Ctrl+クリックはいつでもスポイト）": "Pick a colour with the eyedropper and give faces that colour with the brush (switch in the Kanzashi panel; Ctrl+click is always the eyedropper)",
    # progress of the slow steps
    "UV を展開中（%d 回目）": "Unwrapping (try %d)",
    "重なりとつぶれを調べ中": "Looking for folded and squashed faces",
    "写す位置を計算中": "Working out where to transfer",
    "画像を写し中：%s": "Transferring image: %s",
    "色の答え合わせ中": "Checking the colours",
    # the panel
    "Kanzashi（かんざし）試作": "Kanzashi (prototype)",
    "処理中（%d %%）。待ってください": "Working (%d %%). Please wait",
    "① の「自動で登録」を押す": 'step 1 "Auto register"',
    "② の「毛束を検出」を押す": 'step 2 "Detect strands"',
    "③ の「色を直すモードに入る」（検出はもう不要）": 'step 3 "Start Fixing Colours"',
    "スポイトで、合わせたい色の面をクリック": "pick the wanted colour",
    "色の違う所をなぞる（戻すのは Ctrl+Z）": "stroke wrong faces (undo Ctrl+Z)",
    "次：": "Next: ",
    "① 対象の髪を決める": "1  Choose the hair",
    "自動で登録": "Auto register",
    "選択を足す": "Add selected",
    "（消えた物体）": "(deleted object)",
    "名前で足す": "Add by name",
    "隠した物を戻す": "Show hidden",
    "② 毛束を検出する": "2  Detect the strands",
    "頭頂を自動で決める（いちばん高い点）": "Find the crown automatically",
    "3D カーソルを頭頂に置いてから押す": "First put the 3D cursor on the crown",
    "検出済み：%s": "Detected: %s",
    "続きの編集は、検出せずに ③ へ進む": "To go on editing, go to step 3",
    "もう一度検出すると、塗り直しと": "Detecting again rebuilds everything:",
    "曲げた形が作り直されて消えます": "your repainting and bending are lost",
    "検出をやり直す（確認が出ます）": "Detect again (asks to confirm)",
    "毛束を検出（1 本ごとに色が付く）": "Detect strands (one colour each)",
    "写しのファイルで行う（メッシュを切ります）": "Work in a copy (the mesh is cut)",
    "③ 色の違う所を直す": "3  Fix wrong colours",
    "スポイト": "Eyedropper",
    "ブラシ": "Brush",
    "塗りたい相手をクリック → 2 色だけ表示": "Click a strand: show 2 colours",
    "ブラシの太さ": "Brush size",
    "[ ] キーでも太さを変えられます。面 1 枚が最小です": "[ ] keys also resize. Min: one face",
    "スポイト：面をクリックで色を拾う": "Eyedropper: click a face to pick",
    "ブラシ：なぞった面がその色になる": "Brush: stroked faces get that colour",
    "Ctrl+クリックはいつでもスポイト": "Ctrl+click is always the eyedropper",
    "Shift+クリック：今の色とその色だけ表示": "Shift+click: show those 2 colours",
    "戻す Ctrl+Z／やり直す Ctrl+Shift+Z": "Undo Ctrl+Z / redo Ctrl+Shift+Z",
    "Esc：スポイトへ戻る → もう一度で終わる": "Esc: eyedropper -> again: stop",
    "左のツールバーの筆は使いません": "Don't use the left toolbar brushes",
    "色の一覧（%s）　今の色：%s": "Colours (%s)   current: %s",
    "全部表示": "Show all",
    "新しい色を足す": "Add a colour",
    "行をクリック：その色を選ぶ／目：隠す／矢印：その色だけ": "Row: choose / eye: hide / arrow: solo",
    "④ ワイヤーで髪を曲げる": "4  Bend the hair by wires",
    "押した後、曲げたい毛束の面をクリック": "Then click the strand to bend",
    "ワイヤー %d を曲げています": "Bending wire %d",
    "丸いつまみをクリックして G で動かす": "Click a handle, move it with G",
    "髪の面か一覧をクリック：その毛束に切り替え": "Click hair or list: switch strand",
    "Esc：選択を外す → もう一度で終わる": "Esc: deselect -> again to finish",
    "Shift+クリックで複数選べます": "Shift+click selects several",
    "根元の 5 cm は動きません（その先が曲がる）": "The root 5 cm stays put",
    "色の一覧の目・矢印で、見せる毛束を絞れます": "List eye/arrow: limit what shows",
    "曲げ終わる（つまみを消す）": "Finish bending (remove handles)",
    "⑤ 毛束ごとの UV": "5  UV per strand",
    "数十秒かかります（進み具合が上に出ます）": "Takes tens of seconds",
    "作成済み：%s": "Made: %s",
    "UV マップ名は LW_StrandUV（元の UV はそのまま）": "UV map: LW_StrandUV (original kept)",
    "作った UV を選ぶ": "Strand UV",
    "元の UV に戻す": "Original UV",
    "検査 OK": "Check OK",
    "髪を 1 つにまとめ、この UV だけで FBX に出す": "One mesh, this UV only, as FBX",
    "張り替え済み：%s": "Swapped: %s",
    "元の UV・材質に戻す": "Back to original UV & materials",
    "この UV に張り替える（見た目はそのまま）": "Swap to this UV (same look)",
    "今のテクスチャを新しい UV へ写します": "Textures move to the new UV",
    "まだ作っていません": "Not made yet",
    "⑥ 終わる": "6  Finish",
    "表示を元に戻す。後で続きができます": "Restores the view; continue later",
    "形をメッシュに書き込み、ワイヤーを外す": "Bakes the shape, removes wires",
    "クリックした面の色を拾う": "Picks the colour of the clicked face",
    "なぞった面を今の色にする": "Gives the stroked faces the current colour",
    "2 色だけ": "2 colours",
    "クリックした面の色と今の色だけを表示する": "Shows only the colour of the clicked face and the current one",
}

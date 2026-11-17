"""Draws the figures of the README: docs/fig_*.ja.svg and docs/fig_*.en.svg.

    python tools/make_figures.py

The figures are schematic drawings made by this script (no model, no screenshot).
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs")
N = chr(10)

FONT = "'Segoe UI','Hiragino Sans','Yu Gothic UI','Meiryo','Noto Sans JP','Noto Sans CJK JP',sans-serif"
INK = "#2b2733"
SUB = "#6a6475"
LINE = "#d9d3e3"
CARD = "#ffffff"
BG = "#f7f5fb"
ACCENT = "#7a4b8c"
GREY = "#b9b4c4"
PAL = ["#9ad3a0", "#b7a2ee", "#f2c078", "#7fc8d6", "#ee9db8", "#c7dd7a", "#a9b8f0"]
HAIR = [
    (-70, 150, 34, -40),
    (-45, 190, 36, -25),
    (-18, 210, 38, -8),
    (10, 215, 38, 6),
    (38, 195, 36, 24),
    (64, 160, 34, 42),
]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, weight="normal", anchor="start", fill=INK):
    return '<text x="%g" y="%g" font-size="%g" font-weight="%s" text-anchor="%s" fill="%s">%s</text>' % (
        x,
        y,
        size,
        weight,
        anchor,
        fill,
        esc(s),
    )


def lines(x, y, rows, size=12, gap=None, anchor="start", fill=SUB, weight="normal"):
    gap = gap or size * 1.45
    return "".join(text(x, y + i * gap, r, size, weight, anchor, fill) for i, r in enumerate(rows))


def rect(x, y, w, h, fill=CARD, stroke=LINE, r=10, sw=1.2, extra=""):
    return '<rect x="%g" y="%g" width="%g" height="%g" rx="%g" fill="%s" stroke="%s" stroke-width="%g" %s/>' % (
        x,
        y,
        w,
        h,
        r,
        fill,
        stroke,
        sw,
        extra,
    )


def strand(x, y, length, width, sway, fill, stroke="none", sw=1.0, extra=""):
    """A tapered lock: root at (x, y), tip at (x + sway, y + length)."""
    my = y + length * 0.6
    d = "M%g,%g Q%g,%g %g,%g Q%g,%g %g,%gZ" % (
        x - width / 2,
        y,
        x - width * 0.6 + sway * 0.3,
        my,
        x + sway,
        y + length,
        x + width * 0.6 + sway * 0.3,
        my,
        x + width / 2,
        y,
    )
    return '<path d="%s" fill="%s" stroke="%s" stroke-width="%g" stroke-linejoin="round" %s/>' % (
        d,
        fill,
        stroke,
        sw,
        extra,
    )


def wire_pt(x, y, length, sway, t):
    cx, cy = x + sway * 0.3, y + length * 0.6
    ex, ey = x + sway, y + length * 0.97
    u = 1 - t
    return (u * u * x + 2 * u * t * cx + t * t * ex, u * u * y + 2 * u * t * cy + t * t * ey)


def wire(x, y, length, sway, color=INK, sw=1.4, dots=4):
    s = '<path d="M%g,%g Q%g,%g %g,%g" fill="none" stroke="%s" stroke-width="%g" stroke-linecap="round"/>' % (
        x,
        y,
        x + sway * 0.3,
        y + length * 0.6,
        x + sway,
        y + length * 0.97,
        color,
        sw,
    )
    for i in range(dots):
        px, py = wire_pt(x, y, length, sway, (i + 0.5) / dots)
        s += '<circle cx="%g" cy="%g" r="2.1" fill="%s"/>' % (px, py, color)
    return s


def hair(cx, y, colored, scale=1.0, wires=True):
    s = '<circle cx="%g" cy="%g" r="%g" fill="#ece8f1" stroke="%s" stroke-dasharray="4 4"/>' % (
        cx,
        y + 52 * scale,
        56 * scale,
        LINE,
    )
    order = [0, 5, 1, 4, 2, 3]
    for i in order:
        dx, ln, w, sway = HAIR[i]
        x0, y0 = cx + dx * 0.55 * scale, y + abs(dx) * 0.22 * scale
        if colored:
            s += strand(x0, y0, ln * scale, w * scale, sway * scale, PAL[i], "#ffffff", 1.2)
        else:
            s += strand(x0, y0, ln * scale, w * scale, sway * scale, GREY, GREY, 1.5)
    if colored and wires:
        for i in order:
            dx, ln, w, sway = HAIR[i]
            s += wire(
                cx + dx * 0.55 * scale, y + abs(dx) * 0.22 * scale + 4, ln * scale, sway * scale, sw=1.2 * scale, dots=3
            )
    return s


def arrow(x1, y1, x2, y2, color=ACCENT, sw=2.4):
    return (
        '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g" stroke-linecap="round" marker-end="url(#ah)"/>'
        % (x1, y1, x2 - 3, y2, color, sw)
    )


def check(cx, cy, r=11, color="#3fa56a"):
    return (
        '<circle cx="%g" cy="%g" r="%g" fill="%s"/><path d="M%g,%g l%g,%g l%g,%g" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
        % (cx, cy, r, color, cx - r * 0.45, cy, r * 0.32, r * 0.36, r * 0.6, -r * 0.7)
    )


def svg(w, h, body, title):
    head = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" font-family="%s" role="img" aria-label="%s">'
        % (w, h, w, h, FONT, esc(title))
    )
    defs = (
        '<defs><marker id="ah" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="%s"/></marker></defs>' % ACCENT
    )
    return head + N + defs + N + rect(1, 1, w - 2, h - 2, BG, LINE, 14) + N + body + N + "</svg>" + N


def chip(x, y, w, title, sub, icon=""):
    return rect(x, y, w, 72) + icon + text(x + 62, y + 29, title, 15, "bold") + lines(x + 62, y + 49, sub, 11.5)


# ---------------------------------------------------------------- figures


def fig_overview(t):
    b = hair(170, 40, False)
    b += text(170, 282, t["ov_before"], 14, "bold", "middle") + text(
        170, 303, t["ov_before2"], 12, "normal", "middle", SUB
    )
    b += text(322, 132, "Kanzashi", 14, "bold", "middle", ACCENT) + arrow(285, 148, 362, 148)
    b += hair(480, 40, True)
    b += text(480, 282, t["ov_after"], 14, "bold", "middle") + text(
        480, 303, t["ov_after2"], 12, "normal", "middle", SUB
    )
    x, w = 662, 280
    ic1 = (
        strand(x + 22, 96 - 60 + 12, 44, 14, 0, PAL[0])
        + strand(x + 38, 48, 44, 14, 0, PAL[1])
        + '<rect x="%g" y="62" width="14" height="12" fill="%s"/>' % (x + 31, PAL[0])
        + '<circle cx="%g" cy="68" r="11" fill="none" stroke="%s" stroke-width="1.6" stroke-dasharray="3 3"/>'
        % (x + 38, INK)
    )
    ic2 = (
        strand(x + 22, 128, 46, 16, 18, PAL[3])
        + wire(x + 22, 130, 46, 18, dots=0)
        + '<rect x="%g" y="150" width="8" height="8" fill="#fff" stroke="%s" stroke-width="1.6"/>' % (x + 26, ACCENT)
    )
    ic3 = '<rect x="%g" y="208" width="42" height="42" fill="#fff" stroke="%s"/>' % (x + 10, SUB)
    for i, (dx, hh) in enumerate([(5, 34), (15, 26), (25, 30), (34, 20)]):
        ic3 += strand(x + 10 + dx, 212, hh, 7, 0, PAL[i])
    b += chip(x, 36, w, t["c_paint"], t["c_paint2"], ic1)
    b += chip(x, 116, w, t["c_bend"], t["c_bend2"], ic2)
    b += chip(x, 196, w, t["c_uv"], t["c_uv2"], ic3)
    return svg(960, 325, b, t["ov_title"])


def fig_steps(t):
    b = ""
    cw, gap, x0 = 146, 10, 17
    for i in range(6):
        x = x0 + i * (cw + gap)
        cx = x + cw / 2
        b += rect(x, 18, cw, 214)
        b += '<circle cx="%g" cy="44" r="13" fill="%s"/>' % (x + 24, ACCENT) + text(
            x + 24, 49, str(i + 1), 14, "bold", "middle", "#fff"
        )
        b += text(x + 44, 49, t["s%d" % (i + 1)], 14, "bold")
        y = 72
        if i == 0:
            for dx, sw_ in ((-16, -10), (0, 0), (16, 10)):
                b += strand(cx + dx * 0.6, y, 80, 20, sw_, GREY, GREY, 1.5)
            b += check(cx + 30, y + 70)
        elif i == 1:
            for k, (dx, sw_) in enumerate(((-16, -10), (0, 0), (16, 10))):
                b += strand(cx + dx * 0.6, y, 80, 20, sw_, PAL[k], "#fff", 1.2)
            for dx, sw_ in ((-16, -10), (0, 0), (16, 10)):
                b += wire(cx + dx * 0.6, y + 3, 80, sw_, dots=3, sw=1.2)
        elif i == 2:
            for r in range(5):
                wrong = r in (2, 3)
                b += '<rect x="%g" y="%g" width="24" height="16" fill="%s" stroke="#fff"/>' % (
                    cx - 25,
                    y + r * 16,
                    PAL[0],
                )
                b += '<rect x="%g" y="%g" width="24" height="16" fill="%s" stroke="#fff"/>' % (
                    cx + 1,
                    y + r * 16,
                    PAL[0] if wrong else PAL[1],
                )
            b += (
                '<circle cx="%g" cy="%g" r="17" fill="none" stroke="%s" stroke-width="1.8" stroke-dasharray="4 3"/>'
                % (cx + 13, y + 48, INK)
            )
            b += '<circle cx="%g" cy="%g" r="6" fill="%s" stroke="%s" stroke-width="1.4"/>' % (
                cx + 38,
                y + 70,
                PAL[1],
                INK,
            )
        elif i == 3:
            b += strand(cx - 14, y, 84, 22, 0, "none", SUB, 1.2, 'stroke-dasharray="4 3"')
            b += strand(cx - 14, y, 84, 22, 34, PAL[3], "#fff", 1.2) + wire(cx - 14, y + 3, 84, 34, dots=0)
            hx, hy = wire_pt(cx - 14, y + 3, 84, 34, 0.72)
            b += '<rect x="%g" y="%g" width="10" height="10" fill="#fff" stroke="%s" stroke-width="2"/>' % (
                hx - 5,
                hy - 5,
                ACCENT,
            )
            b += arrow(hx - 26, hy + 4, hx - 8, hy + 1, sw=2)
        elif i == 4:
            b += '<rect x="%g" y="%g" width="84" height="84" fill="#fff" stroke="%s"/>' % (cx - 42, y, SUB)
            for k, (dx, hh) in enumerate([(-30, 72), (-14, 56), (2, 66), (18, 44), (32, 60)]):
                b += strand(cx + dx, y + 6, hh, 11, 0, PAL[k])
        else:
            b += strand(cx - 6, y, 82, 24, 22, PAL[4], "#fff", 1.2)
            b += check(cx + 30, y + 70)
        b += lines(cx, 186, t["s%db" % (i + 1)], 11, 16, "middle")
    return svg(960, 250, b, t["st_title"])


def fig_edit(t):
    b = rect(18, 18, 456, 296) + rect(486, 18, 456, 296)
    b += text(38, 48, t["p_title"], 15, "bold")
    for k, (gx, lab) in enumerate(((84, t["before"]), (290, t["after"]))):
        for r in range(7):
            wrong = k == 0 and r in (2, 3, 4)
            b += '<rect x="%g" y="%g" width="40" height="24" fill="%s" stroke="#fff" stroke-width="1.5"/>' % (
                gx,
                74 + r * 24,
                PAL[0],
            )
            b += '<rect x="%g" y="%g" width="40" height="24" fill="%s" stroke="#fff" stroke-width="1.5"/>' % (
                gx + 41,
                74 + r * 24,
                PAL[0] if wrong else PAL[1],
            )
            b += '<rect x="%g" y="%g" width="40" height="24" fill="%s" stroke="#fff" stroke-width="1.5"/>' % (
                gx + 82,
                74 + r * 24,
                PAL[2],
            )
        b += text(gx + 61, 262, lab, 12.5, "bold", "middle", SUB)
    b += '<circle cx="145" cy="134" r="27" fill="none" stroke="%s" stroke-width="2" stroke-dasharray="5 4"/>' % INK
    b += arrow(222, 158, 276, 158)
    b += lines(38, 286, t["p_cap"], 12)
    b += text(506, 48, t["b_title"], 15, "bold")
    x, y, ln = 640, 70, 190
    b += strand(x, y, ln, 44, 0, "none", SUB, 1.3, 'stroke-dasharray="5 4"')
    b += strand(x, y, ln, 44, 96, PAL[3], "#fff", 1.4) + wire(x, y + 4, ln, 96, dots=0, sw=1.8)
    for tt in (0.25, 0.48, 0.7, 0.9):
        hx, hy = wire_pt(x, y + 4, ln, 96, tt)
        sel = tt == 0.7
        s = 7 if sel else 4.5
        b += '<rect x="%g" y="%g" width="%g" height="%g" fill="%s" stroke="%s" stroke-width="2"/>' % (
            hx - s,
            hy - s,
            s * 2,
            s * 2,
            "#fff",
            ACCENT if sel else INK,
        )
        if sel:
            b += arrow(hx - 48, hy + 10, hx - 13, hy + 3)
    b += '<path d="M%g,%g h-10 v34 h10" fill="none" stroke="%s" stroke-width="1.6"/>' % (x - 34, y, INK)
    b += lines(x - 52, y + 14, t["b_root"], 11.5, 15, "end", INK)
    b += text(x - 22, 236, t["before"], 11.5, "normal", "end", SUB) + text(
        x + 112, 262, t["after"], 11.5, "bold", "start", SUB
    )
    b += lines(506, 286, t["b_cap"], 12)
    return svg(960, 332, b, t["ed_title"])


def fig_uv(t):
    b = hair(150, 44, True, 0.92, False)
    b += text(150, 286, t["uv_3d"], 13, "bold", "middle")
    b += arrow(270, 150, 330, 150)
    ux, uy, us = 352, 34, 224
    b += '<rect x="%g" y="%g" width="%g" height="%g" fill="#fff" stroke="%s" stroke-width="1.4"/>' % (
        ux,
        uy,
        us,
        us,
        SUB,
    )
    for k in range(1, 4):
        b += '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s"/>' % (
            ux + k * us / 4,
            uy,
            ux + k * us / 4,
            uy + us,
            "#eeeaf4",
        )
        b += '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s"/>' % (
            ux,
            uy + k * us / 4,
            ux + us,
            uy + k * us / 4,
            "#eeeaf4",
        )
    for i, (dx, hh, ww) in enumerate(
        [(22, 150, 28), (56, 190, 30), (92, 205, 32), (128, 205, 32), (164, 190, 30), (198, 150, 28)]
    ):
        b += strand(ux + dx, uy + 10, hh, ww, 0, PAL[i], "#ffffff", 1)
    b += text(ux - 6, uy + us + 4, "0", 11, "normal", "end", SUB) + text(
        ux + us + 5, uy + us + 4, "1", 11, "normal", "start", SUB
    )
    b += text(ux - 6, uy + 9, "1", 11, "normal", "end", SUB)
    b += text(ux + us / 2, 286, t["uv_map"], 13, "bold", "middle") + text(
        ux + us / 2, 306, t["uv_map2"], 11.5, "normal", "middle", SUB
    )
    x, w = 640, 300
    ic1 = check(x + 31, 71, 14)
    ic2 = (
        '<path d="M%g,137 v22 m-9,-9 l9,9 l9,-9 M%g,166 h30" fill="none" stroke="%s" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>'
        % (x + 31, x + 16, ACCENT)
    )
    ic3 = (
        '<rect x="%g" y="214" width="22" height="22" fill="%s" stroke="%s"/><rect x="%g" y="228" width="22" height="22" fill="%s" stroke="%s"/>'
        % (x + 14, PAL[2], SUB, x + 28, PAL[1], SUB)
    )
    b += chip(x, 36, w, t["u_check"], t["u_check2"], ic1)
    b += chip(x, 116, w, t["u_export"], t["u_export2"], ic2)
    b += chip(x, 196, w, t["u_swap"], t["u_swap2"], ic3)
    return svg(960, 325, b, t["uv_title"])


def fig_flow(t):
    b = text(30, 40, t["f_place"], 15, "bold")
    xs, w = (30, 340, 650), 280
    for i, x in enumerate(xs):
        on = i == 1
        b += rect(x, 56, w, 74, ACCENT if on else CARD, ACCENT if on else LINE)
        b += text(x + w / 2, 87, t["f_p%d" % (i + 1)], 15, "bold", "middle", "#fff" if on else INK)
        b += text(x + w / 2, 110, t["f_p%db" % (i + 1)], 11.5, "normal", "middle", "#f1e6f6" if on else SUB)
        if i < 2:
            b += arrow(x + w + 4, 93, x + w + 28, 93)
    b += text(30, 178, t["f_ways"], 15, "bold")
    for i, x in enumerate(xs):
        b += rect(x, 194, w, 92)
        b += '<circle cx="%g" cy="222" r="13" fill="%s"/>' % (x + 26, PAL[(1, 3, 0)[i]])
        b += text(x + 26, 227, "ABC"[i], 13, "bold", "middle", INK)
        b += text(x + 48, 227, t["f_w%d" % (i + 1)], 14.5, "bold")
        b += lines(x + 18, 252, t["f_w%db" % (i + 1)], 11.5, 17)
    return svg(960, 304, b, t["fl_title"])


JA = {
    "ov_title": "Kanzashi のあらまし",
    "ov_before": "生成した髪",
    "ov_before2": "ひとかたまりのメッシュ。毛束を選べない",
    "ov_after": "毛束ごとの色とワイヤー",
    "ov_after2": "1 本ずつ選べる・直せる・曲げられる",
    "c_paint": "塗って直す",
    "c_paint2": ["分かれ方の違う面をなぞって、", "正しい毛束へ付け替える"],
    "c_bend": "ワイヤーで曲げる",
    "c_bend2": ["つまみを動かすと、", "毛束がワイヤーに沿って曲がる"],
    "c_uv": "毛束ごとの UV",
    "c_uv2": ["1 毛束 = 1 島。", "テクスチャの作り直しに使う"],
    "st_title": "パネルの 6 つの段",
    "s1": "髪を登録",
    "s1b": ["髪のメッシュを", "名前と材質から登録"],
    "s2": "毛束を検出",
    "s2b": ["毛束に分けて、", "色とワイヤーを付ける"],
    "s3": "色を直す",
    "s3b": ["スポイトで色を拾い、", "ブラシで面を塗り直す"],
    "s4": "曲げる",
    "s4b": ["つまみを動かして", "毛束を曲げる"],
    "s5": "毛束の UV",
    "s5b": ["1 毛束 = 1 島。検査・", "書き出し・張り替え"],
    "s6": "終わる",
    "s6b": ["表示を戻す／", "形をメッシュに確定"],
    "ed_title": "塗って直す・ワイヤーで曲げる",
    "before": "直す前",
    "after": "直した後",
    "p_title": "③ 色の違う所を直す",
    "p_cap": ["塗った面が、その色の毛束に付け替わります。", "Ctrl+Z で戻せます。"],
    "b_title": "④ ワイヤーで髪を曲げる",
    "b_root": ["根元の 5 cm は", "動かない"],
    "b_cap": ["つまみを動かすと、毛束がワイヤーに沿って曲がります。", "メッシュの形は、確定するまで書き換えません。"],
    "uv_title": "毛束ごとの UV",
    "uv_3d": "毛束に分けた髪",
    "uv_map": "毛束ごとの UV",
    "uv_map2": "1 毛束 = 1 島。0〜1 に詰める",
    "u_check": "検査",
    "u_check2": ["はみ出し・島の重なり・", "つぶれた面を調べる"],
    "u_export": "書き出し",
    "u_export2": ["この UV だけを持つ髪を FBX／GLB に。", "テクスチャの作り直しへ"],
    "u_swap": "張り替え",
    "u_swap2": ["今のテクスチャを新しい UV へ写す。", "元に戻すこともできる"],
    "fl_title": "工程の位置と 3 つの使い方",
    "f_place": "制作の流れの中の位置",
    "f_p1": "頭と髪のパーツ分け",
    "f_p1b": "髪を頭と別のメッシュにする",
    "f_p2": "Kanzashi",
    "f_p2b": "検出 → 塗り直し → 曲げ → 毛束ごとの UV",
    "f_p3": "髪のテクスチャの貼り直し",
    "f_p3b": "毛束ごとの UV で作る",
    "f_ways": "3 つの使い方",
    "f_w1": "パネル（アドオン）",
    "f_w1b": ["Blender のサイドバーで、", "人が見ながら操作する"],
    "f_w2": "スクリプト",
    "f_w2b": ["パネルなしの背景実行。", "検出・UV・確認用の画像"],
    "f_w3": "スキル（AI エージェント）",
    "f_w3b": ["エージェントが手順を進め、", "要所でユーザーに確認する"],
}
EN = {
    "ov_title": "What Kanzashi does",
    "ov_before": "Generated hair",
    "ov_before2": "one fused mesh; no strand can be picked",
    "ov_after": "One colour and one wire per strand",
    "ov_after2": "pick, fix and bend strand by strand",
    "c_paint": "Fix by painting",
    "c_paint2": ["paint the faces that were split wrongly", "onto the right strand"],
    "c_bend": "Bend by wire",
    "c_bend2": ["move a handle and the strand", "follows its wire"],
    "c_uv": "UV per strand",
    "c_uv2": ["one island per strand,", "ready for new textures"],
    "st_title": "The six steps of the panel",
    "s1": "Register",
    "s1b": ["hair meshes are found", "by name and material"],
    "s2": "Detect",
    "s2b": ["split into strands,", "a colour and a wire each"],
    "s3": "Fix colours",
    "s3b": ["pick a colour,", "paint the faces"],
    "s4": "Bend",
    "s4b": ["move a handle,", "the strand bends"],
    "s5": "Strand UV",
    "s5b": ["one island per strand;", "check, export, swap"],
    "s6": "Finish",
    "s6b": ["restore the view /", "apply the shape"],
    "ed_title": "Fixing by painting and bending by wire",
    "before": "before",
    "after": "after",
    "p_title": "3  Fix wrong colours",
    "p_cap": ["Painted faces move to the strand of that colour.", "Ctrl+Z undoes it."],
    "b_title": "4  Bend the hair by wires",
    "b_root": ["the 5 cm at the", "root stay put"],
    "b_cap": ["Move a handle and the strand follows its wire.", "The mesh itself is not rewritten until you apply."],
    "uv_title": "UV per strand",
    "uv_3d": "Hair split into strands",
    "uv_map": "UV per strand",
    "uv_map2": "one island each, packed into 0-1",
    "u_check": "Check",
    "u_check2": ["out of range, overlapping islands,", "squashed faces"],
    "u_export": "Export",
    "u_export2": ["the hair with this UV only, as FBX / GLB,", "to make new textures"],
    "u_swap": "Swap",
    "u_swap2": ["transfer the current textures to the", "new UV; can be reverted"],
    "fl_title": "Place in the pipeline and three ways to use it",
    "f_place": "Place in the pipeline",
    "f_p1": "Split head and hair",
    "f_p1b": "the hair becomes a mesh of its own",
    "f_p2": "Kanzashi",
    "f_p2b": "detect → repaint → bend → UV per strand",
    "f_p3": "Redo the hair texture",
    "f_p3b": "on the UV per strand",
    "f_ways": "Three ways to use it",
    "f_w1": "Panel (add-on)",
    "f_w1b": ["in Blender's sidebar;", "you work while looking"],
    "f_w2": "Scripts",
    "f_w2b": ["headless, no panel: detection,", "UV, pictures for checking"],
    "f_w3": "Skill (AI agent)",
    "f_w3b": ["the agent runs the steps and", "asks you at the key points"],
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for lang, t in (("ja", JA), ("en", EN)):
        for name, fn in (
            ("overview", fig_overview),
            ("steps", fig_steps),
            ("edit", fig_edit),
            ("uv", fig_uv),
            ("flow", fig_flow),
        ):
            p = os.path.join(OUT, "fig_%s.%s.svg" % (name, lang))
            with open(p, "w", encoding="utf-8", newline=N) as f:
                f.write(fn(t))
            print(os.path.relpath(p, ROOT))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Kanzashi: finds the strands of a generated hair mesh, lets you fix them by painting, bends them by wires
and makes a UV map per strand. Sidebar (N) > Kanzashi.

Importing this package registers nothing; register() does. The modules that only compute can be used from scripts
without the panel (scripts/kanzashi_run.py)."""

bl_info = {
    "name": "Kanzashi",
    "author": "Lida",
    "version": (0, 4, 2),
    "blender": (5, 3, 0),
    "location": "3D Viewport > Sidebar (N) > Kanzashi",
    "description": "Hair strands of generated meshes: detect, repaint, bend by wires, UV per strand",
    "category": "Mesh",
}


def register():
    from . import panel

    panel.register()


def unregister():
    from . import panel

    panel.unregister()

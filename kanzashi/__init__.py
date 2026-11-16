# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Kanzashi: finds the strands of a generated hair mesh, lets you fix them by painting, bends them by wires
and makes a UV map per strand. Sidebar (N) > Kanzashi."""

bl_info = {
    "name": "Kanzashi",
    "author": "Lida",
    "version": (0, 1, 0),
    "blender": (5, 3, 0),
    "location": "3D Viewport > Sidebar (N) > Kanzashi",
    "description": "Hair strands of generated meshes: detect, repaint, bend by wires, UV per strand",
    "category": "Mesh",
}

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:               # the modules of this prototype import each other by plain name
    sys.path.insert(0, _HERE)

from . import panel  # noqa: E402


def register():
    panel.register()


def unregister():
    panel.unregister()

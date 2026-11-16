# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Shows the Kanzashi panel for this session only, without installing the add-on:

    blender model.blend --python scripts/kanzashi_panel.py

The package "kanzashi" is looked for next to this file and one folder up (the repository)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "..")):
    if os.path.isfile(os.path.join(cand, "kanzashi", "panel.py")):
        sys.path.insert(0, os.path.abspath(cand))
        break
import kanzashi  # noqa: E402

kanzashi.register()

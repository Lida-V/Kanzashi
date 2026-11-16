# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Builds the two packages into dist/ :
    Kanzashi-addon-<version>.zip    the Blender add-on (install from disk)
    Kanzashi-scripts-<version>.zip  the core modules and the script that runs without the panel
Run: python tools/build_packages.py"""
import hashlib
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
CORE = ("lida_hair_tree.py", "lida_hair_strands.py", "lida_hair_rewire.py", "lida_hair_wire.py")
FIXED = (2026, 1, 1, 0, 0, 0)


def put(z, arc, path):
    info = zipfile.ZipInfo(arc, FIXED); info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o644 << 16
    z.writestr(info, open(path, "rb").read())


def build(name, entries):
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", name)
    with zipfile.ZipFile(out, "w") as z:
        for arc, path in sorted(entries):
            put(z, arc, path)
    sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
    open(out + ".sha256", "w", encoding="utf-8", newline="\n").write("%s  %s\n" % (sha, name))
    print(name, os.path.getsize(out), sha)


addon = [("kanzashi/" + f, os.path.join(ROOT, "kanzashi", f)) for f in sorted(os.listdir(os.path.join(ROOT, "kanzashi"))) if f.endswith(".py")]
addon += [("kanzashi/LICENSE", os.path.join(ROOT, "LICENSE")), ("kanzashi/README.md", os.path.join(ROOT, "README.md"))]
build("Kanzashi-addon-%s.zip" % VERSION, addon)

top = "Kanzashi-scripts-%s/" % VERSION
scripts = [(top + "kanzashi_run.py", os.path.join(ROOT, "scripts", "kanzashi_run.py"))]
scripts += [(top + "kanzashi_core/" + f, os.path.join(ROOT, "kanzashi", f)) for f in CORE]
scripts += [(top + "LICENSE", os.path.join(ROOT, "LICENSE")), (top + "README.md", os.path.join(ROOT, "README.md"))]
build("Kanzashi-scripts-%s.zip" % VERSION, scripts)

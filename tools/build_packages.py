# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Builds the two packages into dist/ :
    Kanzashi-addon-<version>.zip    the Blender add-on (Preferences > Add-ons > Install from Disk)
    Kanzashi-scripts-<version>.zip  the script that runs without the panel, with the package it needs
The same input gives the same bytes. Run: python tools/build_packages.py"""

import hashlib
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
FIXED = (2026, 1, 1, 0, 0, 0)
DOCS = ("LICENSE", "README.md", "README.en.md")


def put(z, arc, path):
    info = zipfile.ZipInfo(arc, FIXED)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    data = open(path, "rb").read()
    if not arc.endswith((".jpg", ".png")):
        data = data.replace(b"\r\n", b"\n")  # the same bytes whatever the line endings of the checkout
    z.writestr(info, data)


def build(name, entries):
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
    out = os.path.join(ROOT, "dist", name)
    with zipfile.ZipFile(out, "w") as z:
        for arc, path in sorted(entries):
            put(z, arc, path)
    sha = hashlib.sha256(open(out, "rb").read()).hexdigest()
    open(out + ".sha256", "w", encoding="utf-8", newline="\n").write("%s  %s\n" % (sha, name))
    print(name, os.path.getsize(out), sha)


def package(prefix):
    folder = os.path.join(ROOT, "kanzashi")
    files = sorted(f for f in os.listdir(folder) if f.endswith((".py", ".toml")))
    return [(prefix + "kanzashi/" + f, os.path.join(folder, f)) for f in files]


def check_versions():
    init = open(os.path.join(ROOT, "kanzashi", "__init__.py"), encoding="utf-8").read()
    manifest = open(os.path.join(ROOT, "kanzashi", "blender_manifest.toml"), encoding="utf-8").read()
    want = '"version": (%s)' % ", ".join(VERSION.split("."))
    if want not in init or 'version = "%s"' % VERSION not in manifest:
        raise SystemExit("VERSION, kanzashi/__init__.py and blender_manifest.toml do not agree on %s" % VERSION)


check_versions()
build("Kanzashi-addon-%s.zip" % VERSION, package("") + [("kanzashi/" + d, os.path.join(ROOT, d)) for d in DOCS])
top = "Kanzashi-scripts-%s/" % VERSION
scripts = [(top + n, os.path.join(ROOT, "scripts", n)) for n in ("kanzashi_run.py", "kanzashi_guard.py")]
build("Kanzashi-scripts-%s.zip" % VERSION, scripts + package(top) + [(top + d, os.path.join(ROOT, d)) for d in DOCS])

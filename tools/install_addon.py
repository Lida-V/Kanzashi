# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Installs the Kanzashi add-on of this repository into Blender, or tells whether it is installed.

    python tools/install_addon.py --check          {"installed": true/false, "version": "...", "repo_version": "..."}
    python tools/install_addon.py                  builds the ZIP and installs it as an extension (enabled)
    python tools/install_addon.py --blender PATH   when Blender is not found by itself

Installing changes the user's Blender: ask them first. Nothing else is touched."""

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
CHECK = (
    "import addon_utils, json;"
    "m=[x for x in addon_utils.modules() if x.__name__.split('.')[-1]=='kanzashi'];"
    "v=addon_utils.module_bl_info(m[0]).get('version') if m else None;"
    "print('KANZASHI_CHECK '+json.dumps(dict(installed=bool(m), module=m[0].__name__ if m else None,"
    "version='.'.join(str(i) for i in v) if v else None,"
    "enabled=bool(m) and addon_utils.check(m[0].__name__)[1])))"
)


def find_blender(given):
    cands = [given, os.environ.get("BLENDER"), shutil.which("blender")]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", ""), "D:/Program Files", "C:/Program Files"):
            cands.append(os.path.join(base, "blender.exe"))
            root = os.path.join(base, "Blender Foundation")
            if os.path.isdir(root):
                for d in sorted(os.listdir(root), reverse=True):
                    cands.append(os.path.join(root, d, "blender.exe"))
    else:
        cands += ["/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def check(blender):
    r = subprocess.run([blender, "-b", "--python-expr", CHECK], capture_output=True, text=True, errors="replace")
    for line in r.stdout.splitlines():
        if line.startswith("KANZASHI_CHECK "):
            out = json.loads(line[len("KANZASHI_CHECK ") :])
            out["repo_version"] = VERSION
            out["up_to_date"] = out.get("version") == VERSION
            return out
    return dict(installed=False, error="Blender gave no answer", repo_version=VERSION)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", help="path of the Blender executable")
    ap.add_argument("--check", action="store_true", help="only tell whether the add-on is installed")
    a = ap.parse_args()
    blender = find_blender(a.blender)
    if blender is None:
        print(json.dumps(dict(ok=False, error="Blender not found; give --blender PATH")))
        return 1
    if a.check:
        print(json.dumps(dict(ok=True, blender=blender, **check(blender))))
        return 0
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "build_packages.py")], capture_output=True, text=True
    )
    if r.returncode:
        print(json.dumps(dict(ok=False, error="building the ZIP failed", detail=r.stdout[-400:] + r.stderr[-400:])))
        return 1
    zip_path = os.path.join(ROOT, "dist", "Kanzashi-addon-%s.zip" % VERSION)
    r = subprocess.run(
        [blender, "--command", "extension", "install-file", "-r", "user_default", "-e", zip_path],
        capture_output=True,
        text=True,
        errors="replace",
    )
    state = check(blender)
    ok = r.returncode == 0 and state.get("installed") and state.get("up_to_date")
    print(json.dumps(dict(ok=bool(ok), blender=blender, zip=zip_path, **state)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

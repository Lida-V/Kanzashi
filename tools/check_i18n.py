# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Every Japanese text of the add-on has an English one with the same % fields, and no English text is unused.

Run: python tools/check_i18n.py   (exit code 1 when something is wrong)"""

import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAPANESE = re.compile("[\\u3040-\\u30ff\\u4e00-\\u9fff\\uff00-\\uffef]")
FIELD = re.compile(r"%(?:\.\d+)?[sdf%]")
# words that are looked for in object names, and a marker that is compared as it is
NOT_TEXTS = {"髪", "前髪", "毛", "飾", "検査 OK", "日本語"}


def english_table():
    src = open(os.path.join(ROOT, "kanzashi", "i18n.py"), encoding="utf-8").read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "EN":
            return ast.literal_eval(node.value)
    raise SystemExit("EN not found in kanzashi/i18n.py")


def main():
    en = english_table()
    used = set()
    bad = []
    for path in sorted(glob.glob(os.path.join(ROOT, "kanzashi", "*.py"))):
        name = os.path.basename(path)
        if name == "i18n.py":
            continue
        for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and JAPANESE.search(node.value)):
                continue
            s = node.value
            if s in NOT_TEXTS or "\n" in s or " / " in s:  # docstrings and labels that are bilingual on purpose
                continue
            used.add(s)
            if s not in en:
                bad.append(("no English", name, s[:60]))
            elif sorted(FIELD.findall(s)) != sorted(FIELD.findall(en[s])):
                bad.append(("% fields differ", name, s[:60]))
            elif not en[s].isascii():
                bad.append(("English is not ASCII", name, en[s][:60]))
    unused = [k for k in en if k not in used and k not in ("、", "。")]  # the separators
    print("texts", len(used), "English", len(en), "problems", len(bad), "unused", len(unused))
    for b in bad:
        print(" ", *b)
    for u in unused:
        print("  unused:", u[:60])
    return 1 if bad or unused else 0


if __name__ == "__main__":
    sys.exit(main())

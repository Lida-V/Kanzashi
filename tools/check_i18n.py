# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""Run: python tools/check_i18n.py
Every Japanese text of the panel has an English one with the same % fields; no English text is unused."""
import ast, re, sys
import os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JP = re.compile(r'[぀-ヿ一-鿿]')
SPEC = re.compile(r'%(?:\.\d+)?[sdf%]')
src = open(root + '/kanzashi/lida_hair_i18n.py', encoding='utf-8').read()
EN = None
for node in ast.parse(src).body:
    if isinstance(node, ast.Assign) and node.targets[0].id == 'EN':
        EN = ast.literal_eval(node.value)
used = set(); bad = []
for f in ('panel.py', 'lida_hair_tree.py'):
    tree = ast.parse(open(root + '/kanzashi/' + f, encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and JP.search(node.value):
            s = node.value
            if s in ('髪', '前髪', '毛', '飾', '検査 OK') or '\n' in s or 'パネルの言語' in s or s == '日本語' or '自動' in s and '/' in s or 'Blender の表示言語' in s and '/' in s:
                continue
            used.add(s)
            if s not in EN:
                bad.append(('NO EN', f, s[:60]))
            elif sorted(SPEC.findall(s)) != sorted(SPEC.findall(EN[s])):
                bad.append(('SPEC', f, s[:60]))
            if not EN.get(s, 'x').isascii():
                bad.append(('NOT ASCII', f, EN[s][:60]))
unused = [k for k in EN if k not in used and k not in ('、', '。', '%s＝%s', '%s：%s', '検査 OK')]
print('texts', len(used), 'EN', len(EN), 'problems', len(bad), 'unused', len(unused))
for b in bad: print(b)
for u in unused: print('UNUSED', u[:60])
sys.exit(1 if bad else 0)

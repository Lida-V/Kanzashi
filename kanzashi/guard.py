# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
"""A mark on a hair that has the strand UV, and a check that the hair is still as it was when the UV was made.
Another tool that separates the hair into parts again, joins it, or unwraps it again breaks the strand UV; the mark
lets that be seen before the hair goes on to texturing."""

import hashlib
import json
import uuid

import numpy as np

KEY = "kanzashi_uv_lock"
UV_NAME = "LW_StrandUV"


def fingerprint(hair):
    me = hair.data
    out = dict(faces=len(me.polygons), verts=len(me.vertices), uv=None)
    layer = me.uv_layers.get(UV_NAME)
    if layer is not None:
        uv = np.empty(len(me.loops) * 2, dtype=np.float32)
        layer.data.foreach_get("uv", uv)
        out["uv"] = hashlib.sha1(np.round(uv, 5).tobytes()).hexdigest()[:16]
    return out


def mark(hairs):
    """Call after the strand UV was made (and packed): remembers what the hair is like now."""
    for h in hairs:
        h[KEY] = json.dumps(dict(id=uuid.uuid4().hex[:12], name=h.name, **fingerprint(h)))


def read(ob):
    try:
        return json.loads(ob.get(KEY, ""))
    except Exception:
        return None


def quick(hair):
    """Cheap enough for the panel: None when fine or not marked, else a short reason."""
    m = read(hair)
    if m is None:
        return None
    me = hair.data
    if UV_NAME not in me.uv_layers:
        return "uv_missing"
    if len(me.polygons) != m["faces"] or len(me.vertices) != m["verts"]:
        return "changed"
    return None


def check(objects):
    """Every marked mesh among `objects`: ok / split / changed / uv_changed / uv_missing."""
    marked = [(o, read(o)) for o in objects if o.type == "MESH" and read(o) is not None]
    by_id = {}
    for o, m in marked:
        by_id.setdefault(m["id"], []).append(o.name)
    res = []
    for o, m in marked:
        now = fingerprint(o)
        if len(by_id[m["id"]]) > 1:
            status = "split"  # separated objects all carry the mark of the one they came from
        elif now["uv"] is None:
            status = "uv_missing"
        elif now["faces"] != m["faces"] or now["verts"] != m["verts"]:
            status = "changed"
        elif now["uv"] != m["uv"]:
            status = "uv_changed"
        else:
            status = "ok"
        res.append(
            dict(
                object=o.name,
                marked_as=m.get("name"),
                status=status,
                faces=[m["faces"], now["faces"]],
                verts=[m["verts"], now["verts"]],
                pieces=by_id[m["id"]] if status == "split" else None,
            )
        )
    return dict(ok=all(r["status"] == "ok" for r in res), marked=len(res), hairs=res)

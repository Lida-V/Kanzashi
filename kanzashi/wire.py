# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Lida
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Lida
# Prototype: hair strands from guide wires, fitted to an existing (generated) hair mesh.
#   - ensure_group():   geometry-node group that turns a curve into a strand (flat -> tube -> pointed tip)
#   - trace_strand():   from one point on an existing strand, follow it and return centre line + section sizes
#   - fit_polyline():   re-centre a drawn line on the existing strand and read section sizes
#   - make_wire():      build the editable curve object with the modifier
# Importing this file registers nothing and changes nothing.
import math

import numpy as np

GROUP = "LidaHairWire"
PRESETS = {
    # flat/tube = thickness / width at root side and tip side; start/end = where the change happens (0..1)
    # tip = share of the length that narrows; power > 1 keeps the width longer and closes quickly; root = width at the root
    "bangs": dict(flat=0.12, tube=0.30, start=0.55, end=1.0, tip=0.50, bow=0.30, power=2.4, root=0.85),
    "side": dict(flat=0.20, tube=0.55, start=0.30, end=0.85, tip=0.35, bow=0.15, power=2.0, root=0.8),
    "back": dict(flat=0.35, tube=0.85, start=0.15, end=0.70, tip=0.22, bow=0.05, power=1.5, root=1.0),
}
PRESET_INPUTS = (("flat", "Flat Ratio"), ("tube", "Tube Ratio"), ("start", "Tube Start"), ("end", "Tube End"),
                 ("tip", "Tip Length"), ("bow", "Bow"), ("power", "Tip Power"), ("root", "Root Width"))
SOCKETS = [  # name, type, default, min, max
    ("Width Scale", "NodeSocketFloat", 1.0, 0.05, 5.0),
    ("Flat Ratio", "NodeSocketFloat", 0.22, 0.02, 1.5),
    ("Tube Ratio", "NodeSocketFloat", 0.60, 0.02, 1.5),
    ("Tube Start", "NodeSocketFloat", 0.30, 0.0, 1.0),
    ("Tube End", "NodeSocketFloat", 0.85, 0.0, 1.0),
    ("Tip Length", "NodeSocketFloat", 0.25, 0.01, 1.0),
    ("Bow", "NodeSocketFloat", 0.15, -1.0, 1.0),
    ("Trim Root", "NodeSocketFloat", 0.0, 0.0, 1.0),
    ("Trim Tip", "NodeSocketFloat", 1.0, 0.0, 1.0),
    ("Rings", "NodeSocketInt", 48, 4, 400),
    ("Sides", "NodeSocketInt", 12, 4, 64),
    ("Avoid", "NodeSocketCollection", None, None, None),
    ("Avoid On", "NodeSocketBool", True, None, None),
    ("Clearance", "NodeSocketFloat", 0.004, 0.0, 0.2),
    ("Material", "NodeSocketMaterial", None, None, None),
    ("Tip Power", "NodeSocketFloat", 1.5, 0.3, 6.0),
    ("Tip Side", "NodeSocketFloat", 0.0, -1.0, 1.0),   # which edge the point ends on: that edge stays straight
    ("Root Width", "NodeSocketFloat", 1.0, 0.05, 2.0),
    ("Lift", "NodeSocketFloat", 0.0, 0.0, 0.05),       # extra distance from the head: strands on an upper layer
]


# ----------------------------------------------------------------------------- numpy part
def weld(points, tris, tol=1e-5):
    key = np.round(points / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return points[first], inv.reshape(-1)[tris]


def frame_of(t):
    t = t / np.linalg.norm(t)
    a = np.array([0.0, 0.0, 1.0]) if abs(t[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    e1 = np.cross(t, a); e1 /= np.linalg.norm(e1)
    return e1, np.cross(t, e1)


def slice_section(P, T, c, t, window):
    """Cut triangles (P[T]) by the plane through c with normal t. Return the connected piece nearest to c."""
    t = t / np.linalg.norm(t)
    tri = P[T]
    near = np.linalg.norm(tri.mean(axis=1) - c, axis=1) < window * 1.8
    idx = np.nonzero(near)[0]
    if not len(idx):
        return None
    tri = tri[idx]; ti = T[idx]
    d = (tri - c) @ t
    cross = (d.min(axis=1) < 0) & (d.max(axis=1) >= 0)
    tri, ti, d = tri[cross], ti[cross], d[cross]
    if not len(tri):
        return None
    seg_p, seg_k = [], []
    for k in range(len(tri)):
        pts, keys = [], []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            da, db = d[k, a], d[k, b]
            if (da < 0) != (db < 0):
                s = da / (da - db)
                pts.append(tri[k, a] + (tri[k, b] - tri[k, a]) * s)
                va, vb = int(ti[k, a]), int(ti[k, b])
                keys.append((min(va, vb), max(va, vb)))
        if len(pts) == 2:
            seg_p.append(pts); seg_k.append(keys)
    if not seg_p:
        return None
    seg_p = np.array(seg_p)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for ka, kb in seg_k:
        parent[find(ka)] = find(kb)
    comp = np.array([hash(find(k[0])) for k in seg_k])
    mid = seg_p.mean(axis=1)
    dist = np.linalg.norm(mid - c, axis=1)
    pick = comp == comp[int(np.argmin(dist))]
    sp = seg_p[pick]
    ends = sp.reshape(-1, 3)
    saturated = bool(np.linalg.norm(ends - c, axis=1).max() > window)
    ln = np.linalg.norm(sp[:, 1] - sp[:, 0], axis=1) + 1e-12
    m = sp.mean(axis=1)
    centre = (m * ln[:, None]).sum(axis=0) / ln.sum()
    e1, e2 = frame_of(t)
    q = np.stack([(ends - centre) @ e1, (ends - centre) @ e2], axis=1)
    cov = q.T @ q / len(q)
    w, v = np.linalg.eigh(cov)
    major = v[:, 1]
    minor = np.array([-major[1], major[0]])
    a = q @ major; b = q @ minor
    hw = float((a.max() - a.min()) * 0.5); ht = float((b.max() - b.min()) * 0.5)
    # centre of the bounding box in the section frame is steadier than the length-weighted mean for open cards
    centre = centre + (e1 * major[0] + e2 * major[1]) * (a.max() + a.min()) * 0.5 \
        + (e1 * minor[0] + e2 * minor[1]) * (b.max() + b.min()) * 0.5
    verts = sorted({v for keys, use in zip(seg_k, pick) if use for key in keys for v in key})
    return dict(centre=centre, major=e1 * major[0] + e2 * major[1], hw=hw, ht=ht, saturated=saturated,
                near=float(dist.min()), verts=verts)


def local_axis(P, T, c, radius):
    """Axis of a strand near c: the direction the surface normals avoid."""
    tri = P[T]
    near = np.linalg.norm(tri.mean(axis=1) - c, axis=1) < radius
    tri = tri[near]
    if len(tri) < 4:
        return None
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    w, v = np.linalg.eigh(n.T @ n)
    return v[:, 0]


def trace_strand(P, T, seed, window=0.03, step=0.008, max_steps=400, min_hw=0.0012):
    """Follow the strand through seed in both directions. Returns stations ordered as traced (not yet root->tip)."""
    axis = local_axis(P, T, seed, window)
    if axis is None:
        return []
    first = slice_section(P, T, seed, axis, window)
    if first is None:
        return []

    def march(direction):
        out = []; c = first["centre"].copy(); d = direction.copy(); sat = 0
        for _ in range(max_steps):
            s = slice_section(P, T, c + d * step, d, window)
            if s is None or s["near"] > max(window * 0.5, step * 2):
                out.append(dict(centre=c + d * step * 0.6, major=None, hw=0.0, ht=0.0, saturated=False, end="tip"))
                break
            if s["saturated"]:
                sat += 1
                if sat >= 2:
                    break
            else:
                sat = 0
            nd = s["centre"] - c
            ln = np.linalg.norm(nd)
            if ln < step * 0.25 or float(nd @ d) <= 0:
                break
            d = (d * 0.35 + nd / ln * 0.65); d /= np.linalg.norm(d)
            c = s["centre"]; out.append(s)
            if s["hw"] < min_hw:
                out.append(dict(centre=c + d * step * 0.6, major=None, hw=0.0, ht=0.0, saturated=False, end="tip"))
                break
        return out
    fwd = march(axis); back = march(-axis)
    return back[::-1] + [first] + fwd


def fit_polyline(P, T, pts, window=0.03, step=0.006):
    """Re-centre a drawn polyline on the strand under it and read section sizes."""
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1); cum = np.concatenate([[0], np.cumsum(seg)])
    n = max(4, int(cum[-1] / step))
    s = np.linspace(0, cum[-1], n)
    q = np.stack([np.interp(s, cum, pts[:, k]) for k in range(3)], axis=1)
    out = []
    for i in range(n):
        t = q[min(i + 1, n - 1)] - q[max(i - 1, 0)]
        r = slice_section(P, T, q[i], t, window)
        if r is None or r["near"] > window * 0.6 or r["saturated"]:
            # nothing to read here (no strand, or strands melted into one sheet): keep the drawn point
            out.append(dict(centre=q[i], major=None, hw=0.0, ht=0.0, saturated=False, miss=True))
        else:
            out.append(r)
    return out


def stations_to_points(stations, spacing=0.025, default_hw=0.006):
    """Reduce stations to control points: (positions, half widths, majors, summary)."""
    c = np.array([s["centre"] for s in stations])
    hw = np.array([s["hw"] for s in stations]); ht = np.array([s["ht"] for s in stations])
    bad = np.array([s.get("saturated", False) or s.get("miss", False) for s in stations])
    good = (~bad) & (hw > 0)
    ref = float(np.median(hw[good])) if good.any() else default_hw
    hw_use = np.where(good, hw, np.where(hw > 0, np.minimum(hw, ref), ref))
    k = 5  # median filter
    pad = np.pad(hw_use, k // 2, mode="edge")
    hw_use = np.array([np.median(pad[i:i + k]) for i in range(len(hw_use))])
    seg = np.linalg.norm(np.diff(c, axis=0), axis=1); cum = np.concatenate([[0], np.cumsum(seg)])
    m = max(4, int(round(cum[-1] / spacing)) + 1)
    s = np.linspace(0, cum[-1], m)
    pos = np.stack([np.interp(s, cum, c[:, k2]) for k2 in range(3)], axis=1)
    rad = np.interp(s, cum, hw_use)
    idx = np.clip(np.searchsorted(cum, s), 0, len(stations) - 1)
    majors = [stations[i]["major"] for i in idx]
    ratio = np.where(good & (hw > 1e-5), ht / np.maximum(hw, 1e-5), np.nan)
    u = cum / max(cum[-1], 1e-9)

    def med(lo, hi, fallback):
        r = ratio[(u >= lo) & (u <= hi)]; r = r[~np.isnan(r)]
        return float(np.clip(np.median(r), 0.05, 1.2)) if len(r) else fallback
    summary = dict(length=float(cum[-1]), flat=med(0.0, 0.35, 0.25), tube=med(0.55, 0.9, 0.6),
                   width_median=ref, stations=len(stations), not_read=int(bad.sum()))
    return pos, rad, majors, summary


# ----------------------------------------------------------------------------- Blender part
def gather_triangles(objs, depsgraph):
    """World-space welded triangles of evaluated mesh objects."""
    pts, tris, off = [], [], 0
    for o in objs:
        ev = o.evaluated_get(depsgraph); me = ev.to_mesh()
        me.calc_loop_triangles()
        v = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", v); v = v.reshape(-1, 3)
        m = np.array(o.matrix_world)
        v = v @ m[:3, :3].T + m[:3, 3]
        t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64); me.loop_triangles.foreach_get("vertices", t)
        pts.append(v); tris.append(t.reshape(-1, 3) + off); off += len(v)
        ev.to_mesh_clear()
    return weld(np.concatenate(pts), np.concatenate(tris))


def make_envelope(obj, collection, smooth=20, grow=0.003, name=None):
    """A smooth closed stand-in for a bumpy or open surface (a generated head with hair on it):
    a sphere wrapped onto it from outside, then smoothed. Use it as the Avoid target so wires do not
    follow every groove. The source object is not changed."""
    import bpy, bmesh
    from mathutils import Vector
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector([min(v[i] for v in bb) for i in range(3)]); hi = Vector([max(v[i] for v in bb) for i in range(3)])
    me = bpy.data.meshes.new(name or ("LWenv_" + obj.name))
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=5, radius=1.0); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(me.name, me); collection.objects.link(o)
    o.location = (lo + hi) / 2; o.scale = (hi - lo) * 0.5 * 1.5
    w = o.modifiers.new("wrap", "SHRINKWRAP"); w.target = obj; w.wrap_method = "NEAREST_SURFACEPOINT"
    s = o.modifiers.new("smooth", "SMOOTH"); s.factor = 0.5; s.iterations = smooth
    g = o.modifiers.new("grow", "DISPLACE"); g.strength = grow; g.mid_level = 0.0  # smoothing shrinks: push back out
    for p in me.polygons:
        p.use_smooth = True
    o.display_type = "WIRE"; o.hide_render = True
    return o


def ensure_group():
    import bpy
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
    itf = g.interface
    itf.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    itf.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for name, typ, default, lo, hi in SOCKETS:
        s = itf.new_socket(name, in_out="INPUT", socket_type=typ)
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value = lo; s.max_value = hi
    N = g.nodes; L = g.links
    gin = N.new("NodeGroupInput"); gout = N.new("NodeGroupOutput")

    def I(name):
        return gin.outputs[name]

    def link(a, b):
        L.new(a, b)

    def val(x):
        return x if hasattr(x, "node") or hasattr(x, "is_output") else None

    def put(sock, x):
        if hasattr(x, "is_output"):
            link(x, sock)
        else:
            sock.default_value = x

    def math_(op, a, b=None, c=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        put(n.inputs[0], a)
        if b is not None:
            put(n.inputs[1], b)
        if c is not None:
            put(n.inputs[2], c)
        return n.outputs[0]

    def vmath(op, a, b=None, scale=None):
        n = N.new("ShaderNodeVectorMath"); n.operation = op
        put(n.inputs[0], a)
        if b is not None:
            put(n.inputs[1], b)
        if scale is not None:
            put(n.inputs["Scale"], scale)
        return n.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else n.outputs["Vector"]

    def node(kind, **props):
        n = N.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def smooth01(x, lo, hi):  # smoothstep((x-lo)/(hi-lo))
        t = math_("DIVIDE", math_("SUBTRACT", x, lo), math_("MAXIMUM", math_("SUBTRACT", hi, lo), 1e-4))
        n = N.new("ShaderNodeClamp"); put(n.inputs[0], t)
        t = n.outputs[0]
        return math_("MULTIPLY", math_("MULTIPLY", t, t), math_("SUBTRACT", 3.0, math_("MULTIPLY", 2.0, t)))

    # 1 resample and trim
    rs = node("GeometryNodeResampleCurve")
    link(gin.outputs["Geometry"], rs.inputs["Curve"]); link(I("Rings"), rs.inputs["Count"])
    tr = node("GeometryNodeTrimCurve")
    link(rs.outputs["Curve"], tr.inputs["Curve"])
    link(I("Trim Root"), tr.inputs["Start"]); link(I("Trim Tip"), tr.inputs["End"])
    geo = tr.outputs["Curve"]

    # 2 sizes along the wire (fields on the trimmed curve)
    u = node("GeometryNodeSplineParameter").outputs["Factor"]
    radius = node("GeometryNodeInputRadius").outputs["Radius"]
    s_tip = math_("DIVIDE", math_("SUBTRACT", u, math_("SUBTRACT", 1.0, I("Tip Length"))), I("Tip Length"))
    cl = N.new("ShaderNodeClamp"); put(cl.inputs[0], s_tip)
    taper = math_("SUBTRACT", 1.0, math_("POWER", cl.outputs[0], I("Tip Power")))   # 1 ... 0 at the very end: pointed
    rootf = math_("ADD", I("Root Width"), math_("MULTIPLY", smooth01(u, 0.0, 0.3), math_("SUBTRACT", 1.0, I("Root Width"))))
    full = math_("MULTIPLY", math_("MULTIPLY", radius, I("Width Scale")), rootf)
    hw = math_("MULTIPLY", full, taper)
    side = math_("MULTIPLY", math_("MULTIPLY", I("Tip Side"), full), math_("SUBTRACT", 1.0, taper))
    mix = smooth01(u, I("Tube Start"), I("Tube End"))
    ratio = math_("ADD", I("Flat Ratio"), math_("MULTIPLY", mix, math_("SUBTRACT", I("Tube Ratio"), I("Flat Ratio"))))
    ht = math_("MULTIPLY", hw, ratio)

    # 3 keep clear of the body (twice: a blurred lead-in, then exact), and read the outward direction
    ci = node("GeometryNodeCollectionInfo", transform_space="RELATIVE")
    link(I("Avoid"), ci.inputs["Collection"])
    rl = node("GeometryNodeRealizeInstances"); link(ci.outputs[0], rl.inputs["Geometry"])
    body = rl.outputs["Geometry"]
    pos = node("GeometryNodeInputPosition").outputs["Position"]

    def outward():
        px = node("GeometryNodeProximity", target_element="FACES")
        link(body, px.inputs[0])
        sn = node("GeometryNodeSampleNearestSurface", data_type="FLOAT_VECTOR")
        link(body, sn.inputs["Mesh"]); link(node("GeometryNodeInputNormal").outputs["Normal"], sn.inputs["Value"])
        nn = sn.outputs["Value"]
        diff = vmath("SUBTRACT", pos, px.outputs["Position"])
        sgn = math_("SIGN", math_("ADD", vmath("DOT_PRODUCT", diff, nn), 1e-7))
        s = vmath("NORMALIZE", vmath("ADD", vmath("SCALE", diff, scale=sgn), vmath("SCALE", nn, scale=1e-5)))
        return s, math_("MULTIPLY", px.outputs["Distance"], sgn)

    def push(geometry, blur):
        s, sd = outward()
        need = math_("ADD", math_("ADD", I("Clearance"), I("Lift")), ht)
        delta = math_("MAXIMUM", math_("SUBTRACT", need, sd), 0.0)
        sw = node("GeometryNodeSwitch", input_type="FLOAT")
        link(I("Avoid On"), sw.inputs[0]); sw.inputs[1].default_value = 0.0; link(delta, sw.inputs[2])
        off = vmath("SCALE", s, scale=sw.outputs[0])
        if blur:
            b = node("GeometryNodeBlurAttribute", data_type="FLOAT_VECTOR")
            link(off, b.inputs["Value"]); b.inputs["Iterations"].default_value = blur
            off = b.outputs["Value"]
        sp = node("GeometryNodeSetPosition")
        link(geometry, sp.inputs["Geometry"]); link(off, sp.inputs["Offset"])
        return sp.outputs["Geometry"]
    geo = push(geo, 8)
    geo = push(geo, 2)
    geo = push(geo, 0)

    # 4 capture what the mesh needs from the wire
    s_dir, _ = outward()
    bl = node("GeometryNodeBlurAttribute", data_type="FLOAT_VECTOR")
    link(s_dir, bl.inputs["Value"]); bl.inputs["Iterations"].default_value = 10
    tan = node("GeometryNodeInputTangent").outputs["Tangent"]
    w0 = vmath("NORMALIZE", vmath("CROSS_PRODUCT", tan, vmath("NORMALIZE", bl.outputs["Value"])))
    n0 = vmath("CROSS_PRODUCT", w0, tan)
    tilt = node("GeometryNodeInputCurveTilt").outputs["Tilt"]
    co, si = math_("COSINE", tilt), math_("SINE", tilt)
    wdir = vmath("ADD", vmath("SCALE", w0, scale=co), vmath("SCALE", n0, scale=si))
    ndir = vmath("SUBTRACT", vmath("SCALE", n0, scale=co), vmath("SCALE", w0, scale=si))
    cap = node("GeometryNodeCaptureAttribute", domain="POINT")
    names = [("P", "VECTOR", pos), ("W", "VECTOR", wdir), ("Nn", "VECTOR", ndir), ("hw", "FLOAT", hw),
             ("ht", "FLOAT", ht), ("u", "FLOAT", u), ("side", "FLOAT", side)]
    for nm, typ, _src in names:
        cap.capture_items.new(typ, nm)
    link(geo, cap.inputs["Geometry"])
    for nm, typ, src in names:
        link(src, cap.inputs[nm])
    C = {nm: cap.outputs[nm] for nm, _t, _s in names}
    sr = node("GeometryNodeSetCurveRadius"); link(cap.outputs["Geometry"], sr.inputs["Curve"]); sr.inputs["Radius"].default_value = 1.0

    # 5 profile: unit circle carrying its own coordinates
    circ = node("GeometryNodeCurvePrimitiveCircle"); link(I("Sides"), circ.inputs["Resolution"]); circ.inputs["Radius"].default_value = 1.0
    pc = node("GeometryNodeCaptureAttribute", domain="POINT"); pc.capture_items.new("VECTOR", "prof")
    link(circ.outputs["Curve"], pc.inputs["Geometry"]); link(node("GeometryNodeInputPosition").outputs["Position"], pc.inputs["prof"])
    c2m = node("GeometryNodeCurveToMesh")
    link(sr.outputs["Curve"], c2m.inputs["Curve"]); link(pc.outputs["Geometry"], c2m.inputs["Profile Curve"])
    c2m.inputs["Fill Caps"].default_value = True

    # 6 place every vertex: centre + width direction * x + outward direction * (y * thickness - bow)
    sep = node("ShaderNodeSeparateXYZ"); link(pc.outputs["prof"], sep.inputs[0])
    px_, py_ = sep.outputs["X"], sep.outputs["Y"]
    across = vmath("SCALE", C["W"], scale=math_("ADD", math_("MULTIPLY", px_, C["hw"]), C["side"]))
    bow = math_("MULTIPLY", math_("MULTIPLY", I("Bow"), C["hw"]), math_("SUBTRACT", math_("MULTIPLY", px_, px_), 0.5))
    thick = math_("SUBTRACT", math_("MULTIPLY", py_, C["ht"]), bow)
    newpos = vmath("ADD", C["P"], vmath("ADD", across, vmath("SCALE", C["Nn"], scale=thick)))
    sp = node("GeometryNodeSetPosition"); link(c2m.outputs["Mesh"], sp.inputs["Geometry"]); link(newpos, sp.inputs["Position"])

    # 7 UV strip: U around the section (seam on the inner side), V root -> tip
    ang = math_("ARCTAN2", px_, py_)  # +-pi (the seam) on the inner side
    ev = node("GeometryNodeFieldOnDomain", data_type="FLOAT_VECTOR", domain="FACE"); link(pc.outputs["prof"], ev.inputs[0])
    sepf = node("ShaderNodeSeparateXYZ"); link(ev.outputs[0], sepf.inputs[0])
    angf = math_("ARCTAN2", sepf.outputs["X"], sepf.outputs["Y"])
    dlt = math_("SUBTRACT", ang, angf)
    fix = math_("SUBTRACT", ang, math_("MULTIPLY", math_("ROUND", math_("DIVIDE", dlt, 2 * math.pi)), 2 * math.pi))
    uu = math_("ADD", math_("DIVIDE", fix, 2 * math.pi), 0.5)
    clu = N.new("ShaderNodeClamp"); put(clu.inputs[0], uu); uu = clu.outputs[0]
    uv = node("ShaderNodeCombineXYZ"); link(uu, uv.inputs[0]); link(C["u"], uv.inputs[1])
    st = node("GeometryNodeStoreNamedAttribute", data_type="FLOAT2", domain="CORNER")
    link(sp.outputs["Geometry"], st.inputs["Geometry"]); st.inputs["Name"].default_value = "UVMap"; link(uv.outputs[0], st.inputs["Value"])

    # 8 close the tip to one point, smooth, material
    mg = node("GeometryNodeMergeByDistance"); link(st.outputs["Geometry"], mg.inputs["Geometry"]); mg.inputs["Distance"].default_value = 1e-5
    sm = node("GeometryNodeSetShadeSmooth"); link(mg.outputs["Geometry"], sm.inputs[0])
    mt = node("GeometryNodeSetMaterial"); link(sm.outputs[0], mt.inputs["Geometry"]); link(I("Material"), mt.inputs["Material"])
    link(mt.outputs["Geometry"], gout.inputs["Geometry"])
    return g


def set_input(md, name, value):
    g = md.node_group
    ident = next(s.identifier for s in g.interface.items_tree if getattr(s, "in_out", "") == "INPUT" and s.name == name)
    try:
        md[ident] = value
    except Exception:
        getattr(md.properties.inputs, ident).value = value


def get_input(md, name):
    g = md.node_group
    ident = next(s.identifier for s in g.interface.items_tree if getattr(s, "in_out", "") == "INPUT" and s.name == name)
    try:
        return md[ident]
    except Exception:
        return getattr(md.properties.inputs, ident).value


def make_wire(name, pos, rad, collection, avoid=None, preset="side", summary=None, follow=1.0, material=None, tilts=None):
    """Create the editable wire (Bezier, automatic handles) with the strand modifier. Returns the object."""
    import bpy
    cu = bpy.data.curves.new(name, "CURVE"); cu.dimensions = "3D"; cu.resolution_u = 12
    sp = cu.splines.new("BEZIER"); sp.bezier_points.add(len(pos) - 1)
    for i, bp in enumerate(sp.bezier_points):
        bp.co = [float(x) for x in pos[i]]; bp.handle_left_type = bp.handle_right_type = "AUTO"
        bp.radius = float(max(rad[i], 0.0005)); bp.tilt = float(tilts[i]) if tilts is not None else 0.0
    ob = bpy.data.objects.new(name, cu); collection.objects.link(ob)
    md = ob.modifiers.new("LidaHairWire", "NODES"); md.node_group = ensure_group()
    p = dict(PRESETS[preset])
    if summary:  # follow = 1: thickness as read from the existing strand; 0: preset only
        p["flat"] = p["flat"] + (summary["flat"] - p["flat"]) * follow
        p["tube"] = p["tube"] + (summary["tube"] - p["tube"]) * follow
    for k, nm in PRESET_INPUTS:
        set_input(md, nm, float(p[k]))
    if avoid is not None:
        set_input(md, "Avoid", avoid)
    if material is not None:
        set_input(md, "Material", material)
    ob["lida_hair_wire"] = preset
    return ob


def vary(objs, seed=0, amount=1.0, layers=0.0015):
    """Make a row of strands uneven, the way drawn hair is: width, length, where the point ends, and layer.
    Narrow strands are lifted onto an upper layer so they overlap the wide ones instead of crossing them."""
    rng = np.random.default_rng(seed)
    out = []
    for i, ob in enumerate(objs):
        md = ob.modifiers.get("LidaHairWire")
        if md is None:
            continue
        w = float(np.exp(rng.normal(0.0, 0.30 * amount)))
        set_input(md, "Width Scale", float(np.clip(get_input(md, "Width Scale") * w, 0.2, 3.0)))
        set_input(md, "Tip Side", float(np.clip(rng.normal(0.0, 0.6 * amount), -1, 1)))
        set_input(md, "Tip Length", float(np.clip(get_input(md, "Tip Length") * rng.uniform(1 - 0.3 * amount, 1 + 0.3 * amount), 0.05, 1.0)))
        set_input(md, "Trim Tip", float(1.0 - rng.uniform(0.0, 0.12 * amount)))
        set_input(md, "Lift", float(layers * (2 if w < 0.8 else (1 if i % 2 else 0))))
        ob.update_tag(); out.append(ob.name)
    return out

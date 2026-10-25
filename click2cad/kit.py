"""Parts kit: helpers every generated script can use to place geometry in world space (metres).

The pipeline puts HELPERS into the script's namespace, so a script builds parts with calls like
rod("Leg_1", hub_point, caster_point, 0.02): the part's ends sit exactly where they are asked to,
which keeps attached parts connected.
"""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector


def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _from_bmesh(name, bm):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return _link(bpy.data.objects.new(name, me))


def box(name, lo, hi):
    """Axis-aligned box between two opposite corners."""
    lo, hi = Vector(lo), Vector(hi)
    lo, hi = Vector([min(a, b) for a, b in zip(lo, hi)]), Vector([max(a, b) for a, b in zip(lo, hi)])
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.transform(bm, matrix=Matrix.Translation((lo + hi) / 2) @ Matrix.Diagonal((*(hi - lo), 1.0)), verts=bm.verts)
    return _from_bmesh(name, bm)


def rod(name, p0, p1, radius, segments=24):
    """Cylinder whose end caps sit exactly on p0 and p1."""
    p0, p1 = Vector(p0), Vector(p1)
    axis = p1 - p0
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius, depth=axis.length)
    rot = Vector((0.0, 0.0, 1.0)).rotation_difference(axis.normalized()).to_matrix().to_4x4()
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ rot, verts=bm.verts)
    return _from_bmesh(name, bm)


def tube(name, points, radius, cyclic=False):
    """Round tube through the given points (smooth bends), converted to a mesh."""
    cu = bpy.data.curves.new(name + "_path", 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    cu.use_fill_caps = True
    spline = cu.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    for bp, p in zip(spline.bezier_points, points):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = 'AUTO'
    spline.use_cyclic_u = cyclic
    tmp = _link(bpy.data.objects.new(name + "_tmp", cu))
    depsgraph = bpy.context.evaluated_depsgraph_get()
    depsgraph.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    me.name = name
    return _link(bpy.data.objects.new(name, me))


def sheet(name, corners, thickness):
    """Flat panel through four corner points (in order), given a thickness."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in corners], [], [(0, 1, 2, 3)])
    me.update()
    obj = _link(bpy.data.objects.new(name, me))
    mod = obj.modifiers.new("Solidify", 'SOLIDIFY')
    mod.thickness = thickness
    mod.offset = 0.0
    return obj


def bevel(obj, width, segments=3):
    """Round the edges of an object made by box() or sheet(). Returns the object."""
    mod = obj.modifiers.new("Bevel", 'BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    return obj


HELPERS = {"box": box, "rod": rod, "tube": tube, "sheet": sheet, "bevel": bevel,
           "math": math, "Vector": Vector, "Matrix": Matrix}

"""Test-build a script the way the pipeline does, then check and render it (for answering live requests).

usage: .venv311\\Scripts\\python.exe tools\\check_script.py <script.py> <photo> <out_dir>

Builds into <out_dir>/model.obj (never into a job folder), prints a connectivity check and writes
<out_dir>/review.png: the photo next to five rendered views.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageOps  # noqa: E402

from click2cad import kit, llm  # noqa: E402

script_path, photo_path, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
out_dir.mkdir(parents=True, exist_ok=True)
obj = out_dir / "model.obj"
obj.unlink(missing_ok=True)

# -- build exactly like pipeline.py, but into out_dir
code = llm.ensure_export_tail(llm.retarget_output(script_path.read_text(encoding="utf-8"), None, obj), obj)
bpy.ops.wm.read_factory_settings(use_empty=True)
ns = {"bpy": bpy, "OUTPUT_PATH": str(obj.resolve()), **kit.HELPERS}
exec(compile(code, str(script_path), "exec"), ns, ns)
if not obj.exists():
    bpy.ops.wm.obj_export(filepath=str(obj.resolve()))
print("BUILT", obj.exists())

# -- connectivity: parts whose bounding boxes come within 5 mm count as touching (approximate)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=str(obj))
scene = bpy.context.scene
meshes = [o for o in scene.objects if o.type == "MESH" and o.data.vertices]
TOL = 0.005
boxes = {}
for o in meshes:
    pts = [o.matrix_world @ v.co for v in o.data.vertices]
    boxes[o.name] = ([min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)])
names = list(boxes)
parent = {n: n for n in names}


def find(n):
    while parent[n] != n:
        parent[n] = parent[parent[n]]
        n = parent[n]
    return n


for i, a in enumerate(names):
    for b in names[i + 1:]:
        (alo, ahi), (blo, bhi) = boxes[a], boxes[b]
        if all(alo[k] <= bhi[k] + TOL and blo[k] <= ahi[k] + TOL for k in range(3)):
            parent[find(a)] = find(b)
groups = {}
for n in names:
    groups.setdefault(find(n), []).append(n)
groups = sorted(groups.values(), key=len, reverse=True)
lo = Vector([min(boxes[n][0][k] for n in names) for k in range(3)])
hi = Vector([max(boxes[n][1][k] for n in names) for k in range(3)])
size = (hi - lo) * 100
print(f"CHECK {len(names)} parts, {len(groups)} separate group(s), lowest point {lo.z * 100:.1f} cm, "
      f"size {size.x:.0f} x {size.y:.0f} x {size.z:.0f} cm")
for g in groups[1:]:
    print("   floating:", ", ".join(sorted(g)))

# -- five views next to the photo
center, radius = (lo + hi) / 2, (hi - lo).length / 2
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
scene.render.engine = "BLENDER_WORKBENCH"
shading = scene.display.shading
shading.light = "STUDIO"
shading.color_type = "SINGLE"
shading.single_color = (0.55, 0.6, 0.7)
shading.show_cavity = True
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = 600
dist = radius / math.sin(cam.data.angle / 2) * 1.02
views = [("3/4 front", (1.3, -1.8, 0.8)), ("Front", (0, -1, 0.04)), ("Side", (1, 0, 0.04)),
         ("3/4 back", (-1.3, 1.8, 0.8)), ("Top", (0.0, -0.001, 1))]
font = ImageFont.load_default(size=26)
sheet = Image.new("RGB", (1800, 1200), "white")
cells = [("Photo", None)]
for label, direction in views:
    cam.location = center + Vector(direction).normalized() * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(out_dir / f"view_{label.replace('/', '-').replace(' ', '_')}.png")
    bpy.ops.render.render(write_still=True)
    cells.append((label, scene.render.filepath))
for i, (label, path) in enumerate(cells):
    cell = Image.new("RGB", (600, 600), "white")
    if path is None:
        img = ImageOps.contain(ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB"), (600, 600))
        cell.paste(img, ((600 - img.width) // 2, (600 - img.height) // 2))
    else:
        view = Image.open(path).convert("RGBA")
        cell.paste(view, (0, 0), view)
    ImageDraw.Draw(cell).text((14, 10), label, fill=(40, 40, 40), font=font)
    sheet.paste(cell, ((i % 3) * 600, (i // 3) * 600))
sheet.save(out_dir / "review.png")
print("SHEET", out_dir / "review.png")

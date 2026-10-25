"""Ask Claude (a live Claude Code session, or the Anthropic API) to write or refine a Blender (bpy) build script."""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageOps

from . import claude, claude_session
from .config import PROVIDERS, claude_mode

# Longest side of the photos sent to the API. Phone photos are ~4000px; this keeps requests
# fast without losing the detail the model needs.
MAX_IMAGE_SIDE = 1600

# The script runs with the parts kit (click2cad/kit.py) already in scope.
SYSTEM = """
You write Blender Python (bpy) scripts only.
Return ONLY executable Python code. No markdown fences. No explanation.

Rules:
1. import bpy and math at the top.
2. Use meters (1 unit = 1 meter). Z is up, the floor is z = 0, and the piece stands centred on the
   origin with its front facing -Y and its back facing +Y.
3. First define the key dimensions as named variables (for example SEAT_TOP, SEAT_HALF_W, BACK_Z1,
   BASE_R), estimated from the photo using realistic furniture sizes. Place every part relative to
   these variables so attached parts meet exactly: a backrest starts at the seat's back edge, legs run
   from the hub to each caster, armrests start on the seat's sides. Nothing may float, and nothing may
   go below the floor.
4. Build all geometry with these helper functions, which are already defined. Do not redefine them,
   and do not use bpy.ops.mesh primitives, object scale/rotation, or boolean modifiers:
     box(name, lo, hi)                        axis-aligned box between corner points lo=(x,y,z), hi=(x,y,z)
     rod(name, p0, p1, radius)                cylinder whose end caps sit exactly on points p0 and p1
     tube(name, points, radius, cyclic=False) round tube through a list of points, with smooth bends
     sheet(name, corners, thickness)          flat panel through four corner points given in order
     bevel(obj, width, segments=3)            rounds the edges of an object made by box or sheet; returns obj
   Vector and Matrix (from mathutils) are also available.
5. Name objects clearly: Seat, Backrest, Leg_1, Leg_2, ...
6. Do not open UI dialogs. Do not call bpy.ops.wm.save_as_mainfile.
7. End by exporting OBJ with:
   bpy.ops.wm.obj_export(filepath=OUTPUT_PATH, export_selected_objects=False)
   where OUTPUT_PATH is already defined as a Python string variable in scope.
""".strip()


def backend(provider: str):
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown model provider: {provider!r}")
    return claude_session if claude_mode() == "live" else claude


def model_name(provider: str) -> str:
    return backend(provider).model()


def provider_status(provider: str) -> dict:
    missing = backend(provider).missing_settings()
    return {
        "id": provider,
        "label": PROVIDERS[provider],
        "model": model_name(provider) or None,
        "ready": not missing,
        "missing": missing,
    }


def load_image(path: Path) -> Image.Image:
    image = ImageOps.exif_transpose(Image.open(path))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    return image


def export_instructions(out: str) -> str:
    return (
        f"Define this exact variable before export:\n"
        f'OUTPUT_PATH = r"{out}"\n'
        f"Then call bpy.ops.wm.obj_export(filepath=OUTPUT_PATH).\n"
    )


def ask_blender_script(provider: str, image_paths: list[Path], prompt: str, output_obj: Path) -> str:
    """Ask for a bpy script that builds the object and exports to output_obj."""
    if not image_paths:
        raise ValueError("At least one photo is required")
    images = [load_image(p) for p in image_paths]

    out = output_obj.resolve().as_posix()
    views = (
        f"The {len(images)} photos show the same piece from different angles.\n"
        if len(images) > 1
        else ""
    )
    user = (
        f"Build this furniture in Blender from the photo{'s' if len(images) > 1 else ''}.\n"
        f"{views}"
        f"User notes: {prompt.strip() or 'none'}\n"
        + export_instructions(out)
    )
    return strip_code_fences(backend(provider).generate(SYSTEM, images, user, job_dir=output_obj.parent))


def refine_blender_script(
    provider: str,
    image_paths: list[Path],
    prompt: str,
    feedback: str,
    previous_script: str,
    previous_error: str | None,
    output_obj: Path,
) -> str:
    """Ask for an improved version of previous_script that applies the user's feedback."""
    images = [load_image(p) for p in image_paths]
    count = len(images)
    lines = [
        f"Improve this Blender script. It builds the furniture in the photo{'s' if count > 1 else ''}."
        if count
        else "Improve this Blender script. It builds a piece of furniture."
    ]
    if count > 1:
        lines.append(f"The {count} photos show the same piece from different angles.")
    lines.append(f"User notes: {prompt.strip() or 'none'}")
    if previous_error:
        lines.append(f"When it ran in Blender, the script failed with this error:\n{previous_error.strip()}")
    lines.append(f"Requested changes: {feedback.strip() or ('fix the error' if previous_error else 'none')}")
    lines.append("Return the complete updated script. Keep every part the requested changes don't mention.")
    lines.append(f"Current script:\n{previous_script.strip()}")
    user = "\n".join(lines) + "\n" + export_instructions(output_obj.resolve().as_posix())
    return strip_code_fences(backend(provider).generate(SYSTEM, images, user, job_dir=output_obj.parent))


def retarget_output(code: str, old_output: str | None, output_obj: Path) -> str:
    """Point a script's export at output_obj, so a refined script can't overwrite its parent's model."""
    new = output_obj.resolve().as_posix()
    if old_output:
        code = code.replace(old_output, new)
    return re.sub(
        r"^([ \t]*)OUTPUT_PATH\s*=.*$",
        lambda m: f'{m.group(1)}OUTPUT_PATH = r"{new}"',
        code,
        flags=re.M,
    )


def strip_code_fences(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:python)?\s*\n([\s\S]*?)\n```$", text)
    if fence:
        return fence.group(1).strip()
    # Soft cleanup if model wrapped anyway
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def ensure_export_tail(script: str, output_obj: Path) -> str:
    """Guarantee OUTPUT_PATH + obj_export exist at the end."""
    out = output_obj.resolve().as_posix()
    tail = (
        "\n\n# --- Click2CAD export tail ---\n"
        f'OUTPUT_PATH = r"{out}"\n'
        "try:\n"
        "    bpy.ops.wm.obj_export(filepath=OUTPUT_PATH)\n"
        "except Exception:\n"
        "    # Older Blender fallback\n"
        "    bpy.ops.export_scene.obj(filepath=OUTPUT_PATH)\n"
    )
    if "obj_export" in script or "export_scene.obj" in script:
        if "OUTPUT_PATH" not in script:
            script = f'OUTPUT_PATH = r"{out}"\n' + script
        return script
    return script.rstrip() + tail

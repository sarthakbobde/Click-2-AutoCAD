"""Run one job: photo(s) -> Claude-written bpy script -> Blender geometry -> OBJ.

The web server runs each job as a subprocess (`python -m click2cad.pipeline <job_dir>`)
so every job gets a fresh bpy state, and a crash in the generated code cannot
take the server down. Lines starting with @@ are progress markers for the runner.

job.json "mode":
    generate (default)  write a new script from the photo(s)
    refine              improve an earlier job's script (base_script.py) using the user's feedback
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from . import llm
from .config import PROVIDERS
from .jobs import INPUTS, MODEL, SCRIPT, SPEC


def marker(kind: str, value: str) -> None:
    print(f"@@{kind}:{value}", flush=True)


def run(job_dir: Path, spec: dict) -> Path:
    obj_path = job_dir / MODEL
    script_path = job_dir / SCRIPT
    images = [job_dir / INPUTS / name for name in spec["images"]]
    prompt = spec.get("prompt", "")
    provider = spec.get("provider", "claude")
    model = llm.model_name(provider)

    marker("model", model)
    marker("stage", "asking")
    if spec.get("mode") == "refine":
        base_output = spec.get("base_output")
        previous = (job_dir / spec["base_script"]).read_text(encoding="utf-8")
        previous = llm.retarget_output(previous, base_output, obj_path)
        print(f"Asking {PROVIDERS[provider]} ({model}) to refine the script...", flush=True)
        code = llm.refine_blender_script(
            provider, images, prompt, spec.get("feedback", ""), previous, spec.get("base_error"), obj_path
        )
        code = llm.retarget_output(code, base_output, obj_path)
    else:
        print(f"Asking {PROVIDERS[provider]} ({model}) for a Blender script ({len(images)} photo(s))...", flush=True)
        code = llm.ask_blender_script(provider, images, prompt, obj_path)
    code = llm.ensure_export_tail(code, obj_path)
    script_path.write_text(code, encoding="utf-8")
    print(f"Wrote {script_path.name}", flush=True)

    marker("stage", "building")
    import bpy

    from . import kit

    # Reset to factory-ish empty scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Isolated globals: the script sees bpy, OUTPUT_PATH and the parts kit (box, rod, tube, sheet, bevel)
    ns: dict = {"bpy": bpy, "OUTPUT_PATH": str(obj_path.resolve()), **kit.HELPERS}
    exec(compile(code, str(script_path), "exec"), ns, ns)

    if not obj_path.exists():
        # The script forgot the export; do it ourselves
        marker("stage", "exporting")
        try:
            bpy.ops.wm.obj_export(filepath=str(obj_path.resolve()))
        except Exception:
            bpy.ops.export_scene.obj(filepath=str(obj_path.resolve()))
    if not obj_path.exists():
        raise RuntimeError("The Blender script ran but no OBJ was exported")

    print(f"Exported {obj_path.name}", flush=True)
    return obj_path


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m click2cad.pipeline <job_dir>")
        return 2
    job_dir = Path(argv[0])
    spec = json.loads((job_dir / SPEC).read_text(encoding="utf-8"))
    try:
        run(job_dir, spec)
    except Exception as exc:
        traceback.print_exc()
        marker("error", f"{type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

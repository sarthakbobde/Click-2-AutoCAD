"""Generate a model from the command line, without the web UI.

    .venv311\\Scripts\\python.exe generate.py samples\\Chair_front.jpg --prompt "Stacking chair"
    .venv311\\Scripts\\python.exe generate.py front.jpg side.jpg back.jpg   # several views of one piece

The job runs right here in the foreground and is recorded like any other
submission, so the result also shows up in the web UI. In live mode it waits
for Claude (in the Claude Code session) to answer, like jobs from the UI.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from click2cad import llm, pipeline
from click2cad.config import PROVIDERS, default_provider
from click2cad.jobs import IMAGE_EXTS, MODEL, SPEC, JobStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Click2CAD: furniture photo(s) -> Blender model (OBJ)")
    parser.add_argument("images", nargs="+", type=Path, help="Photo(s) of one piece; several = different views")
    parser.add_argument("--prompt", default="", help="Short description to guide the model")
    parser.add_argument("--name", default="", help="Submission name (defaults to the first file name)")
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        help="Model provider (default: C2C_DEFAULT_PROVIDER in .env, otherwise azure)",
    )
    args = parser.parse_args()

    for path in args.images:
        if not path.is_file():
            print(f"Image not found: {path}")
            return 1
        if path.suffix.lower() not in IMAGE_EXTS:
            print(f"Unsupported file type: {path} (use JPG, PNG or WebP)")
            return 1

    provider = args.provider or default_provider()
    status = llm.provider_status(provider)
    if not status["ready"]:
        print(f"{status['label']} is not set up yet: add {' and '.join(status['missing'])} to .env")
        return 1

    store = JobStore()
    job = store.create(
        args.name or args.images[0].stem,
        args.prompt,
        [(path.name, path.read_bytes()) for path in args.images],
        provider,
        llm.model_name(provider),
        status="running",
    )
    job_id = job["id"]
    job_dir = store.job_dir(job_id)
    store.update(job_id, started_at=time.time(), attempts=1)
    print(f"Submission {job_id}")

    try:
        pipeline.run(job_dir, json.loads((job_dir / SPEC).read_text(encoding="utf-8")))
    except Exception as exc:
        store.update(job_id, status="failed", stage=None, error=f"{type(exc).__name__}: {exc}", finished_at=time.time())
        print(f"Failed: {exc}")
        return 1

    store.update(job_id, status="completed", stage=None, finished_at=time.time())
    print(f"OK: {job_dir / MODEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

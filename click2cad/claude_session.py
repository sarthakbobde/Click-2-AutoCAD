"""Claude, live: each job waits for Claude, running in a Claude Code session next to the app, to write its script.

The job writes request.md into its folder (the photos are already in inputs/) and waits for answer.py.
In the Claude Code session, tools/watch_requests.py exits as soon as a request is waiting; Claude reads
the request and the photos, writes answer.py, and the pipeline carries on exactly as with an API model.
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from .config import JOB_TIMEOUT_SECONDS
from .jobs import INPUTS

REQUEST = "request.md"
ANSWER = "answer.py"
# Leave a couple of minutes to build before the job's own timeout.
WAIT_SECONDS = max(60, JOB_TIMEOUT_SECONDS - 120)


def model() -> str:
    return "live session"


def missing_settings() -> list[str]:
    return []


def generate(system: str, images: list[Image.Image], text: str, job_dir: Path | None = None) -> str:
    if job_dir is None:
        raise RuntimeError("Live mode needs the job folder")
    request, answer = job_dir / REQUEST, job_dir / ANSWER
    answer.unlink(missing_ok=True)
    photos = sorted(p.name for p in (job_dir / INPUTS).iterdir()) if (job_dir / INPUTS).exists() else []
    request.write_text(
        "# Blender script request\n\n"
        f"Job folder: {job_dir}\n"
        f"Photos: {', '.join(f'{INPUTS}/{name}' for name in photos) or 'none'}\n"
        f"Write the script to: {answer}\n\n"
        "## Instructions\n\n" + system + "\n\n## Message\n\n" + text,
        encoding="utf-8",
    )
    print(f"Waiting for the AI model to write the script (up to {WAIT_SECONDS // 60} min)...", flush=True)

    deadline = time.time() + WAIT_SECONDS
    last_size = -1
    while time.time() < deadline:
        if answer.exists():
            size = answer.stat().st_size
            if size and size == last_size:  # unchanged for a second: fully written
                return answer.read_text(encoding="utf-8")
            last_size = size
        time.sleep(1)
    raise RuntimeError(f"The AI model didn't answer within {WAIT_SECONDS // 60} minutes")

"""Click2CAD web app: REST API + static UI. Start it with `python serve.py`."""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import llm
from .config import JOBS_DIR, MAX_PARALLEL_JOBS, PROVIDERS, WEB_DIR, default_provider
from .jobs import ACTIVE, BASE_SCRIPT, IMAGE_EXTS, INPUTS, LOG, MODEL, SCRIPT, THUMB, JobStore, validate_image
from .runner import JobRunner

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

store = JobStore()
runner = JobRunner(store)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runner.start()
    yield
    runner.stop()


app = FastAPI(title="Click2CAD", lifespan=lifespan)


def to_api(job: dict) -> dict:
    job_dir = store.job_dir(job["id"])
    base = f"/files/{job['id']}"
    stamp = int(job["finished_at"] or job["created_at"])  # busts the browser cache after a retry
    has_model = job["status"] == "completed" and (job_dir / MODEL).exists()
    return {
        **job,
        "thumb_url": f"{base}/{THUMB}" if (job_dir / THUMB).exists() else None,
        "image_urls": [f"{base}/inputs/{name}" for name in job["images"]],
        "model_url": f"{base}/{MODEL}?v={stamp}" if has_model else None,
        "script_url": f"{base}/{SCRIPT}?v={stamp}" if (job_dir / SCRIPT).exists() else None,
    }


def require_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Submission not found")
    return job


def require_provider(provider: str) -> str:
    """The provider to use (default when blank); 409 if its .env settings are missing."""
    provider = (provider or default_provider()).strip().lower()
    if provider not in PROVIDERS:
        raise HTTPException(400, f"Unknown model provider {provider!r}")
    status = llm.provider_status(provider)
    if not status["ready"]:
        raise HTTPException(409, f"{status['label']} is not set up yet: add {' and '.join(status['missing'])} to .env")
    return provider


def bpy_version() -> str | None:
    try:
        return version("bpy")
    except PackageNotFoundError:
        return None


@app.get("/api/config")
def get_config():
    return {
        "providers": [llm.provider_status(provider) for provider in PROVIDERS],
        "default_provider": default_provider(),
        "blender": bpy_version(),
        "max_parallel_jobs": MAX_PARALLEL_JOBS,
    }


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": [to_api(job) for job in store.list()]}


@app.post("/api/jobs", status_code=201)
def submit_jobs(
    files: list[UploadFile] = File(...),
    mode: str = Form("separate"),
    name: str = Form(""),
    prompt: str = Form(""),
    provider: str = Form(""),
):
    """Queue photos. mode=separate: one job per photo; mode=multiview: one job, all photos."""
    if mode not in ("separate", "multiview"):
        raise HTTPException(400, "mode must be 'separate' or 'multiview'")
    provider = require_provider(provider)
    uploads = []
    for upload in files:
        filename = upload.filename or "photo.jpg"
        if Path(filename).suffix.lower() not in IMAGE_EXTS:
            raise HTTPException(400, f"{filename}: unsupported file type (use JPG, PNG or WebP)")
        data = upload.file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"{filename} is larger than 25 MB")
        try:
            validate_image(data)
        except ValueError:
            raise HTTPException(400, f"{filename} is not a readable image")
        uploads.append((filename, data))
    if not uploads:
        raise HTTPException(400, "Add at least one photo")

    name, prompt = name.strip()[:120], prompt.strip()[:1000]
    groups = [uploads] if mode == "multiview" else [[upload] for upload in uploads]
    created = []
    for group in groups:
        stem = Path(group[0][0]).stem
        job_name = f"{name} - {stem}" if name and len(groups) > 1 else (name or stem)
        created.append(store.create(job_name, prompt, group, provider, llm.model_name(provider)))
    runner.wake()
    return {"jobs": [to_api(job) for job in created]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return to_api(require_job(job_id))


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def get_log(job_id: str):
    require_job(job_id)
    log = store.job_dir(job_id) / LOG
    return log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""


@app.post("/api/jobs/{job_id}/refine", status_code=201)
def refine_job(job_id: str, feedback: str = Form(""), provider: str = Form(""), name: str = Form("")):
    """Queue a new submission that improves this one's script using the user's feedback."""
    parent = require_job(job_id)
    if parent["status"] in ACTIVE:
        raise HTTPException(409, "Wait for this submission to finish before refining it")
    parent_dir = store.job_dir(job_id)
    script = parent_dir / SCRIPT
    if not script.exists():
        raise HTTPException(409, "This submission has no Blender script to refine")
    feedback = feedback.strip()[:2000]
    if not feedback and parent["status"] != "failed":
        raise HTTPException(400, "Describe what should change")
    provider = require_provider(provider)

    photos = [(filename, (parent_dir / INPUTS / filename).read_bytes()) for filename in parent["images"]]
    job = store.create(
        (name.strip() or f"{parent['name']} (refined)")[:120],
        parent["prompt"],
        photos,
        provider,
        llm.model_name(provider),
        parent_id=job_id,
        feedback=feedback,
        spec_extra={
            "mode": "refine",
            "feedback": feedback,
            "base_script": BASE_SCRIPT,
            "base_output": (parent_dir / MODEL).resolve().as_posix(),
            "base_error": parent["error"] if parent["status"] == "failed" else None,
        },
        files={BASE_SCRIPT: script.read_bytes()},
    )
    runner.wake()
    return to_api(job)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str):
    job = require_job(job_id)
    if job["status"] in ACTIVE:
        raise HTTPException(409, "This submission is already queued or running")
    if not job["images"] and not (store.job_dir(job_id) / BASE_SCRIPT).exists():
        raise HTTPException(409, "This submission has no photos to regenerate from")
    require_provider(job["provider"])
    store.requeue(job_id)
    runner.wake()
    return to_api(require_job(job_id))


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    require_job(job_id)
    if not runner.cancel(job_id):
        raise HTTPException(409, "Only queued or running submissions can be cancelled")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = require_job(job_id)
    if job["status"] in ACTIVE:
        raise HTTPException(409, "Cancel the submission before deleting it")
    store.delete(job_id)
    return {"ok": True}


app.mount("/files", StaticFiles(directory=JOBS_DIR), name="files")
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

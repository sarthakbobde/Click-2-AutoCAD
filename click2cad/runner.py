"""Background queue: runs queued jobs, each in its own Python subprocess."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import JOB_TIMEOUT_SECONDS, MAX_PARALLEL_JOBS, ROOT
from .jobs import LOG, JobStore

STAGE_PREFIX = "@@stage:"
MODEL_PREFIX = "@@model:"
ERROR_PREFIX = "@@error:"


class JobRunner:
    def __init__(self, store: JobStore, max_parallel: int = MAX_PARALLEL_JOBS):
        self.store = store
        self.max_parallel = max_parallel
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()

    def start(self) -> None:
        self.store.requeue_interrupted()
        threading.Thread(target=self._loop, name="job-runner", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        with self._lock:
            procs = list(self._procs.values())
        for proc in procs:
            proc.kill()

    def wake(self) -> None:
        self._wake.set()

    def cancel(self, job_id: str) -> bool:
        if self.store.cancel_if_queued(job_id):
            return True
        with self._lock:
            proc = self._procs.get(job_id)
            if proc:
                self._cancelled.add(job_id)
        if proc:
            proc.kill()
            return True
        return False

    def _loop(self) -> None:
        while not self._stopping.is_set():
            while True:
                with self._lock:
                    busy = len(self._procs)
                if busy >= self.max_parallel:
                    break
                job = self.store.claim_next()
                if not job:
                    break
                self._launch(job)
            self._wake.wait(timeout=2)
            self._wake.clear()

    def _launch(self, job: dict) -> None:
        job_id = job["id"]
        job_dir = self.store.job_dir(job_id)
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "click2cad.pipeline", str(job_dir)],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            self.store.update(job_id, status="failed", stage=None, error=f"Could not start worker: {exc}", finished_at=time.time())
            return
        with self._lock:
            self._procs[job_id] = proc
        threading.Thread(target=self._watch, args=(job_id, proc, job_dir / LOG), daemon=True).start()

    def _watch(self, job_id: str, proc: subprocess.Popen, log_path: Path) -> None:
        timed_out = threading.Event()

        def on_timeout() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(JOB_TIMEOUT_SECONDS, on_timeout)
        timer.daemon = True
        timer.start()

        error, last_line = None, ""
        with open(log_path, "w", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                text = line.strip()
                if text.startswith(STAGE_PREFIX):
                    self.store.update(job_id, stage=text[len(STAGE_PREFIX):])
                elif text.startswith(MODEL_PREFIX):
                    self.store.update(job_id, model=text[len(MODEL_PREFIX):] or None)
                elif text.startswith(ERROR_PREFIX):
                    error = text[len(ERROR_PREFIX):].strip()
                elif text:
                    last_line = text
        code = proc.wait()
        timer.cancel()

        with self._lock:
            self._procs.pop(job_id, None)
            cancelled = job_id in self._cancelled
            self._cancelled.discard(job_id)

        now = time.time()
        if self._stopping.is_set():
            pass  # server shutting down; requeue_interrupted() picks it up next start
        elif cancelled:
            self.store.update(job_id, status="cancelled", stage=None, finished_at=now)
        elif timed_out.is_set():
            self.store.update(job_id, status="failed", stage=None, error=f"Timed out after {JOB_TIMEOUT_SECONDS}s", finished_at=now)
        elif code == 0:
            self.store.update(job_id, status="completed", stage=None, error=None, finished_at=now)
        else:
            message = error or last_line or f"Worker exited with code {code}"
            self.store.update(job_id, status="failed", stage=None, error=message, finished_at=now)
        self._wake.set()

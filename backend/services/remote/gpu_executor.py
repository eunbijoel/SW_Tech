"""
RTX 5090 GPU server remote execution adapter.

Two connection modes:
  1. HTTP API mode  — if GPU_API_URL is set, POST jobs to the GPU server's REST API.
  2. SSH mode       — fallback: SSH into the server and run a Python script.

In production you'd deploy a lightweight FastAPI job-runner on the GPU server
and use HTTP API mode.  SSH mode is useful for ad-hoc or early setups.
"""
import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.core.config import settings
from backend.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class GPUJob:
    id: str
    code: str
    status: str = "pending"   # pending | running | done | error
    result: str = ""
    error: str = ""


class GPUExecutor:
    """Submit code to a remote GPU server for execution."""

    def __init__(self) -> None:
        self._api_url = settings.GPU_API_URL
        self._ssh_host = settings.GPU_SERVER_HOST
        self._ssh_port = settings.GPU_SERVER_PORT
        self._ssh_user = settings.GPU_SERVER_USER
        self._ssh_key  = Path(settings.GPU_SERVER_KEY_PATH).expanduser()

    @property
    def is_configured(self) -> bool:
        return bool(self._api_url or self._ssh_host)

    async def submit(self, code: str, context: dict | None = None) -> GPUJob:
        """
        Submit a Python code snippet for GPU execution.
        Returns a GPUJob with the result populated (blocking until done).
        """
        if not self.is_configured:
            raise RuntimeError("GPU server not configured. Set GPU_API_URL or GPU_SERVER_HOST.")

        job = GPUJob(id=str(uuid.uuid4()), code=code)

        if self._api_url:
            return await self._submit_http(job, context or {})
        return await self._submit_ssh(job)

    async def _submit_http(self, job: GPUJob, context: dict) -> GPUJob:
        """POST job to GPU server REST API and poll until complete."""
        payload = {"id": job.id, "code": job.code, "context": context}
        async with httpx.AsyncClient(timeout=300) as client:
            try:
                resp = await client.post(f"{self._api_url}/jobs", json=payload)
                resp.raise_for_status()
                data = resp.json()
                job.status = data.get("status", "done")
                job.result = data.get("result", "")
                log.info("GPU job submitted via HTTP", job_id=job.id, status=job.status)
            except Exception as e:
                job.status = "error"
                job.error = str(e)
                log.error("GPU HTTP submission failed", error=str(e))
        return job

    async def _submit_ssh(self, job: GPUJob) -> GPUJob:
        """Run code on GPU server via SSH (paramiko)."""
        try:
            import paramiko  # type: ignore[import]
        except ImportError:
            job.status = "error"
            job.error = "paramiko not installed. Run: pip install paramiko"
            return job

        script = (
            "import sys, json\n"
            f"exec({job.code!r})\n"
        )

        def _run_ssh() -> tuple[str, str]:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=self._ssh_host,
                port=self._ssh_port,
                username=self._ssh_user,
                key_filename=str(self._ssh_key) if self._ssh_key.exists() else None,
            )
            _, stdout, stderr = client.exec_command(f"python3 -c {script!r}")
            out = stdout.read().decode()
            err = stderr.read().decode()
            client.close()
            return out, err

        try:
            out, err = await asyncio.get_event_loop().run_in_executor(None, _run_ssh)
            if err:
                job.status = "error"
                job.error = err
            else:
                job.status = "done"
                job.result = out
        except Exception as e:
            job.status = "error"
            job.error = str(e)
            log.error("GPU SSH execution failed", error=str(e))

        return job


gpu_executor = GPUExecutor()

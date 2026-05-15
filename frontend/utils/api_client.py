"""
HTTP client for the FastAPI backend.

All Streamlit pages import this module — never call httpx directly from pages.
Centralising here makes backend URL changes a one-line edit.
"""
from __future__ import annotations

import httpx
import streamlit as st

BACKEND_URL = "http://localhost:8000/api/v1"
TIMEOUT = 120.0


def _headers() -> dict:
    # In production: read API key from st.secrets or environment
    api_key = st.session_state.get("api_key", "")
    return {"X-API-Key": api_key} if api_key else {}


def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT, headers=_headers())


# ── Chat ──────────────────────────────────────────────────────────────────────

def chat_complete(messages: list[dict], model: str = "", **kwargs) -> dict:
    payload = {"messages": messages, "model": model, **kwargs}
    with _client() as c:
        resp = c.post("/chat/complete", json=payload)
        resp.raise_for_status()
        return resp.json()


def chat_excel(file_ids: list[str], prompt: str, model: str = "", executor: str = "local") -> dict:
    payload = {
        "file_ids": file_ids,
        "prompt": prompt,
        "model": model,
        "executor": executor,
        "save_result": True,
    }
    with _client() as c:
        resp = c.post("/chat/excel", json=payload)
        resp.raise_for_status()
        return resp.json()


# ── Files ─────────────────────────────────────────────────────────────────────

def upload_files(file_bytes_list: list[tuple[str, bytes]], session_id: str = "") -> list[dict]:
    files = [("files", (name, data, "application/octet-stream")) for name, data in file_bytes_list]
    data = {"session_id": session_id}
    with httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT, headers=_headers()) as c:
        resp = c.post("/files/upload", files=files, data=data)
        resp.raise_for_status()
        return resp.json()


def list_files(session_id: str = "") -> list[dict]:
    with _client() as c:
        resp = c.get("/files/", params={"session_id": session_id})
        resp.raise_for_status()
        return resp.json()["files"]


def list_library_files() -> list[dict]:
    """Return pre-seeded Excel files from the backend excel/ directory."""
    with _client() as c:
        resp = c.get("/files/library")
        resp.raise_for_status()
        return resp.json()["files"]


def delete_file(file_id: str) -> bool:
    with _client() as c:
        resp = c.delete(f"/files/{file_id}")
        return resp.status_code == 200


def get_file_download_url(file_id: str) -> str:
    return f"{BACKEND_URL}/files/{file_id}/download"


# ── Models ────────────────────────────────────────────────────────────────────

def list_models() -> dict:
    with _client() as c:
        resp = c.get("/models/")
        resp.raise_for_status()
        return resp.json()


def models_health() -> dict:
    with _client() as c:
        resp = c.get("/models/health")
        resp.raise_for_status()
        return resp.json()


def pull_ollama_model(model_name: str) -> httpx.Response:
    with _client() as c:
        return c.post("/models/pull", json={"model": model_name})


def delete_ollama_model(model_name: str) -> bool:
    with _client() as c:
        resp = c.delete(f"/models/{model_name}")
        return resp.status_code == 200


# ── Results ───────────────────────────────────────────────────────────────────

def list_results(result_type: str = "all") -> dict:
    with _client() as c:
        resp = c.get("/models/results/list", params={"result_type": result_type})
        resp.raise_for_status()
        return resp.json()


def get_markdown_result(filename: str) -> str:
    with _client() as c:
        resp = c.get(f"/models/results/markdown/{filename}")
        resp.raise_for_status()
        return resp.json()["content"]


def delete_result(result_type: str, filename: str) -> bool:
    with _client() as c:
        resp = c.delete(f"/models/results/{result_type}/{filename}")
        return resp.status_code == 200


# ── Execution ─────────────────────────────────────────────────────────────────

def gpu_status() -> dict:
    with _client() as c:
        resp = c.get("/execution/gpu/status")
        resp.raise_for_status()
        return resp.json()


def spark_status() -> dict:
    with _client() as c:
        resp = c.get("/execution/spark/status")
        resp.raise_for_status()
        return resp.json()


# ── Health ────────────────────────────────────────────────────────────────────

def backend_health() -> bool:
    try:
        with httpx.Client(timeout=5) as c:
            resp = c.get("http://localhost:8000/health")
            return resp.status_code == 200
    except Exception:
        return False

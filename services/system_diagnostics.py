"""
서버·GPU·Ollama 진단 — 읽기 전용 시스템 정보 수집 (Step 2).
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")


@dataclass
class GpuDevice:
    index: int
    name: str
    memory_used_mb: float
    memory_total_mb: float
    utilization_pct: float | None = None

    @property
    def memory_label(self) -> str:
        used_gb = self.memory_used_mb / 1024
        total_gb = self.memory_total_mb / 1024
        return f"{used_gb:.0f}/{total_gb:.0f} GB"

    @property
    def memory_ratio(self) -> float:
        if self.memory_total_mb <= 0:
            return 0.0
        return min(1.0, self.memory_used_mb / self.memory_total_mb)


@dataclass
class SystemSnapshot:
    gpus: list[GpuDevice] = field(default_factory=list)
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    cpu_count: int = 0
    load_avg_1m: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_path: str = "/"
    disk_mount_label: str = "/"
    project_dir_gb: float = 0.0
    project_dir_path: str = ""
    ollama_connected: bool = False
    ollama_models: list[str] = field(default_factory=list)
    hostname: str = ""
    cpu_usage_pct: float = 0.0
    cuda_visible: str = ""
    errors: list[str] = field(default_factory=list)


def _run(cmd: list[str], timeout: int = 5) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def collect_gpu_devices() -> list[GpuDevice]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    devices: list[GpuDevice] = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            devices.append(
                GpuDevice(
                    index=int(parts[0]),
                    name=parts[1],
                    memory_used_mb=float(parts[2]),
                    memory_total_mb=float(parts[3]),
                    utilization_pct=float(parts[4]) if len(parts) > 4 and parts[4] else None,
                )
            )
        except ValueError:
            continue
    return devices


def collect_memory_gb() -> tuple[float, float]:
    try:
        mem: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as fp:
            for line in fp:
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                mem[key.strip()] = int(val.strip().split()[0])
        total_kb = mem.get("MemTotal", 0)
        avail_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)
        return used_kb / (1024**2), total_kb / (1024**2)
    except OSError:
        return 0.0, 0.0


def collect_disk_gb(path: str = "/") -> tuple[float, float, str]:
    try:
        usage = shutil.disk_usage(path)
        return (
            usage.used / (1024**3),
            usage.total / (1024**3),
            path,
        )
    except OSError:
        return 0.0, 0.0, path


def collect_dir_size_gb(path: str | Path) -> float:
    """디렉터리 실제 용량 — du 우선."""
    root = Path(path)
    if not root.exists():
        return 0.0
    out = _run(["du", "-sb", str(root)], timeout=15)
    if out:
        try:
            return int(out.split()[0]) / (1024**3)
        except (ValueError, IndexError):
            pass
    return 0.0


def collect_ollama_status() -> tuple[bool, list[str], str | None]:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code != 200:
            return False, [], f"HTTP {r.status_code}"
        data = r.json()
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return True, models, None
    except requests.RequestException as exc:
        return False, [], str(exc)


def collect_system_snapshot(
    disk_path: str | None = None,
    project_dir: str | Path | None = None,
) -> SystemSnapshot:
    """디스크는 기본 루트 파티션(/) — 프로젝트 폴더 용량은 별도 표시."""
    disk_mount = disk_path or "/"
    snap = SystemSnapshot()
    snap.gpus = collect_gpu_devices()
    snap.ram_used_gb, snap.ram_total_gb = collect_memory_gb()
    snap.cpu_count = os.cpu_count() or 0
    try:
        snap.load_avg_1m = os.getloadavg()[0]
    except OSError:
        snap.load_avg_1m = 0.0
    if snap.cpu_count > 0:
        snap.cpu_usage_pct = min(100.0, (snap.load_avg_1m / snap.cpu_count) * 100.0)
    try:
        snap.hostname = socket.gethostname()
    except OSError:
        snap.hostname = ""
    snap.disk_used_gb, snap.disk_total_gb, snap.disk_path = collect_disk_gb(disk_mount)
    snap.disk_mount_label = disk_mount
    proj = Path(project_dir or os.getcwd()).resolve()
    snap.project_dir_path = str(proj)
    snap.project_dir_gb = collect_dir_size_gb(proj)
    connected, models, err = collect_ollama_status()
    snap.ollama_connected = connected
    snap.ollama_models = models
    if err:
        snap.errors.append(f"Ollama: {err}")
    snap.cuda_visible = os.getenv("CUDA_VISIBLE_DEVICES", "(미설정 — 기본 GPU)")
    if not snap.gpus:
        snap.errors.append("nvidia-smi 없음 또는 GPU 미감지")
    return snap


def gpu_device_options(gpus: list[GpuDevice]) -> list[str]:
    if not gpus:
        return ["GPU0 (기본)"]
    return [f"GPU{g.index} = {g.name}" for g in gpus]

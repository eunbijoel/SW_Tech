"""
Pytest fixtures shared across unit and integration tests.
"""
import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# Point storage to temp dirs so tests don't pollute real storage
os.environ.setdefault("UPLOAD_DIR", "/tmp/test_uploads")
os.environ.setdefault("RESULTS_DIR", "/tmp/test_results")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_API_KEY", "test-key")


@pytest.fixture(scope="session", autouse=True)
def ensure_test_dirs() -> None:
    for d in [
        Path("/tmp/test_uploads"),
        Path("/tmp/test_results/markdown"),
        Path("/tmp/test_results/excel"),
        Path("/tmp/logs"),
    ]:
        d.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def app():
    from backend.main import app
    return app


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """A small CSV file for upload tests."""
    p = tmp_path / "sample.csv"
    p.write_text("id,name,value\n1,alpha,10\n2,beta,20\n3,gamma,30\n")
    return p


@pytest.fixture
def sample_xlsx(tmp_path: Path) -> Path:
    """A small Excel file for upload tests."""
    import pandas as pd
    p = tmp_path / "sample.xlsx"
    df = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"], "value": [100, 200, 300]})
    df.to_excel(p, index=False)
    return p

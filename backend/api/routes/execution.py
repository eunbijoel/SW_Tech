"""
Remote execution API routes.

POST /api/v1/execution/gpu       — submit code to RTX 5090 GPU server
GET  /api/v1/execution/gpu/status — GPU server status
POST /api/v1/execution/spark/sql  — run Spark SQL on uploaded files
GET  /api/v1/execution/spark/status — Spark status
"""
from fastapi import APIRouter, HTTPException

from backend.models.execution import GPUJobRequest, GPUJobResponse
from backend.services.remote.gpu_executor import gpu_executor
from backend.services.remote.spark_executor import spark_executor
from backend.services.file_service import file_service
from backend.core.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.post("/gpu", response_model=GPUJobResponse)
async def run_on_gpu(req: GPUJobRequest) -> GPUJobResponse:
    if not gpu_executor.is_configured:
        raise HTTPException(status_code=400, detail="GPU server not configured")
    job = await gpu_executor.submit(req.code, req.context)
    return GPUJobResponse(
        job_id=job.id,
        status=job.status,  # type: ignore[arg-type]
        result=job.result,
        error=job.error,
    )


@router.get("/gpu/status")
async def gpu_status() -> dict:
    return {
        "configured": gpu_executor.is_configured,
        "api_url": str(gpu_executor._api_url) if gpu_executor._api_url else None,
        "ssh_host": gpu_executor._ssh_host,
    }


@router.post("/spark/sql")
async def run_spark_sql(file_ids: list[str], sql: str) -> dict:
    if not spark_executor.is_configured:
        raise HTTPException(status_code=400, detail="Spark not configured")
    paths = []
    for fid in file_ids:
        path = file_service.get_path(fid)
        if path is None:
            raise HTTPException(status_code=404, detail=f"File {fid} not found")
        paths.append(path)
    try:
        df = await spark_executor.run_sql(paths, sql)
        return {
            "rows": len(df),
            "cols": len(df.columns),
            "preview": df.head(50).to_dict(orient="records"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spark/status")
async def spark_status() -> dict:
    return {
        "configured": spark_executor.is_configured,
        "master_url": spark_executor._master,
    }

"""
Apache Spark distributed execution adapter.

Used for large-scale Excel/CSV processing that exceeds single-machine
pandas capacity (typically > 10 GB or > 100 M rows).

Requires: pyspark installed and SPARK_MASTER_URL configured.
Falls back gracefully to pandas if Spark is not available.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from backend.core.config import settings
from backend.core.logging import get_logger

log = get_logger(__name__)


class SparkExecutor:
    """
    Wraps PySpark for distributed DataFrame operations.
    Operations are expressed as SQL strings or transformation configs.
    """

    def __init__(self) -> None:
        self._master = settings.SPARK_MASTER_URL
        self._driver_mem  = settings.SPARK_DRIVER_MEMORY
        self._exec_mem    = settings.SPARK_EXECUTOR_MEMORY
        self._session = None

    @property
    def is_configured(self) -> bool:
        return bool(self._master)

    def _get_session(self):  # type: ignore[return]
        """Lazy Spark session initialization."""
        if self._session is not None:
            return self._session
        try:
            from pyspark.sql import SparkSession  # type: ignore[import]
            self._session = (
                SparkSession.builder
                .master(self._master)
                .appName("AI Prompt Platform")
                .config("spark.driver.memory", self._driver_mem)
                .config("spark.executor.memory", self._exec_mem)
                .getOrCreate()
            )
            log.info("Spark session created", master=self._master)
            return self._session
        except ImportError:
            raise RuntimeError("pyspark not installed. Run: pip install pyspark")

    async def run_sql(self, file_paths: list[Path], sql: str) -> pd.DataFrame:
        """
        Load files as Spark DataFrames, register as temp views,
        execute SQL, and return a pandas DataFrame.

        Table names: file_0, file_1, …
        """
        if not self.is_configured:
            raise RuntimeError("Spark not configured. Set SPARK_MASTER_URL.")

        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._run_sql_sync, file_paths, sql
        )

    def _run_sql_sync(self, file_paths: list[Path], sql: str) -> pd.DataFrame:
        spark = self._get_session()
        for i, path in enumerate(file_paths):
            df = spark.read.option("header", "true").option("inferSchema", "true")
            ext = path.suffix.lower()
            if ext == ".csv":
                sdf = df.csv(str(path))
            else:
                sdf = df.format("com.crealytics.spark.excel").load(str(path))
            sdf.createOrReplaceTempView(f"file_{i}")
            log.info("Registered Spark view", view=f"file_{i}", path=str(path))

        result_sdf = spark.sql(sql)
        return result_sdf.toPandas()

    async def merge_files(
        self, file_paths: list[Path], strategy: str = "union"
    ) -> pd.DataFrame:
        """
        Convenience wrapper for common merge operations.
        strategy: "union" | "intersect" | "join_on_key"
        """
        if not self.is_configured:
            # Graceful pandas fallback
            log.warning("Spark unavailable — falling back to pandas merge")
            return self._pandas_merge(file_paths, strategy)

        if strategy == "union":
            views = " UNION ALL ".join(f"SELECT * FROM file_{i}" for i in range(len(file_paths)))
            sql = f"SELECT * FROM ({views})"
        else:
            sql = "SELECT * FROM file_0"   # extend for other strategies

        return await self.run_sql(file_paths, sql)

    def _pandas_merge(self, file_paths: list[Path], strategy: str) -> pd.DataFrame:
        frames = []
        for path in file_paths:
            frames.append(
                pd.read_csv(path) if path.suffix.lower() == ".csv"
                else pd.read_excel(path, engine="openpyxl")
            )
        if strategy == "union":
            return pd.concat(frames, ignore_index=True)
        return frames[0]

    def stop(self) -> None:
        if self._session:
            self._session.stop()
            self._session = None
            log.info("Spark session stopped")


spark_executor = SparkExecutor()

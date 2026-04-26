"""
Managed Agent Monitor: monitora execuções CMA e expõe métricas de observabilidade.

Métricas rastreadas:
  - execuções totais (por executor_type e status)
  - latência (média, p95)
  - taxa de sucesso
  - consumo de tokens

Integra com logging estruturado para ser consumido por ferramentas como Datadog/Grafana.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ManagedAgents.Monitor")


@dataclass
class _ExecutionRecord:
    session_id: str
    task_id: str
    executor_type: str
    status: str
    tokens_input: int
    tokens_output: int
    execution_time_seconds: float
    started_at: float = field(default_factory=time.monotonic)


class ManagedAgentMonitor:
    """
    Singleton de métricas in-process para execuções CMA.

    Uso:
        monitor = ManagedAgentMonitor.get_instance()
        monitor.record_execution(...)
        stats = monitor.get_stats()
    """

    _instance: Optional["ManagedAgentMonitor"] = None

    def __init__(self) -> None:
        self._records: List[_ExecutionRecord] = []
        self._counts: Dict[str, int] = defaultdict(int)

    @classmethod
    def get_instance(cls) -> "ManagedAgentMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_execution(
        self,
        session_id: str,
        task_id: str,
        executor_type: str,
        status: str,
        tokens_input: int,
        tokens_output: int,
        execution_time_seconds: float,
    ) -> None:
        record = _ExecutionRecord(
            session_id=session_id,
            task_id=task_id,
            executor_type=executor_type,
            status=status,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            execution_time_seconds=execution_time_seconds,
        )
        self._records.append(record)
        key = f"{executor_type}.{status}"
        self._counts[key] += 1

        logger.info(
            "CMA_METRIC executor_type=%s status=%s session_id=%s task_id=%s "
            "tokens_in=%d tokens_out=%d elapsed=%.3fs",
            executor_type, status, session_id, task_id,
            tokens_input, tokens_output, execution_time_seconds,
        )

    def get_stats(self) -> Dict[str, Any]:
        if not self._records:
            return {
                "total": 0,
                "success_rate": 0.0,
                "avg_latency_seconds": 0.0,
                "p95_latency_seconds": 0.0,
                "total_tokens_input": 0,
                "total_tokens_output": 0,
                "by_executor": {},
            }

        total = len(self._records)
        successful = [r for r in self._records if r.status in ("completed", "done")]
        latencies = sorted(r.execution_time_seconds for r in self._records)

        p95_idx = max(0, int(len(latencies) * 0.95) - 1)
        p95 = latencies[p95_idx] if latencies else 0.0

        by_executor: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "success": 0})
        for r in self._records:
            by_executor[r.executor_type]["count"] += 1
            if r.status in ("completed", "done"):
                by_executor[r.executor_type]["success"] += 1

        return {
            "total": total,
            "success_rate": round(len(successful) / total, 3) if total else 0.0,
            "avg_latency_seconds": round(sum(latencies) / len(latencies), 3),
            "p95_latency_seconds": round(p95, 3),
            "total_tokens_input": sum(r.tokens_input for r in self._records),
            "total_tokens_output": sum(r.tokens_output for r in self._records),
            "by_executor": dict(by_executor),
            "counts": dict(self._counts),
        }

    def reset(self) -> None:
        """Reseta métricas — útil para testes."""
        self._records.clear()
        self._counts.clear()


# Singleton global
monitor = ManagedAgentMonitor.get_instance()

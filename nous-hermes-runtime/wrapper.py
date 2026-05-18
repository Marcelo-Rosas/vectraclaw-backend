"""
HTTP thin wrapper para o CLI Hermes (Nous Research).

O backend VectraClaw resolve adapter_catalog / field_values e envia
`hermes_config` + `api_key` em cada POST /exec (regra de ouro #2).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("NousHermes.Wrapper")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="VectraClaw Nous Hermes Runtime", version="0.1.0")

_DEFAULT_TIMEOUT_S = 180
_DEFAULT_MAX_TURNS = 20


class HermesConfigPayload(BaseModel):
    """Config resolvida pelo backend VectraClaw — sem defaults de produto."""

    inference_provider: str = Field(..., description="openrouter | ollama | anthropic")
    model_id: str = Field(..., min_length=1, description="Modelo Hermes/OpenRouter/Ollama")
    approval_mode: str = Field(..., min_length=1)
    max_turns: int = Field(..., ge=1, le=90)
    ollama_base_url: Optional[str] = Field(
        default=None,
        description="Base URL Ollama (sem /v1) quando provider=ollama",
    )


class ExecRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=200_000)
    hermes_config: HermesConfigPayload
    api_key: Optional[str] = Field(default=None, description="Chave resolvida pelo backend (Vault)")
    max_turns: Optional[int] = Field(default=None, ge=1, le=90)
    ignore_user_config: bool = Field(default=True)
    timeout_seconds: int = Field(default=_DEFAULT_TIMEOUT_S, ge=30, le=600)


class ExecResponse(BaseModel):
    success: bool
    content: str
    exit_code: int
    duration_ms: int
    error: Optional[str] = None


def _hermes_bin() -> str:
    path = shutil.which("hermes")
    if not path:
        raise RuntimeError("binário 'hermes' não encontrado no PATH")
    return path


def _apply_hermes_cli_config(cfg: HermesConfigPayload, api_key: Optional[str]) -> Dict[str, str]:
    """Aplica config via `hermes config set` e monta env para o subprocess."""
    hermes = _hermes_bin()
    provider = cfg.inference_provider.strip().lower()
    model = cfg.model_id.strip()
    approval = cfg.approval_mode.strip().lower()

    sets: list[tuple[str, str]] = [
        ("model.provider", provider),
        ("approval.mode", approval),
    ]
    if model:
        sets.append(("model.default", model))
    if provider == "ollama" and cfg.ollama_base_url:
        base = cfg.ollama_base_url.rstrip("/")
        sets.append(("model.ollama_base_url", base))

    for key, value in sets:
        try:
            subprocess.run(
                [hermes, "config", "set", key, value],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            logger.warning("hermes config set %s falhou: %s", key, exc)

    env = os.environ.copy()
    if api_key:
        key = api_key.strip()
        if provider == "openrouter":
            env["OPENROUTER_API_KEY"] = key
        elif provider == "anthropic":
            env["ANTHROPIC_API_KEY"] = key
        elif provider == "ollama":
            pass
        else:
            env["OPENROUTER_API_KEY"] = key
    return env


def _run_hermes_z(
    prompt: str,
    cfg: HermesConfigPayload,
    api_key: Optional[str],
    max_turns: int,
    ignore_user_config: bool,
    timeout_seconds: int,
) -> ExecResponse:
    hermes = _hermes_bin()
    env = _apply_hermes_cli_config(cfg, api_key)
    cmd = [hermes, "-z", prompt]
    if ignore_user_config:
        cmd.append("--ignore-user-config")
    if max_turns:
        cmd.extend(["--max-turns", str(max_turns)])

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecResponse(
            success=False,
            content="",
            exit_code=-1,
            duration_ms=duration_ms,
            error=f"timeout após {timeout_seconds}s: {exc}",
        )
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ExecResponse(
            success=False,
            content="",
            exit_code=-1,
            duration_ms=duration_ms,
            error=str(exc),
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    content = stdout or stderr
    success = proc.returncode == 0 and bool(stdout)
    error = None if success else (stderr or f"exit {proc.returncode}")
    return ExecResponse(
        success=success,
        content=content,
        exit_code=int(proc.returncode),
        duration_ms=duration_ms,
        error=error,
    )


@app.get("/health")
def health() -> Dict[str, Any]:
    try:
        hermes = _hermes_bin()
        proc = subprocess.run(
            [hermes, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
        version = (proc.stdout or proc.stderr or "").strip() or "unknown"
        return {"status": "ok", "hermes_version": version, "hermes_path": hermes}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/exec", response_model=ExecResponse)
def exec_prompt(body: ExecRequest) -> ExecResponse:
    cfg = body.hermes_config
    max_turns = body.max_turns if body.max_turns is not None else cfg.max_turns
    return _run_hermes_z(
        prompt=body.prompt,
        cfg=cfg,
        api_key=body.api_key,
        max_turns=max_turns,
        ignore_user_config=body.ignore_user_config,
        timeout_seconds=body.timeout_seconds,
    )

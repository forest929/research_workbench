"""Thin async wrapper around Nebius Token Factory (OpenAI-compatible)."""

import time
import asyncpg
from openai import AsyncOpenAI

from portfolio_architect.config import get_settings
from portfolio_architect.db.query_log import log_llm_call

_settings = get_settings()

_generation_client: AsyncOpenAI | None = None
_judge_client: AsyncOpenAI | None = None
_finetuned_client: AsyncOpenAI | None = None


def _get_generation_client() -> AsyncOpenAI:
    global _generation_client
    if _generation_client is None:
        _generation_client = AsyncOpenAI(
            base_url=_settings.token_factory_base_url,
            api_key=_settings.nebius_key or "placeholder",
            timeout=_settings.generation_timeout_s,
            max_retries=_settings.generation_max_retries,
        )
    return _generation_client


def _get_finetuned_client() -> AsyncOpenAI:
    """Client for the self-hosted vLLM LoRA adapter (see runbook §4). Reached
    via SSH tunnel; separate from the Token Factory client so a down VM can
    never interfere with base generation."""
    global _finetuned_client
    if _finetuned_client is None:
        if not _settings.finetuned_enabled:
            raise RuntimeError(
                "Fine-tuned endpoint not configured "
                "(set FINETUNED_BASE_URL and FINETUNED_MODEL)."
            )
        _finetuned_client = AsyncOpenAI(
            base_url=_settings.finetuned_base_url,
            api_key=_settings.finetuned_api_key,
            timeout=_settings.finetuned_timeout_s,
        )
    return _finetuned_client


def _get_judge_client() -> AsyncOpenAI:
    global _judge_client
    if _judge_client is None:
        _judge_client = AsyncOpenAI(
            base_url=_settings.token_factory_base_url,
            api_key=_settings.nebius_key or "placeholder",
        )
    return _judge_client


async def _call(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    call_type: str,
    conn: asyncpg.Connection | None,
    project_id=None,
) -> str:
    t0 = time.monotonic()
    err = None
    try:
        response = await client.chat.completions.create(  # type: ignore[union-attr]
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        latency_ms = int((time.monotonic() - t0) * 1000)
        if conn:
            await log_llm_call(
                conn,
                call_type=call_type,
                model=model,
                project_id=project_id,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
                latency_ms=latency_ms,
                success=True,
            )
        return content
    except Exception as e:
        err = str(e)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if conn:
            await log_llm_call(
                conn,
                call_type=call_type,
                model=model,
                project_id=project_id,
                latency_ms=latency_ms,
                success=False,
                error_msg=err,
            )
        raise


async def generate(
    messages: list[dict],
    temperature: float = 0.0,
    call_type: str = "generation",
    conn: asyncpg.Connection | None = None,
    project_id=None,
) -> str:
    return await _call(
        _get_generation_client(),
        model=_settings.generation_model,
        messages=messages,
        temperature=temperature,
        max_tokens=_settings.max_tokens_generation,
        call_type=call_type,
        conn=conn,
        project_id=project_id,
    )


async def generate_finetuned(
    messages: list[dict],
    temperature: float = 0.2,
    call_type: str = "generation_finetuned",
    conn: asyncpg.Connection | None = None,
    project_id=None,
) -> str:
    """Generate via the self-hosted fine-tuned adapter. Raises if the endpoint
    is unconfigured or unreachable — callers (workbench) catch and fall back to
    base-only with an 'offline' note rather than failing the whole request."""
    return await _call(
        _get_finetuned_client(),
        model=_settings.finetuned_model,
        messages=messages,
        temperature=temperature,
        max_tokens=_settings.max_tokens_generation,
        call_type=call_type,
        conn=conn,
        project_id=project_id,
    )


async def judge(
    messages: list[dict],
    call_type: str = "judge_logical",
    conn: asyncpg.Connection | None = None,
    project_id=None,
) -> str:
    return await _call(
        _get_judge_client(),
        model=_settings.judge_model,
        messages=messages,
        temperature=0.0,
        max_tokens=_settings.max_tokens_judge,
        call_type=call_type,
        conn=conn,
        project_id=project_id,
    )

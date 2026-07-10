"""Thin async wrapper around Nebius Token Factory's fine-tuning API.

Kept separate from portfolio_architect/llm/client.py (chat completions for
generation/judging) since fine-tuning is a distinct concern with its own
client lifecycle — mirrors the same separation already used between
llm/client.py and embedding/client.py.
"""

from pathlib import Path

from openai import AsyncOpenAI

from portfolio_architect.config import get_settings

_settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=_settings.token_factory_base_url,
            api_key=_settings.nebius_key,
        )
    return _client


async def upload_file(path: Path, purpose: str = "fine-tune") -> str:
    client = _get_client()
    with open(path, "rb") as f:
        result = await client.files.create(file=f, purpose=purpose)
    return result.id


async def create_job(
    training_file_id: str,
    validation_file_id: str | None,
    model: str,
    hyperparameters: dict,
    suffix: str | None = None,
    seed: int | None = None,
) -> dict:
    client = _get_client()
    kwargs: dict = {
        "training_file": training_file_id,
        "model": model,
        "hyperparameters": hyperparameters,
    }
    if validation_file_id:
        kwargs["validation_file"] = validation_file_id
    if suffix:
        kwargs["suffix"] = suffix
    if seed is not None:
        kwargs["seed"] = seed
    job = await client.fine_tuning.jobs.create(**kwargs)
    return job.model_dump()


async def get_job(job_id: str) -> dict:
    client = _get_client()
    job = await client.fine_tuning.jobs.retrieve(job_id)
    return job.model_dump()


async def list_checkpoints(job_id: str) -> list[dict]:
    client = _get_client()
    result = await client.fine_tuning.jobs.checkpoints.list(job_id)
    return [c.model_dump() for c in result.data]

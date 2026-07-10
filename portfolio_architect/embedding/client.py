"""Embedding client via Nebius AI Endpoints (OpenAI-compatible embeddings API)."""

from openai import AsyncOpenAI
from portfolio_architect.config import get_settings

_settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not _settings.nebius_embedding_url:
            raise RuntimeError(
                "NEBIUS_EMBEDDING_URL is not set. "
                "Deploy an embedding endpoint on Nebius and set the URL."
            )
        _client = AsyncOpenAI(
            base_url=_settings.nebius_embedding_url,
            api_key=_settings.nebius_key,
        )
    return _client


async def embed_text(text: str) -> list[float]:
    client = _get_client()
    response = await client.embeddings.create(
        model=_settings.embedding_model,
        input=text,
    )
    return response.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = _get_client()
    response = await client.embeddings.create(
        model=_settings.embedding_model,
        input=texts,
    )
    # Sort by index to preserve input order
    items = sorted(response.data, key=lambda x: x.index)
    return [item.embedding for item in items]

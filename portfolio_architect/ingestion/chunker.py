"""Text chunking utilities — shared by the API router and ingest scripts."""

DEFAULT_CHUNK_SIZE = 512     # characters
DEFAULT_OVERLAP_RATIO = 0.1  # 10 % overlap


def chunk_text(
    text: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int | None = None,
) -> list[str]:
    """Split *text* into fixed-size chunks with overlap.

    Returns at least one chunk even for very short input.
    """
    if overlap is None:
        overlap = max(1, size // round(1 / DEFAULT_OVERLAP_RATIO))
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        start += size - overlap
    return chunks or [text]

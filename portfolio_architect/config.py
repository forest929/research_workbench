from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Nebius Token Factory
    nebius_key: str = ""
    generation_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    judge_model: str = "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1"
    token_factory_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    # Per-request cap on hosted-LLM calls. The SDK default is 600s with 2
    # retries, so one hung Token Factory response can stall a batch for minutes
    # (and get retried into 3x that). Callers that can tolerate a miss (e.g.
    # claim extraction treats a failure as "no claims") get bounded tail latency.
    generation_timeout_s: float = 75.0
    generation_max_retries: int = 1

    # Self-hosted fine-tuned LoRA adapter (vLLM), reached via SSH tunnel.
    # Empty when the GPU VM is down — the workbench then degrades to base-only.
    # See docs/lora_finetuning_runbook.md §4.
    finetuned_base_url: str = ""     # e.g. http://127.0.0.1:8000/v1/
    finetuned_model: str = ""        # the vLLM --lora-modules adapter name
    finetuned_api_key: str = "EMPTY"  # vLLM ignores it but the client requires a value
    finetuned_timeout_s: float = 30.0

    # Nebius Embeddings Endpoint
    nebius_embedding_url: str = ""
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # Database (SQLite file path)
    database_path: str = "portfolio_architect.db"

    # Application
    api_base_url: str = "http://localhost:8000"
    retrieval_top_k: int = 15
    evolutionary_n_mutations: int = 3
    max_tokens_generation: int = 2048
    # The judge model (Nemotron-Ultra) always emits a <think> reasoning trace
    # before the JSON verdict. That trace is variable and occasionally runs to
    # ~2000+ tokens; at 3072 the reasoning could eat the budget and truncate the
    # JSON, producing "not valid JSON" failed grades. 6144 gives the reasoning
    # headroom so the ~300-token JSON verdict always lands intact.
    max_tokens_judge: int = 6144

    @property
    def finetuned_enabled(self) -> bool:
        return bool(self.finetuned_base_url and self.finetuned_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

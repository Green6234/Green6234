"""Load Alpaca and app configuration from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    secret_key: str
    paper: bool = True

    @property
    def trading_base_url(self) -> str:
        return "https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets"


@lru_cache(maxsize=1)
def get_alpaca_config() -> AlpacaConfig:
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not api_key or not secret_key:
        raise ValueError(
            "Alpaca credentials required. Set ALPACA_API_KEY and ALPACA_SECRET_KEY "
            "in your environment or a .env file (see .env.example)."
        )
    paper = os.getenv("ALPACA_PAPER", "true").lower() in ("1", "true", "yes")
    return AlpacaConfig(api_key=api_key, secret_key=secret_key, paper=paper)

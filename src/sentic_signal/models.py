"""Pydantic data contracts for the Sentic-Signal ingestor.

NewsItem is the canonical output of this service — published to the
raw-news RabbitMQ queue for downstream consumers (analyst worker, notifier).

The schema is defined by Sentic-Signal — providers adapt to it, not the other
way around. Adding a new provider means writing a normaliser that outputs these
models, not changing the models themselves.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class SentimentLabel(str, Enum):
    BULLISH = "Bullish"
    SOMEWHAT_BULLISH = "Somewhat-Bullish"
    NEUTRAL = "Neutral"
    SOMEWHAT_BEARISH = "Somewhat-Bearish"
    BEARISH = "Bearish"


class NewsItem(BaseModel):
    """A single news article normalised from any provider.

    Every ingestor — regardless of the underlying API or feed — must produce
    NewsItem objects that conform to this schema. This is the "Sentic Standard"
    that enforces provider-agnostic behaviour throughout the pipeline.
    """

    ticker: str = Field(..., description="The equity ticker this article relates to.")
    headline: str = Field(..., description="Article title / headline.")
    url: HttpUrl = Field(..., description="Canonical URL of the article.")
    summary: str = Field(default="", description="Short article summary.")
    published: datetime = Field(..., description="UTC publication timestamp.")
    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ticker relevance score (0–1). Provider-supplied or heuristically computed.",
    )
    source_provider: str = Field(
        default="",
        description="Identifies the origin provider (e.g. 'alpha_vantage', 'yahoo_rss').",
    )
    provider_sentiment: SentimentLabel | None = Field(
        default=None,
        description=(
            "Sentiment label supplied by the provider. Not all providers include this "
            "(e.g. Yahoo RSS returns None). The analyst worker adds sentic_sentiment for all items."
        ),
    )
    sentic_sentiment: float | None = Field(
        default=None,
        description=(
            "Sentic-computed sentiment score in [-1.0, 1.0]. "
            "Populated by the analyst worker (Phase 2). None until then."
        ),
    )

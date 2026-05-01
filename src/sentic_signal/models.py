"""Pydantic data contracts for the Sentic-Signal ingestor.

NewsItem is the canonical output of this service — published to the raw-news
RabbitMQ queue. It is the contract at the signal→extractor boundary of the
five-stage pipeline (ADR-003):

    sentic-signal → [raw-news] → sentic-extractor → [rich-content]
    → sentic-aggregator → [enriched-batches] → sentic-analyst

The schema is defined by Sentic-Signal — providers adapt to it, not the other
way around. Adding a new provider means writing a normaliser that outputs these
models, not changing the models themselves.

Sentiment note
--------------
This service is a pure ingestor. It does not compute sentiment scores.
The war room agents in sentic-analyst produce the definitive analysis
(`AnalysisResult`) after receiving full-text batches from sentic-aggregator.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, computed_field


class SourceProvider(str, Enum):
    """Identifies the origin provider of a NewsItem.

    Typed as an enum so that sentic-extractor can make exhaustive, compile-time-
    checked decisions on whether full-text extraction via Jina Reader is required:

    - Tier 1 funnels return URL + summary only  → Jina extraction needed.
    - Tier 2 direct feeds may return full text  → extraction can be skipped.

    Adding a new provider forces an explicit code change here and in the extractor
    rather than silently falling through a string comparison.
    """

    # Tier 1 — Funnels (URL + summary only; Jina extraction required downstream)
    ALPHA_VANTAGE = "alpha_vantage"
    YAHOO_RSS = "yahoo_rss"
    FINNHUB = "finnhub"

    # Tier 2 — Direct feeds (Phase 5; may carry full text, skip Jina)
    STAT_NEWS_RSS = "stat_news_rss"
    SEC_EDGAR = "sec_edgar"


class NewsItem(BaseModel):
    """A single news article normalised from any provider.

    Every ingestor — regardless of the underlying API or feed — must produce
    NewsItem objects that conform to this schema. This is the "Sentic Standard"
    that enforces provider-agnostic behaviour throughout the pipeline.

    Fields carry only core discovery data: who, what, where, when, from where.
    No provider-specific analysis (sentiment labels, relevance scores) crosses
    this boundary — those are internal ingestor concerns.
    """

    ticker: str = Field(..., description="The equity ticker this article relates to.")
    headline: str = Field(..., description="Article title / headline.")
    url: HttpUrl = Field(..., description="Canonical URL of the article.")
    summary: str | None = Field(
        default=None,
        description=(
            "Short article summary as returned by the provider. "
            "None when the provider supplies no summary. "
            "Used as a fallback by sentic-extractor when Jina Reader fails "
            "(paywall or timeout)."
        ),
    )
    published: AwareDatetime = Field(
        ..., description="UTC publication timestamp from the provider."
    )
    ingested_at: AwareDatetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when this item was ingested by sentic-signal.",
    )
    source_provider: SourceProvider = Field(
        ...,
        description=(
            "Origin provider. Used by sentic-extractor to decide whether "
            "full-text extraction via Jina Reader is needed."
        ),
    )

    @computed_field
    @property
    def item_id(self) -> uuid.UUID:
        """Stable deduplication key: UUID5 derived from url + ticker.

        Deterministic — the same article for the same ticker always produces
        the same item_id, regardless of which provider delivered it.
        Acts as the primary key when records are persisted.
        """
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{str(self.url)}:{self.ticker.upper()}")


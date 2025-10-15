"""Data models for cc-vec."""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, HttpUrl, Field, field_validator


class CrawlRecord(BaseModel):
    """Represents a record from Common Crawl index."""

    url: HttpUrl
    urlkey: str
    timestamp: str
    status: int = Field(ge=100, le=599)  # Valid HTTP status codes
    mime: Optional[str] = None
    digest: Optional[str] = None
    length: Optional[int] = Field(None, ge=0)
    offset: Optional[int] = Field(None, ge=0)
    filename: Optional[str] = None
    languages: Optional[List[str]] = None
    charset: Optional[str] = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v):
        """Validate timestamp format (Common Crawl uses yyyyMMddhhmmss)."""
        if len(v) not in [4, 6, 8, 10, 12, 14]:
            raise ValueError("Timestamp must be in format yyyy, yyyyMM, yyyyMMdd, etc.")
        return v


class ProcessedContent(BaseModel):
    """Represents content after processing and cleaning."""

    source_url: HttpUrl
    title: Optional[str] = None
    text: str
    chunks: List[str] = Field(min_length=1)  # Must have at least one chunk
    language: Optional[str] = None
    quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    metadata: Optional[Dict[str, Any]] = None
    processing_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("chunks")
    @classmethod
    def validate_chunks(cls, v):
        """Ensure chunks are not empty."""
        if not v or all(not chunk.strip() for chunk in v):
            raise ValueError("Chunks cannot be empty")
        return v


class FilterConfig(BaseModel):
    """Configuration for filtering Common Crawl data."""

    url_patterns: Optional[List[str]] = None  # Filter by URL pattern (supports * wildcards)
    url_host_names: Optional[List[str]] = None  # Filter by exact hostname
    url_host_tlds: Optional[List[str]] = None  # Filter by TLD (e.g., 'com', 'org', 'gov')
    url_host_registered_domains: Optional[List[str]] = None  # Filter by registered domain (e.g., 'example.com')
    url_paths: Optional[List[str]] = None  # Filter by URL path (supports % wildcards)
    crawl_ids: Optional[List[str]] = None  # Filter by specific crawl IDs
    status_codes: Optional[List[int]] = Field(default=[200])
    mime_types: Optional[List[str]] = Field(default=["text/html"])
    charsets: Optional[List[str]] = None  # Filter by content charset
    languages: Optional[List[str]] = None
    date_from: Optional[str] = None  # Format: yyyy, yyyyMM, or yyyyMMdd
    date_to: Optional[str] = None
    custom_filters: Optional[List[str]] = None  # Additional CDX filter strings

    @field_validator("status_codes")
    @classmethod
    def validate_status_codes(cls, v):
        """Validate HTTP status codes."""
        if v:
            for code in v:
                if not (100 <= code <= 599):
                    raise ValueError(f"Invalid HTTP status code: {code}")
        return v


class VectorStoreConfig(BaseModel):
    """Configuration for vector store creation."""

    name: str
    chunk_size: int = 800
    overlap: int = 400
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    @field_validator("chunk_size")
    @classmethod
    def validate_chunk_size(cls, v):
        """Validate chunk size is within OpenAI limits."""
        if not (100 <= v <= 4096):
            raise ValueError("chunk_size must be between 100 and 4096")
        return v

    @field_validator("overlap")
    @classmethod
    def validate_overlap(cls, v, info):
        """Validate overlap doesn't exceed half of chunk_size."""
        chunk_size = info.data.get("chunk_size", 800)
        if v > chunk_size / 2:
            raise ValueError(
                f"overlap ({v}) must not exceed half of chunk_size ({chunk_size})"
            )
        return v

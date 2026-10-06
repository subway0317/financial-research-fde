"""Shared transport with explicit failures, content vintage and bounded requests."""

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from financial_research.exceptions import DataValidationError, ProviderError
from financial_research.schemas.provenance import ProvenanceRecord, SourceType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonResponse:
    payload: dict[str, Any]
    provenance: ProvenanceRecord


class JsonTransport:
    def __init__(
        self,
        provider: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30,
        user_agent: str = "financial-research-fde/0.1",
        minimum_interval: float = 0,
    ) -> None:
        self.provider = provider
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self._owns_client = client is None
        self._timeout = timeout
        self._user_agent = user_agent
        self._minimum_interval = minimum_interval
        self._last_request = 0.0

    def get(self, url: str, *, params: dict[str, str | int] | None = None) -> JsonResponse:
        delay = self._minimum_interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        logger.info("provider request provider=%s source=%s", self.provider, url)
        self._last_request = time.monotonic()
        try:
            response = self._client.get(
                url, params=params, timeout=self._timeout, headers={"User-Agent": self._user_agent}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.provider} request failed for {url}: {type(exc).__name__}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataValidationError(f"{self.provider}: invalid JSON from {url}") from exc
        if not isinstance(payload, dict):
            raise DataValidationError(f"{self.provider}: expected JSON object from {url}")
        digest = hashlib.sha256(response.content).hexdigest()
        return JsonResponse(
            payload=payload,
            provenance=ProvenanceRecord(
                provider=self.provider,
                source_type=SourceType.SOURCE_FACT,
                source_reference=str(response.url),
                retrieved_at=datetime.now(UTC),
                data_vintage=f"sha256:{digest}",
                content_hash=digest,
            ),
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

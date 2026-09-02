"""HTTP adapters for external web search and page retrieval."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlparse

import httpx

from .domain import Document, SearchHit


def validate_external_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme.lower() != "https":
        raise ValueError("external URLs must use HTTPS")
    if not host or parsed.username or parsed.password:
        raise ValueError("external URL has an invalid host")
    normalized_host = host.lower().rstrip(".")
    if normalized_host in {"localhost", "localhost.localdomain"} or normalized_host.endswith(".local"):
        raise ValueError("local external URLs are not allowed")
    try:
        address = ipaddress.ip_address(normalized_host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("private or local external URLs are not allowed")
    except ValueError as exc:
        if str(exc).endswith("not allowed"):
            raise
    return url


class _TextParser(HTMLParser):
    _ignored: ClassVar[set[str]] = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}
    _block: ClassVar[set[str]] = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self.section: str | None = None
        self._ignored_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._ignored:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth or not data.strip():
            return
        value = re.sub(r"\s+", " ", data).strip()
        if self._in_title:
            self.title = (self.title or "") + value
        else:
            self.parts.append(value)


class PageFetcher:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout: float = 20.0, max_bytes: int = 2_000_000) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self.client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=True)

    def fetch(self, url: str) -> Document:
        validate_external_url(url)
        response = self.client.get(url)
        response.raise_for_status()
        validate_external_url(str(response.url))
        if len(response.content) > self.max_bytes:
            raise ValueError("response exceeds configured size limit")
        content_type = response.headers.get("content-type", "")
        if content_type and not any(kind in content_type.lower() for kind in ("text/", "html", "xml")):
            raise ValueError("unsupported page content type")
        parser = _TextParser()
        parser.feed(response.text)
        text = "\n".join(part for part in parser.parts if part)
        title = parser.title or None
        return Document(
            source_id=hashlib.sha256(url.encode("utf-8")).hexdigest(), url=url,
            title=title, text=text, published_at=None,
        )

    def close(self) -> None:
        self.client.close()


class WebSearcher:
    def __init__(self, endpoint: str, api_key: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 20.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.client = httpx.Client(transport=transport, timeout=timeout)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if not query.strip():
            return []
        if limit < 1:
            raise ValueError("limit must be positive")
        response = self.client.get(
            f"{self.endpoint}/v7.0/search", params={"q": query, "count": limit, "responseFilter": "Webpages"},
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
        )
        response.raise_for_status()
        hits = []
        for item in response.json().get("webPages", {}).get("value", [])[:limit]:
            published = item.get("dateLastCrawled")
            hits.append(SearchHit(
                url=item["url"], title=item.get("name"), snippet=item.get("snippet", ""),
                published_at=datetime.fromisoformat(published) if published else None,
            ))
        return hits

    def close(self) -> None:
        self.client.close()

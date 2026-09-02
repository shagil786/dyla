"""HTTP adapters for external web search and page retrieval.

Hostname resolution is checked before each request. This prevents obvious DNS
resolution to private/link-local addresses, but httpx may resolve a hostname
again when opening the connection; eliminating that final TOCTOU/rebinding
window requires a custom transport that pins the resolved address while
preserving TLS SNI and certificate verification.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from collections.abc import Callable
from datetime import datetime
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urljoin, urlparse

import httpx

from .domain import Document, SearchHit

Resolver = Callable[..., list[tuple]]


def _default_resolver(host: str, port: int, **kwargs: object) -> list[tuple]:
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)


def validate_external_url(url: str, *, resolver: Resolver = _default_resolver) -> str:
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
        addresses = resolver(normalized_host, parsed.port or 443)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("external hostname could not be resolved safely") from exc
    if not addresses:
        raise ValueError("external hostname has no addresses")
    for address in addresses:
        raw_ip = address[4][0]
        try:
            ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
        except ValueError as exc:
            raise ValueError("external hostname resolved to an invalid address") from exc
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified or ip.is_multicast or not ip.is_global:
            raise ValueError("private, local, or non-public external URLs are not allowed")
    return url


class _TextParser(HTMLParser):
    _ignored: ClassVar[set[str]] = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
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
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout: float = 20.0, max_bytes: int = 2_000_000, max_redirects: int = 3, resolver: Resolver = _default_resolver) -> None:
        if max_bytes < 1 or max_redirects < 0:
            raise ValueError("max_bytes must be positive and max_redirects must not be negative")
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)

    def fetch(self, url: str) -> Document:
        current = validate_external_url(url, resolver=self.resolver)
        for redirect_count in range(self.max_redirects + 1):
            with self.client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response has no Location")
                    if redirect_count == self.max_redirects:
                        raise ValueError("maximum redirect count exceeded")
                    current = validate_external_url(urljoin(current, location), resolver=self.resolver)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_bytes:
                    raise ValueError("response exceeds configured size limit")
                content = bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content) > self.max_bytes:
                        raise ValueError("response exceeds configured size limit")
                content_type = response.headers.get("content-type", "")
                if content_type and not any(kind in content_type.lower() for kind in ("text/", "html", "xml")):
                    raise ValueError("unsupported page content type")
                parser = _TextParser()
                parser.feed(bytes(content).decode(response.encoding or "utf-8", errors="replace"))
                text = "\n".join(part for part in parser.parts if part)
                title = parser.title or None
                return Document(source_id=hashlib.sha256(current.encode("utf-8")).hexdigest(), url=current, title=title, text=text, published_at=None)
        raise ValueError("maximum redirect count exceeded")

    def close(self) -> None:
        self.client.close()


class WebSearcher:
    def __init__(self, endpoint: str, api_key: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 20.0, resolver: Resolver = _default_resolver) -> None:
        self.endpoint = validate_external_url(endpoint, resolver=resolver).rstrip("/")
        self.api_key = api_key
        self.resolver = resolver
        self.client = httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        if not query.strip():
            return []
        if limit < 1:
            raise ValueError("limit must be positive")
        response = self.client.get(f"{self.endpoint}/v7.0/search", params={"q": query, "count": limit, "responseFilter": "Webpages"}, headers={"Ocp-Apim-Subscription-Key": self.api_key})
        response.raise_for_status()
        hits = []
        for item in response.json().get("webPages", {}).get("value", [])[:limit]:
            try:
                result_url = validate_external_url(item["url"], resolver=self.resolver)
            except (KeyError, ValueError):
                continue
            published = item.get("dateLastCrawled")
            try:
                published_at = datetime.fromisoformat(published) if published else None
            except (TypeError, ValueError):
                published_at = None
            hits.append(SearchHit(url=result_url, title=item.get("name"), snippet=item.get("snippet", ""), published_at=published_at))
        return hits

    def close(self) -> None:
        self.client.close()

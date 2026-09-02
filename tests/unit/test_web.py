from datetime import datetime

import httpx
import pytest

from dyla.domain import Document, SearchHit
from dyla.web import PageFetcher, SearchProvider, YouResearchProvider, validate_external_url


PUBLIC_ADDRESSES = [(None, None, None, None, ("93.184.216.34", 443))]


def test_you_provider_normalizes_search_results_and_contents():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/search":
            assert request.headers["X-API-Key"] == "fake-you-key"
            assert request.url.params["query"] == "climate policy"
            return httpx.Response(200, json={"results": {"web": [
                {"url": "https://example.com/article", "title": "Article", "snippets": ["First", "Second"], "published_date": "2025-01-02T03:04:05+00:00"},
                {"url": "https://example.com/no-date", "title": "No date", "snippet": "One"},
            ]}})
        assert request.url.path == "/contents"
        assert request.url.params["url"] == "https://example.com/article"
        return httpx.Response(200, json={"contents": [{
            "url": "https://example.com/article", "title": "Article", "content": "Readable page text", "published_at": "2025-01-02T03:04:05+00:00"
        }]})

    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "fake-you-key",
        transport=httpx.MockTransport(handler), resolver=lambda host, port: PUBLIC_ADDRESSES,
    )

    assert isinstance(provider, SearchProvider)
    assert provider.search("climate policy", 2) == [
        SearchHit(url="https://example.com/article", title="Article", snippet="First Second", published_at=datetime.fromisoformat("2025-01-02T03:04:05+00:00")),
        SearchHit(url="https://example.com/no-date", title="No date", snippet="One", published_at=None),
    ]
    assert provider.fetch("https://example.com/article") == Document(
        source_id=provider._source_id("https://example.com/article"), url="https://example.com/article",
        title="Article", text="Readable page text", published_at=datetime.fromisoformat("2025-01-02T03:04:05+00:00"),
    )


def test_you_provider_skips_malformed_search_items_and_rejects_malformed_contents():
    responses = {
        "/search": httpx.Response(200, json={"results": {"web": [
            {"title": "missing url"}, {"url": "http://unsafe.example", "title": "unsafe"}
        ]}}),
        "/contents": httpx.Response(200, json={"contents": []}),
    }
    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "fake-you-key",
        transport=httpx.MockTransport(lambda request: responses[request.url.path]),
        resolver=lambda host, port: PUBLIC_ADDRESSES,
    )

    assert provider.search("query") == []
    with pytest.raises(ValueError, match="contents response"):
        provider.fetch("https://example.com/article")


def test_you_provider_auth_failure_is_propagated_without_secret():
    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "super-secret-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(401, text="invalid key")),
        resolver=lambda host, port: PUBLIC_ADDRESSES,
    )

    with pytest.raises(httpx.HTTPStatusError) as error:
        provider.search("query")
    assert "super-secret-key" not in str(error.value)


def test_you_provider_rejects_unsafe_fetch_before_contents_request():
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    def resolver(host, port):
        if host == "api.example.com":
            return PUBLIC_ADDRESSES
        return [(None, None, None, None, ("127.0.0.1", 443))]

    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "fake-you-key",
        transport=httpx.MockTransport(handler), resolver=resolver,
    )

    with pytest.raises(ValueError, match="non-public"):
        provider.fetch("https://example.com/private")
    assert called is False


def test_existing_page_fetcher_revalidates_redirects_and_bounds_stream():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": "http://localhost/private"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ignored")

    fetcher = PageFetcher(
        transport=httpx.MockTransport(handler), max_bytes=100,
        resolver=lambda host, port: PUBLIC_ADDRESSES,
    )
    with pytest.raises(ValueError, match="HTTPS"):
        fetcher.fetch("https://example.com/start")
    assert calls == ["https://example.com/start"]


def test_url_validation_rejects_private_dns_and_non_https():
    with pytest.raises(ValueError, match="HTTPS"):
        validate_external_url("http://example.com", resolver=lambda host, port: PUBLIC_ADDRESSES)
    with pytest.raises(ValueError, match="non-public"):
        validate_external_url("https://example.com", resolver=lambda host, port: [(None, None, None, None, ("10.0.0.1", 443))])

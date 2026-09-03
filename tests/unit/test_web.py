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
        assert request.method == "POST"
        assert request.headers["X-API-Key"] == "fake-you-key"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        assert request.read() == b'{"urls":["https://example.com/article"]}'
        return httpx.Response(200, json=[{
            "url": "https://example.com/article", "title": "Article", "markdown": "Readable **page** text", "html": "<p>Ignored HTML</p>",
            "metadata": {"published_date": "2025-01-02T03:04:05+00:00"}
        }])

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
        title="Article", text="Readable **page** text", published_at=datetime.fromisoformat("2025-01-02T03:04:05+00:00"),
    )


def test_you_provider_uses_html_when_markdown_is_missing():
    provider = provider_for(lambda request: httpx.Response(200, json=[{
        "url": "https://example.com/article",
        "title": "HTML article",
        "html": "<h1>Heading</h1><p>Readable HTML</p>",
    }]))

    assert provider.fetch("https://example.com/article").model_dump(exclude={"source_id", "published_at"}) == {
        "url": "https://example.com/article",
        "title": "HTML article",
        "text": "Heading\nReadable HTML",
    }


def test_you_provider_skips_malformed_search_items_and_rejects_malformed_contents():
    responses = {
        "/search": httpx.Response(200, json={"results": {"web": [
            {"title": "missing url"}, {"url": "http://unsafe.example", "title": "unsafe"}
        ]}}),
        "/contents": httpx.Response(200, json=[]),
    }
    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "fake-you-key",
        transport=httpx.MockTransport(lambda request: responses[request.url.path]),
        resolver=lambda host, port: PUBLIC_ADDRESSES,
    )

    assert provider.search("query") == []
    with pytest.raises(ValueError, match="contents response"):
        provider.fetch("https://example.com/article")


@pytest.mark.parametrize("status_code", [401, 403])
def test_you_provider_auth_failure_is_propagated_without_secret(status_code):
    provider = YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "super-secret-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(status_code, text="invalid key")),
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


@pytest.mark.parametrize("address", ["10.0.0.1", "::1", "ff02::1"])
def test_url_validation_rejects_private_ipv4_ipv6_and_multicast(address):
    with pytest.raises(ValueError, match="non-public"):
        validate_external_url("https://example.com", resolver=lambda host, port: [(None, None, None, None, (address, 443))])


def provider_for(handler, **kwargs):
    return YouResearchProvider(
        "https://api.example.com/search", "https://api.example.com/contents", "fake-you-key",
        transport=httpx.MockTransport(handler), resolver=lambda host, port: PUBLIC_ADDRESSES, **kwargs,
    )


def test_you_contents_reuses_content_length_and_streaming_byte_limits():
    provider = provider_for(
        lambda request: httpx.Response(200, headers={"content-type": "application/json", "content-length": "1000"}, json={}),
        max_bytes=10,
    )
    with pytest.raises(ValueError, match="size limit"):
        provider.fetch("https://example.com/article")

    provider = provider_for(
        lambda request: httpx.Response(200, headers={"content-type": "application/json"}, content=b"{" + b"x" * 100 + b"}"),
        max_bytes=10,
    )
    with pytest.raises(ValueError, match="size limit"):
        provider.fetch("https://example.com/article")


def test_you_contents_rejects_unsupported_content_type():
    provider = provider_for(lambda request: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf"))
    with pytest.raises(ValueError, match="unsupported"):
        provider.fetch("https://example.com/article")


def test_you_contents_enforces_redirect_limit_and_normalizes_html_content():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "https://api.example.com/contents?again=1"})

    provider = provider_for(handler, max_redirects=1)
    with pytest.raises(ValueError, match="maximum redirect"):
        provider.fetch("https://example.com/article")
    assert len(calls) == 2


def test_you_provider_rejects_structured_snippets_instead_of_stringifying_them():
    provider = provider_for(lambda request: httpx.Response(200, json={"results": {"web": [{"url": "https://example.com/article", "snippets": [{"text": "not a string"}]}]}}))
    assert provider.search("query")[0].snippet == ""

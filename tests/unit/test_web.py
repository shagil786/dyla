import httpx
import pytest


PUBLIC_RESOLVER = lambda host, port, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))]
PRIVATE_RESOLVER = lambda host, port, **kwargs: [(None, None, None, None, ("127.0.0.1", 0))]

from dyla.web import PageFetcher, WebSearcher, validate_external_url


def test_validate_external_url_requires_https_and_rejects_local_targets():
    assert validate_external_url("https://example.com/article", resolver=PUBLIC_RESOLVER) == "https://example.com/article"
    with pytest.raises(ValueError, match="private"):
        validate_external_url("https://public.example", resolver=PRIVATE_RESOLVER)
    with pytest.raises(ValueError, match="HTTPS"):
        validate_external_url("http://example.com")
    with pytest.raises(ValueError):
        validate_external_url("https://localhost/private")


@pytest.mark.parametrize("address", [
    "::1", "fe80::1", "fc00::1", "2001:db8::1", "::", "ff02::1",
    "100.64.0.1", "224.0.0.1",
])
def test_hostname_resolution_rejects_non_public_ipv4_and_ipv6_destinations(address):
    resolver = lambda host, port, **kwargs: [(None, None, None, None, (address, 0, 0, 0))]
    with pytest.raises(ValueError, match="private|local|public"):
        validate_external_url("https://resolved.example", resolver=resolver)


def test_hostname_resolution_accepts_public_ipv4_and_ipv6_destinations():
    for address in ("93.184.216.34", "2606:4700:4700::1111"):
        resolver = lambda host, port, address=address, **kwargs: [(None, None, None, None, (address, 0, 0, 0))]
        assert validate_external_url("https://resolved.example", resolver=resolver)


def test_page_fetcher_normalizes_html_and_removes_boilerplate():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="""<html><head><title>Research title</title></head><body>
            <nav>Navigation</nav><main><h1>Research title</h1><p>First paragraph.</p>
            <h2>Methods</h2><p>Important result.</p></main><footer>Copyright</footer>
            </body></html>""",
        )

    document = PageFetcher(transport=httpx.MockTransport(handler), resolver=PUBLIC_RESOLVER).fetch("https://example.com/a")
    assert document.title == "Research title"
    assert document.text == "Research title\nFirst paragraph.\nMethods\nImportant result."
    assert "Navigation" not in document.text
    assert document.source_id


def test_page_fetcher_enforces_response_size_limit():
    def handler(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="12345")

    with pytest.raises(ValueError, match="size"):
        PageFetcher(transport=httpx.MockTransport(handler), max_bytes=4, resolver=PUBLIC_RESOLVER).fetch("https://example.com")


def test_page_fetcher_validates_redirects_and_bounds_redirect_count():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": "https://private.example/secret"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="safe")

    def resolver(host, port, **kwargs):
        return PRIVATE_RESOLVER(host, port, **kwargs) if host == "private.example" else PUBLIC_RESOLVER(host, port, **kwargs)

    with pytest.raises(ValueError, match="private"):
        PageFetcher(transport=httpx.MockTransport(handler), resolver=resolver).fetch("https://example.com/start")
    assert len(calls) == 1


def test_page_fetcher_bounds_redirect_count():
    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    with pytest.raises(ValueError, match="maximum redirect"):
        PageFetcher(transport=httpx.MockTransport(handler), max_redirects=1, resolver=PUBLIC_RESOLVER).fetch("https://example.com")


def test_page_fetcher_enforces_content_length_before_reading_body():
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("body should not be read")

    def handler(request):
        return httpx.Response(200, headers={"content-length": "5", "content-type": "text/plain"}, stream=Body())

    with pytest.raises(ValueError, match="size"):
        PageFetcher(transport=httpx.MockTransport(handler), max_bytes=4, resolver=PUBLIC_RESOLVER).fetch("https://example.com")


def test_page_fetcher_enforces_streaming_limit_before_buffering():
    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=httpx.ByteStream(b"12345"))

    with pytest.raises(ValueError, match="size"):
        PageFetcher(transport=httpx.MockTransport(handler), max_bytes=4, resolver=PUBLIC_RESOLVER).fetch("https://example.com")


def test_web_searcher_validates_endpoint_and_result_urls_and_tolerates_bad_dates():
    def handler(request):
        return httpx.Response(200, json={"webPages": {"value": [
            {"url": "http://unsafe.example", "name": "A", "snippet": "Snippet", "dateLastCrawled": "bad"},
            {"url": "https://example.com/a", "name": "B", "snippet": "Good", "dateLastCrawled": "bad"},
        ]}})

    hits = WebSearcher("https://bing.example", "key", transport=httpx.MockTransport(handler), resolver=PUBLIC_RESOLVER).search("query", 2)
    assert [hit.url for hit in hits] == ["https://example.com/a"]
    assert hits[0].published_at is None


def test_web_searcher_maps_results():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/v7.0/search")
        assert request.headers["Ocp-Apim-Subscription-Key"] == "key"
        return httpx.Response(200, json={"webPages": {"value": [
            {"url": "https://example.com/a", "name": "A", "snippet": "Snippet", "dateLastCrawled": "2025-01-02T00:00:00Z"}
        ]}})

    hits = WebSearcher("https://bing.example", "key", transport=httpx.MockTransport(handler), resolver=PUBLIC_RESOLVER).search("query", 1)
    assert hits[0].url == "https://example.com/a"
    assert hits[0].title == "A"
    assert hits[0].snippet == "Snippet"

import httpx
import pytest

from dyla.web import PageFetcher, WebSearcher, validate_external_url


def test_validate_external_url_requires_https_and_rejects_local_targets():
    assert validate_external_url("https://example.com/article") == "https://example.com/article"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_external_url("http://example.com")
    with pytest.raises(ValueError):
        validate_external_url("https://localhost/private")


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

    document = PageFetcher(transport=httpx.MockTransport(handler)).fetch("https://example.com/a")
    assert document.title == "Research title"
    assert document.text == "Research title\nFirst paragraph.\nMethods\nImportant result."
    assert "Navigation" not in document.text
    assert document.source_id


def test_page_fetcher_enforces_response_size_limit():
    def handler(request: httpx.Request):
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="12345")

    with pytest.raises(ValueError, match="size"):
        PageFetcher(transport=httpx.MockTransport(handler), max_bytes=4).fetch("https://example.com")


def test_web_searcher_maps_results():
    def handler(request: httpx.Request):
        assert request.url.path.endswith("/v7.0/search")
        assert request.headers["Ocp-Apim-Subscription-Key"] == "key"
        return httpx.Response(200, json={"webPages": {"value": [
            {"url": "https://example.com/a", "name": "A", "snippet": "Snippet", "dateLastCrawled": "2025-01-02T00:00:00Z"}
        ]}})

    hits = WebSearcher("https://bing.example", "key", transport=httpx.MockTransport(handler)).search("query", 1)
    assert hits[0].url == "https://example.com/a"
    assert hits[0].title == "A"
    assert hits[0].snippet == "Snippet"

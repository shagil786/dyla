"""Composition boundary for selecting web providers from application settings."""

import httpx

from .config import Settings
from .ports import SearchProvider
from .web import YouResearchProvider, Resolver


def build_search_provider(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
) -> SearchProvider:
    """Construct the configured web adapter without exposing it to the core."""

    if settings.dyla_web_provider.casefold() == "you":
        return YouResearchProvider(
            settings.you_search_endpoint,
            settings.you_contents_endpoint,
            settings.you_api_key or "",
            transport=transport,
            resolver=resolver or _default_resolver,
        )
    raise ValueError(f"unsupported web provider: {settings.dyla_web_provider}")


def _default_resolver(host: str, port: int, **kwargs: object) -> list[tuple]:
    import socket

    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)

"""Configuration-driven provider registry and application composition."""
from __future__ import annotations
import importlib
import inspect
from dataclasses import dataclass
from typing import Any
import httpx
from .azure_models import AzureChatModel, AzureEmbeddingModel
from .compatible import CompatibleEmbeddingProvider, CompatibleModelProvider, LocalModelProvider
from .config import Settings
from .local_vector import LocalVectorStore
from .ports import SearchProvider
from .qdrant_vector import QdrantVectorStore
from .search import SearchIndex
from .web import Resolver, YouResearchProvider


def load_plugin(path: str, settings: Settings, **kwargs: Any) -> Any:
    try:
        module_name, function_name = path.split(":", 1)
        factory = getattr(importlib.import_module(module_name), function_name)
    except (ValueError, ImportError, AttributeError) as exc:
        raise ValueError(f"invalid provider plugin path: {path}") from exc
    if not callable(factory):
        raise ValueError(f"provider plugin is not callable: {path}")
    try:
        signature = inspect.signature(factory)
        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
            return factory(settings, **kwargs)
        positional = list(signature.parameters.values())
        if positional:
            return factory(settings)
        return factory()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"provider plugin could not be constructed: {path}") from exc


def _is_plugin(provider: str) -> bool:
    return ":" in provider


def build_model_provider(settings: Settings, *, transport: httpx.BaseTransport | None = None):
    provider = settings.dyla_model_provider.casefold()
    if _is_plugin(provider):
        return load_plugin(settings.dyla_model_provider, settings, transport=transport)
    if provider == "compatible":
        return CompatibleModelProvider(settings.model_base_url or "", settings.model_api_key or "", settings.model_name or "", transport=transport, extra_payload=settings.model_extra_payload)
    if provider == "azure":
        return AzureChatModel(settings, transport=transport)
    if provider == "local":
        return LocalModelProvider()
    raise ValueError(f"unsupported model provider: {settings.dyla_model_provider}")


def build_auditor_provider(settings: Settings, *, transport: httpx.BaseTransport | None = None):
    provider = settings.dyla_auditor_provider.casefold()
    if _is_plugin(provider):
        return load_plugin(settings.dyla_auditor_provider, settings, transport=transport)
    from .auditor import ModelComparator, _TextComparator
    if provider == "local":
        return _TextComparator()
    if provider == "compatible":
        model = CompatibleModelProvider(settings.auditor_base_url or settings.model_base_url or "", settings.auditor_api_key or settings.model_api_key or "", settings.auditor_model or settings.model_name or "", transport=transport, extra_payload=settings.auditor_extra_payload)
        return ModelComparator(model)
    if provider == "azure":
        return ModelComparator(AzureChatModel(settings, transport=transport, model_name=settings.auditor_model))
    raise ValueError(f"unsupported auditor provider: {settings.dyla_auditor_provider}")


def build_embedding_provider(settings: Settings, *, transport: httpx.BaseTransport | None = None, cache_path=None):
    provider = settings.dyla_embedding_provider.casefold()
    if _is_plugin(provider):
        return load_plugin(settings.dyla_embedding_provider, settings, transport=transport)
    if provider == "compatible":
        return CompatibleEmbeddingProvider(
            settings.embedding_base_url or "",
            settings.embedding_api_key or "",
            settings.embedding_model or "",
            transport=transport,
            batch_size=settings.embedding_batch_size,
            cache_path=cache_path,
        )
    if provider == "azure":
        return AzureEmbeddingModel(settings, transport=transport, cache_path=cache_path)
    if provider == "local":
        from .compatible import LocalEmbeddingProvider
        return LocalEmbeddingProvider()
    raise ValueError(f"unsupported embedding provider: {settings.dyla_embedding_provider}")


def build_vector_store(settings: Settings, *, embedder=None, transport: httpx.BaseTransport | None = None, qdrant_client=None):
    provider = settings.dyla_vector_store.casefold()
    if _is_plugin(provider):
        return load_plugin(settings.dyla_vector_store, settings, embedder=embedder, transport=transport)
    if provider == "local":
        return LocalVectorStore(vector_dimensions=None, embedder=embedder)
    if provider == "azure":
        if not settings.azure_search_endpoint or not settings.azure_search_api_key or not settings.azure_search_index:
            raise ValueError("Azure vector store requires Azure Search endpoint, API key, and index")
        return SearchIndex(settings, embedder=embedder, transport=transport)
    if provider == "qdrant":
        return QdrantVectorStore(settings, embedder=embedder, client=qdrant_client)
    if provider == "faiss":
        raise ValueError("unsupported vector store: faiss (use DYLA_VECTOR_STORE=local or a plugin)")
    raise ValueError(f"unsupported vector store: {settings.dyla_vector_store}")


def build_search_provider(settings: Settings, *, transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None) -> SearchProvider:
    provider = settings.dyla_web_provider.casefold()
    if _is_plugin(provider):
        return load_plugin(settings.dyla_web_provider, settings, transport=transport, resolver=resolver)
    if provider == "you":
        return YouResearchProvider(settings.you_search_endpoint, settings.you_contents_endpoint, settings.you_api_key or "", transport=transport, resolver=resolver or _default_resolver)
    raise ValueError(f"unsupported web provider: {settings.dyla_web_provider}")


@dataclass(frozen=True)
class ProviderBundle:
    model: Any
    auditor: Any
    embedding: Any
    vector_store: Any
    search: SearchProvider


def build_provider_bundle(settings: Settings, *, transport: httpx.BaseTransport | None = None, resolver: Resolver | None = None, cache_path=None) -> ProviderBundle:
    embedding = build_embedding_provider(settings, transport=transport, cache_path=cache_path)
    return ProviderBundle(model=build_model_provider(settings, transport=transport), auditor=build_auditor_provider(settings, transport=transport), embedding=embedding, vector_store=build_vector_store(settings, embedder=embedding, transport=transport), search=build_search_provider(settings, transport=transport, resolver=resolver))


def _default_resolver(host: str, port: int, **kwargs: object) -> list[tuple]:
    import socket
    return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)

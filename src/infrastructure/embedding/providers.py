# Time: 2026-04-19 00:07
# Description: 定义 embedding provider 抽象并提供 OpenAI 与本地确定性实现，支持批量、超时重试与错误码。
# Author: Feixue

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


class EmbeddingProviderError(Exception):
    """向量化阶段错误，统一附带错误码与可重试标记。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class EmbeddingProviderMeta:
    """embedding provider 元信息，持久化时用于审计字段。"""

    provider: str
    model: str
    embedding_version: str


class BaseEmbeddingProvider(ABC):
    """embedding provider 抽象，屏蔽具体厂商调用差异。"""

    def __init__(self, *, provider: str, model: str, embedding_version: str) -> None:
        self._meta = EmbeddingProviderMeta(
            provider=provider,
            model=model,
            embedding_version=embedding_version,
        )

    @property
    def meta(self) -> EmbeddingProviderMeta:
        return self._meta

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量向量化文本。"""


class DeterministicEmbeddingProvider(BaseEmbeddingProvider):
    """本地确定性 provider，用于无外网或测试环境回归。"""

    def __init__(self, *, dimension: int, embedding_version: str) -> None:
        super().__init__(
            provider="deterministic",
            model="deterministic-hash",
            embedding_version=embedding_version,
        )
        self._dimension = max(1, int(dimension))

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector: list[float] = []
            for idx in range(self._dimension):
                raw = digest[idx % len(digest)]
                vector.append(round((raw / 127.5) - 1.0, 6))
            vectors.append(vector)
        return vectors


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embeddings provider，固定模型 text-embedding-3-small。"""

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: int,
        max_retries: int,
        batch_size: int,
        embedding_version: str,
        base_url: str = "https://api.openai.com/v1",
    ) -> None:
        super().__init__(
            provider="openai",
            model="text-embedding-3-small",
            embedding_version=embedding_version,
        )
        self._api_key = api_key.strip()
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._max_retries = max(0, int(max_retries))
        self._batch_size = max(1, int(batch_size))
        self._base_url = base_url.rstrip("/")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self._api_key:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_API_KEY_MISSING",
                message="MODEL_API_KEY 未配置，无法调用 OpenAI embedding。",
                retryable=False,
            )

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(await self._embed_batch_with_retry(batch=batch))
        return vectors

    async def _embed_batch_with_retry(self, *, batch: list[str]) -> list[list[float]]:
        last_error: EmbeddingProviderError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._embed_batch_once(batch=batch)
            except EmbeddingProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self._max_retries:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))

        if last_error is None:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_UNKNOWN_ERROR",
                message="embedding 调用失败且未返回可识别错误。",
                retryable=False,
            )
        raise last_error

    async def _embed_batch_once(self, *, batch: list[str]) -> list[list[float]]:
        url = f"{self._base_url}/embeddings"
        payload = {
            "model": self.meta.model,
            "input": batch,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url=url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_TIMEOUT",
                message="embedding 调用超时。",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_HTTP_ERROR",
                message=f"embedding HTTP 异常: {exc}",
                retryable=True,
            ) from exc

        if response.status_code in {429, 500, 502, 503, 504}:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_PROVIDER_RETRYABLE",
                message=f"embedding provider 返回重试状态码: {response.status_code}",
                retryable=True,
            )

        if response.status_code in {401, 403}:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_AUTH_FAILED",
                message="embedding provider 鉴权失败。",
                retryable=False,
            )

        if response.status_code >= 400:
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_PROVIDER_ERROR",
                message=f"embedding provider 返回错误: {response.status_code}",
                retryable=False,
            )

        payload_json = response.json()
        raw_items = payload_json.get("data")
        if not isinstance(raw_items, list):
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_RESPONSE_INVALID",
                message="embedding provider 返回结构缺少 data 列表。",
                retryable=False,
            )

        vectors: list[list[float]] = []
        for item in raw_items:
            embedding = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(embedding, list):
                raise EmbeddingProviderError(
                    code="DOC_EMBEDDING_RESPONSE_INVALID",
                    message="embedding provider 返回向量字段无效。",
                    retryable=False,
                )
            vectors.append([float(value) for value in embedding])

        if len(vectors) != len(batch):
            raise EmbeddingProviderError(
                code="DOC_EMBEDDING_RESPONSE_COUNT_MISMATCH",
                message="embedding provider 返回向量数量与输入不一致。",
                retryable=False,
            )
        return vectors


def build_embedding_provider(
    *,
    provider_name: str,
    api_key: str,
    timeout_seconds: int,
    max_retries: int,
    batch_size: int,
    fallback_dimension: int,
    embedding_version: str,
) -> BaseEmbeddingProvider:
    """按配置构建 embedding provider。"""
    normalized = provider_name.strip().lower()
    if normalized == "openai":
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            batch_size=batch_size,
            embedding_version=embedding_version,
        )

    if normalized in {"deterministic", "stub_hash"}:
        return DeterministicEmbeddingProvider(
            dimension=fallback_dimension,
            embedding_version=embedding_version,
        )

    raise ValueError(f"unsupported_embedding_provider:{provider_name}")

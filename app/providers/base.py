from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import DetectedMaterial


class ProviderError(RuntimeError):
    pass


class VisionProvider(ABC):
    name = "unknown"

    @abstractmethod
    async def analyze(self, image_bytes: bytes, mime_type: str) -> DetectedMaterial:
        raise NotImplementedError


class UnavailableProvider(VisionProvider):
    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def analyze(self, image_bytes: bytes, mime_type: str) -> DetectedMaterial:
        del image_bytes, mime_type
        raise ProviderError(self.reason)


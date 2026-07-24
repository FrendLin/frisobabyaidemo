from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    vision_provider: str = "openai_compatible"
    vision_base_url: str = "https://api.openai.com/v1"
    vision_api_style: str = "auto"
    vision_api_key: str = ""
    vision_model: str = ""
    vision_reference_manifest: str = ""
    vision_examples_per_label: int = 1
    min_confidence: float = 0.70
    request_timeout_seconds: float = 60.0
    batch_concurrency: int = 4
    batch_max_rows: int = 200
    max_image_bytes: int = 15 * 1024 * 1024
    allowed_image_hosts: tuple[str, ...] = ("static.51dh.com.cn",)

    @classmethod
    def from_env(cls) -> "Settings":
        hosts = tuple(
            host.strip().lower()
            for host in os.getenv("ALLOWED_IMAGE_HOSTS", "static.51dh.com.cn").split(",")
            if host.strip()
        )
        return cls(
            vision_provider=os.getenv("VISION_PROVIDER", "openai_compatible").strip(),
            vision_base_url=os.getenv("VISION_BASE_URL", "https://api.openai.com/v1").strip(),
            vision_api_style=os.getenv("VISION_API_STYLE", "auto").strip().lower(),
            vision_api_key=os.getenv("VISION_API_KEY", "").strip(),
            vision_model=os.getenv("VISION_MODEL", "").strip(),
            vision_reference_manifest=os.getenv(
                "VISION_REFERENCE_MANIFEST", ""
            ).strip(),
            vision_examples_per_label=max(
                0, int(os.getenv("VISION_EXAMPLES_PER_LABEL", "1"))
            ),
            min_confidence=float(os.getenv("MIN_CONFIDENCE", "0.70")),
            request_timeout_seconds=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "60")),
            batch_concurrency=max(1, int(os.getenv("BATCH_CONCURRENCY", "4"))),
            batch_max_rows=max(1, int(os.getenv("BATCH_MAX_ROWS", "200"))),
            max_image_bytes=max(1024, int(os.getenv("MAX_IMAGE_BYTES", str(15 * 1024 * 1024)))),
            allowed_image_hosts=hosts,
        )

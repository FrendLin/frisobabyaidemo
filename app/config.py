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
    image_quality_api_url: str = "https://ai.xtion.net/api/ai/imagequality/blurdetect"
    image_quality_api_token: str = ""
    image_quality_review_descriptions: tuple[str, ...] = (
        "中",
        "高",
        "模糊",
        "严重模糊",
        "不合格",
    )
    oss_shared_config: str = "~/.codex/resources/oss/config.json"
    oss_profile: str = ""
    oss_project: str = "frisobabyaidemo"
    oss_subdir: str = "image-quality-check"
    oss_signed_url_ttl_seconds: int = 900
    # 图片标注筛选器的持久化目录（存标注 JSON，绝不写入用户原图目录）。
    labeling_data_dir: str = "data/labeling"
    # 标注结果联动的现有 POC 数据清单路径。
    labeling_manifest: str = "data/dataset_manifest.csv"

    @classmethod
    def from_env(cls) -> "Settings":
        hosts = tuple(
            host.strip().lower()
            for host in os.getenv("ALLOWED_IMAGE_HOSTS", "static.51dh.com.cn").split(",")
            if host.strip()
        )
        quality_review_descriptions = tuple(
            item.strip()
            for item in os.getenv(
                "IMAGE_QUALITY_REVIEW_DESCRIPTIONS",
                "中,高,模糊,严重模糊,不合格",
            ).split(",")
            if item.strip()
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
            image_quality_api_url=os.getenv(
                "IMAGE_QUALITY_API_URL",
                "https://ai.xtion.net/api/ai/imagequality/blurdetect",
            ).strip(),
            image_quality_api_token=os.getenv(
                "IMAGE_QUALITY_API_TOKEN",
                "",
            ).strip(),
            image_quality_review_descriptions=quality_review_descriptions,
            oss_shared_config=os.getenv(
                "OSS_SHARED_CONFIG",
                "~/.codex/resources/oss/config.json",
            ).strip(),
            oss_profile=os.getenv("OSS_PROFILE", "").strip(),
            oss_project=os.getenv("OSS_PROJECT", "frisobabyaidemo").strip(),
            oss_subdir=os.getenv(
                "OSS_IMAGE_QUALITY_SUBDIR",
                "image-quality-check",
            ).strip(),
            oss_signed_url_ttl_seconds=max(
                60,
                int(os.getenv("OSS_SIGNED_URL_TTL_SECONDS", "900")),
            ),
            labeling_data_dir=os.getenv("LABELING_DATA_DIR", "data/labeling").strip(),
            labeling_manifest=os.getenv(
                "LABELING_MANIFEST", "data/dataset_manifest.csv"
            ).strip(),
        )

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import posixpath
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.models import ExternalImageQuality


class ImageQualityServiceError(RuntimeError):
    """A safe, user-facing failure from quality checking or image publishing."""


class ImagePublisher(Protocol):
    async def publish(self, payload: bytes, mime_type: str) -> str: ...


class ImageQualityChecker(Protocol):
    async def inspect(self, image_url: str) -> ExternalImageQuality: ...


def _safe_component(value: str, label: str, *, nested: bool) -> str:
    normalized = value.strip().replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ImageQualityServiceError(f"{label} 配置不合法")
    if not nested and len(parts) != 1:
        raise ImageQualityServiceError(f"{label} 只能是单层目录名")
    return "/".join(parts)


def _load_oss_profile(settings: Settings) -> dict[str, Any]:
    config_path = Path(settings.oss_shared_config).expanduser()
    if not config_path.is_file():
        raise ImageQualityServiceError("未配置 OSS 共享资源，无法进行图片质量检查")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        profiles = config["profiles"]
        profile_name = settings.oss_profile or config["default_profile"]
        profile = dict(profiles[profile_name])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ImageQualityServiceError("OSS 共享配置格式不正确") from error

    overrides = {
        "endpoint": "OSS_ENDPOINT",
        "bucket": "OSS_BUCKET",
        "access_key_id": "OSS_ACCESS_KEY_ID",
        "access_key_secret": "OSS_ACCESS_KEY_SECRET",
        "security_token": "OSS_SECURITY_TOKEN",
        "root_prefix": "OSS_ROOT_PREFIX",
    }
    for field, environment_name in overrides.items():
        if os.getenv(environment_name):
            profile[field] = os.environ[environment_name]

    required = ("endpoint", "bucket", "access_key_id", "access_key_secret")
    if any(not profile.get(field) for field in required):
        raise ImageQualityServiceError("OSS 共享配置缺少必要字段")
    profile.setdefault("root_prefix", "projects")
    return profile


def _make_bucket(profile: dict[str, Any]):
    try:
        import oss2
    except ImportError as error:
        raise ImageQualityServiceError("未安装 OSS 客户端依赖") from error
    if profile.get("security_token"):
        auth = oss2.StsAuth(
            profile["access_key_id"],
            profile["access_key_secret"],
            profile["security_token"],
        )
    else:
        auth = oss2.Auth(
            profile["access_key_id"],
            profile["access_key_secret"],
        )
    return oss2.Bucket(auth, profile["endpoint"], profile["bucket"])


class OssImagePublisher:
    """Publish private, short-lived model inputs under a project-scoped key."""

    def __init__(
        self,
        settings: Settings,
        *,
        bucket_factory: Callable[[dict[str, Any]], Any] = _make_bucket,
    ) -> None:
        self.settings = settings
        self.bucket_factory = bucket_factory

    async def publish(self, payload: bytes, mime_type: str) -> str:
        return await asyncio.to_thread(self._publish, payload, mime_type)

    def _publish(self, payload: bytes, mime_type: str) -> str:
        profile = _load_oss_profile(self.settings)
        root_prefix = _safe_component(
            str(profile.get("root_prefix", "projects")),
            "OSS root_prefix",
            nested=True,
        )
        project = _safe_component(
            self.settings.oss_project,
            "OSS_PROJECT",
            nested=False,
        )
        subdir = _safe_component(
            self.settings.oss_subdir,
            "OSS_IMAGE_QUALITY_SUBDIR",
            nested=True,
        )
        suffix = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(mime_type, mimetypes.guess_extension(mime_type) or ".img")
        date_path = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        object_key = posixpath.join(
            root_prefix,
            project,
            subdir,
            date_path,
            f"{uuid.uuid4().hex}{suffix}",
        )

        bucket = self.bucket_factory(profile)
        try:
            result = bucket.put_object(
                object_key,
                payload,
                headers={
                    "Content-Type": mime_type,
                    "x-oss-object-acl": "private",
                },
            )
            if result.status not in (200, 201):
                raise ImageQualityServiceError("图片上传 OSS 失败")
            return str(
                bucket.sign_url(
                    "GET",
                    object_key,
                    self.settings.oss_signed_url_ttl_seconds,
                    slash_safe=True,
                )
            )
        except ImageQualityServiceError:
            raise
        except Exception as error:  # noqa: BLE001 - normalize SDK errors
            raise ImageQualityServiceError("图片上传 OSS 失败") from error


class ExternalImageQualityClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def inspect(self, image_url: str) -> ExternalImageQuality:
        if not self.settings.image_quality_api_token:
            raise ImageQualityServiceError(
                "未配置 IMAGE_QUALITY_API_TOKEN，无法进行图片质量检查"
            )
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(
                    self.settings.image_quality_api_url,
                    headers={"token": self.settings.image_quality_api_token},
                    json={"url": image_url},
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise ImageQualityServiceError("图片质量检查服务调用失败") from error

        status = body.get("status", body.get("Status"))
        data = body.get("data")
        if status != 1 or not isinstance(data, dict):
            raise ImageQualityServiceError("图片质量检查服务返回失败")
        description = str(data.get("desc", "")).strip()
        if not description:
            raise ImageQualityServiceError("图片质量检查服务未返回模糊描述")
        review_descriptions = {
            item.casefold() for item in self.settings.image_quality_review_descriptions
        }
        return ExternalImageQuality(
            acceptable=description.casefold() not in review_descriptions,
            description=description,
            blur=_as_float(data.get("blur")),
            brightness=(brightness := _as_float(data.get("brightness"))),
            brightness_description=_describe_brightness(brightness),
            angle=_as_float(data.get("angle")),
        )


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _describe_brightness(value: float | None) -> str | None:
    """Map the API value to its documented 25/55 display bands."""
    if value is None:
        return None
    score = value * 100 if 0 <= value <= 1 else value
    if score < 25:
        return "偏低"
    if score > 55:
        return "偏高"
    return "适中"

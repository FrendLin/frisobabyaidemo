from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.image_quality import ExternalImageQualityClient, OssImagePublisher


@pytest.mark.asyncio
async def test_external_quality_client_parses_review_level() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["token"] == "test-token"
        assert json.loads(request.content) == {"url": "https://example.com/image.jpg"}
        return httpx.Response(
            200,
            json={
                "status": 1,
                "data": {
                    "blur": "99.26",
                    "desc": "中",
                    "brightness": 0.22,
                    "angle": 0.31,
                },
            },
        )

    client = ExternalImageQualityClient(
        Settings(image_quality_api_token="test-token"),
        transport=httpx.MockTransport(handler),
    )

    result = await client.inspect("https://example.com/image.jpg")

    assert result.acceptable is False
    assert result.description == "中"
    assert result.blur == pytest.approx(99.26)
    assert result.brightness == pytest.approx(0.22)
    assert result.brightness_description == "偏低"


@pytest.mark.asyncio
async def test_oss_publisher_uses_project_scoped_private_key(tmp_path: Path) -> None:
    config = tmp_path / "oss.json"
    config.write_text(
        json.dumps(
            {
                "default_profile": "default",
                "profiles": {
                    "default": {
                        "endpoint": "oss-cn-beijing.aliyuncs.com",
                        "bucket": "example",
                        "access_key_id": "test-id",
                        "access_key_secret": "test-secret",
                        "root_prefix": "projects",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class Result:
        status = 200

    class FakeBucket:
        object_key = ""
        headers: dict[str, str] = {}

        def put_object(self, key, payload, headers):
            assert payload == b"image"
            self.object_key = key
            self.headers = headers
            return Result()

        def sign_url(self, method, key, expires, slash_safe):
            assert method == "GET"
            assert key == self.object_key
            assert expires == 900
            assert slash_safe is True
            return f"https://signed.example/{key}"

    bucket = FakeBucket()
    publisher = OssImagePublisher(
        Settings(oss_shared_config=str(config)),
        bucket_factory=lambda profile: bucket,
    )

    url = await publisher.publish(b"image", "image/png")

    assert bucket.object_key.startswith(
        "projects/frisobabyaidemo/image-quality-check/"
    )
    assert bucket.object_key.endswith(".png")
    assert bucket.headers["x-oss-object-acl"] == "private"
    assert url.startswith("https://signed.example/projects/frisobabyaidemo/")

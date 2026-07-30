from __future__ import annotations

import asyncio
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app import labeling
from app.batch import BatchValidationError, build_template, process_workbook
from app.config import Settings
from app.domain import Brand, MaterialType
from app.image_quality import (
    ExternalImageQualityClient,
    ImagePublisher,
    ImageQualityChecker,
    ImageQualityServiceError,
    OssImagePublisher,
)
from app.labeling import LabelingError, LabelStore
from app.manifest_sync import sync_labels_to_manifest
from app.models import ReviewDecision
from app.providers.base import ProviderError, UnavailableProvider, VisionProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.quality import InvalidImageError
from app.reviewer import MaterialReviewer
from app.training import load_training_examples


BASE_DIR = Path(__file__).resolve().parent


def _provider_from_settings(settings: Settings) -> VisionProvider:
    if settings.vision_provider != "openai_compatible":
        return UnavailableProvider(
            f"不支持的 VISION_PROVIDER：{settings.vision_provider}"
        )
    if not settings.vision_api_key or not settings.vision_model:
        return UnavailableProvider(
            "未配置 VISION_API_KEY 或 VISION_MODEL，系统不会在无模型时默认通过"
        )
    training_examples = ()
    if settings.vision_reference_manifest:
        manifest = Path(settings.vision_reference_manifest)
        if not manifest.is_file():
            return UnavailableProvider(f"训练清单不存在：{manifest}")
        training_examples = load_training_examples(
            manifest,
            max_per_label=settings.vision_examples_per_label,
        )
    return OpenAICompatibleProvider(settings, training_examples)


def create_app(
    settings: Settings | None = None,
    provider: VisionProvider | None = None,
    quality_checker: ImageQualityChecker | None = None,
    image_publisher: ImagePublisher | None = None,
) -> FastAPI:
    effective_settings = settings or Settings.from_env()
    effective_provider = provider or _provider_from_settings(effective_settings)
    reviewer = MaterialReviewer(
        effective_provider,
        effective_settings,
        quality_checker=quality_checker
        or ExternalImageQualityClient(effective_settings),
        image_publisher=image_publisher or OssImagePublisher(effective_settings),
    )

    application = FastAPI(
        title="美素佳儿大型物料 AI 审核 POC",
        version="0.1.0",
        description="品牌与物料类型双重识别，支持单图审核和 Excel 批处理。",
    )
    application.state.settings = effective_settings
    application.state.provider = effective_provider
    application.state.reviewer = reviewer
    label_store = LabelStore(Path(effective_settings.labeling_data_dir))
    application.state.label_store = label_store
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(BASE_DIR / "templates" / "index.html")

    @application.get("/labeler", include_in_schema=False)
    async def labeler_page() -> FileResponse:
        return FileResponse(
            BASE_DIR / "templates" / "labeler.html",
            headers={"Cache-Control": "no-store"},
        )

    @application.get("/api/health")
    async def health() -> dict[str, object]:
        available = effective_provider.name != "unavailable"
        return {
            "status": "ok" if available else "degraded",
            "provider": effective_provider.name,
            "model_configured": available,
        }

    @application.post("/api/review", response_model=ReviewDecision)
    async def review_single(
        brand: str = Form(""),
        material_type: str = Form(""),
        image: UploadFile = File(...),
        quality_check: bool = Form(False),
    ) -> ReviewDecision:
        expected_brand: Brand | None = None
        expected_material_type: MaterialType | None = None
        try:
            if brand.strip():
                expected_brand = Brand(brand.strip())
            if material_type.strip():
                expected_material_type = MaterialType(material_type.strip())
        except ValueError as error:
            raise HTTPException(status_code=422, detail=f"品牌或物料类型不合法：{error}") from error

        payload = await image.read(effective_settings.max_image_bytes + 1)
        if len(payload) > effective_settings.max_image_bytes:
            raise HTTPException(status_code=413, detail="图片超过大小限制")
        if not payload:
            raise HTTPException(status_code=422, detail="图片为空")
        mime_type = image.content_type or "application/octet-stream"
        if not mime_type.startswith("image/"):
            raise HTTPException(status_code=422, detail="仅支持图片文件")

        try:
            return await reviewer.review(
                expected_brand=expected_brand,
                expected_material_type=expected_material_type,
                image_bytes=payload,
                mime_type=mime_type,
                check_image_quality=quality_check,
            )
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ProviderError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ImageQualityServiceError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @application.get("/api/batch/template")
    async def download_template() -> Response:
        return Response(
            build_template(),
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": 'attachment; filename="material_review_template.xlsx"'
            },
        )

    @application.post("/api/batch")
    async def review_batch(
        workbook: UploadFile = File(...),
        quality_check: bool = Form(False),
    ) -> Response:
        if not workbook.filename or not workbook.filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=422, detail="仅支持 .xlsx 文件")
        payload = await workbook.read()
        try:
            output = await process_workbook(
                payload,
                reviewer,
                effective_settings,
                check_image_quality=quality_check,
            )
        except BatchValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(
            output,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            headers={
                "Content-Disposition": 'attachment; filename="material_review_results.xlsx"'
            },
        )

    # --- 图片标注筛选器 ---

    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @application.get("/api/labeler/config")
    async def labeler_config() -> dict[str, object]:
        return {
            "brand_catalog": labeling.BRAND_CATALOG,
            "material_types": list(labeling.MATERIAL_TYPES),
        }

    @application.post("/api/labeler/pick-directory")
    async def labeler_pick_directory() -> dict[str, object]:
        try:
            selected = await asyncio.to_thread(labeling.pick_directory_native)
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if selected is None:
            return {"cancelled": True, "directory": None}
        return {"cancelled": False, "directory": str(selected)}

    @application.get("/api/labeler/scan")
    async def labeler_scan(directory: str = Query(...)) -> dict[str, object]:
        try:
            resolved = labeling.resolve_directory(directory)
            items = labeling.scan_directory(resolved)
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        records = label_store.load(resolved)
        merged = labeling.merge_items_with_labels(items, records)
        return {
            "directory": str(resolved),
            "images": merged,
            "progress": labeling.progress(merged),
            "duplicate_names": labeling.find_duplicate_names(items),
        }

    @application.get("/api/labeler/image")
    async def labeler_image(
        directory: str = Query(...), relpath: str = Query(...)
    ) -> FileResponse:
        try:
            base = labeling.resolve_directory(directory)
            target = labeling.resolve_image_within(base, relpath)
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        media_type, _ = mimetypes.guess_type(target.name)
        return FileResponse(target, media_type=media_type or "application/octet-stream")

    @application.post("/api/labeler/label")
    async def labeler_label(payload: dict = Body(...)) -> dict[str, object]:
        directory = payload.get("directory")
        relpath = payload.get("relpath")
        if not directory or not relpath:
            raise HTTPException(status_code=422, detail="缺少 directory 或 relpath")
        try:
            base = labeling.resolve_directory(directory)
            # 校验图片确实位于目录内且存在，防止对无效条目落库。
            labeling.resolve_image_within(base, relpath)
            record = label_store.set_label(
                base,
                relpath,
                brands=payload.get("brands"),
                material_types=payload.get("material_types"),
                brand=payload.get("brand"),
                material_type=payload.get("material_type"),
                manifest_url=payload.get("manifest_url"),
                now=_now(),
            )
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"saved": True, "record": record.to_dict()}

    @application.get("/api/labeler/export")
    async def labeler_export(
        directory: str = Query(...),
        fmt: str = Query("csv"),
        mode: str = Query("all"),
        brand: str | None = Query(None),
        material_type: str | None = Query(None),
    ) -> Response:
        try:
            resolved = labeling.resolve_directory(directory)
            items = labeling.scan_directory(resolved)
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        records = label_store.load(resolved)
        merged = labeling.merge_items_with_labels(items, records)
        filtered = labeling.filter_records(
            merged, mode=mode, brand=brand, material_type=material_type
        )
        if fmt == "json":
            body = labeling.export_json(resolved, filtered)
            return Response(
                body,
                media_type="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="labels.json"'
                },
            )
        body = labeling.export_csv(filtered)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="labels.csv"'},
        )

    @application.post("/api/labeler/sync-manifest")
    async def labeler_sync_manifest(payload: dict = Body(...)) -> dict[str, object]:
        directory = payload.get("directory")
        if not directory:
            raise HTTPException(status_code=422, detail="缺少 directory")
        append_missing = bool(payload.get("append_missing", False))
        try:
            resolved = labeling.resolve_directory(directory)
        except LabelingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        records = list(label_store.load(resolved).values())
        result = sync_labels_to_manifest(
            Path(effective_settings.labeling_manifest),
            records,
            append_missing=append_missing,
        )
        return {"synced": True, "result": result.as_dict()}

    return application


app = create_app()

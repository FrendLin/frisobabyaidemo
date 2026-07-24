from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.batch import BatchValidationError, build_template, process_workbook
from app.config import Settings
from app.domain import Brand, MaterialType
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
) -> FastAPI:
    effective_settings = settings or Settings.from_env()
    effective_provider = provider or _provider_from_settings(effective_settings)
    reviewer = MaterialReviewer(effective_provider, effective_settings)

    application = FastAPI(
        title="美素佳儿大型物料 AI 审核 POC",
        version="0.1.0",
        description="品牌与物料类型双重识别，支持单图审核和 Excel 批处理。",
    )
    application.state.settings = effective_settings
    application.state.provider = effective_provider
    application.state.reviewer = reviewer
    application.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(BASE_DIR / "templates" / "index.html")

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
        brand: str = Form(...),
        material_type: str = Form(...),
        image: UploadFile = File(...),
    ) -> ReviewDecision:
        try:
            expected_brand = Brand(brand)
            expected_material_type = MaterialType(material_type)
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
            )
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ProviderError as error:
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
    async def review_batch(workbook: UploadFile = File(...)) -> Response:
        if not workbook.filename or not workbook.filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=422, detail="仅支持 .xlsx 文件")
        payload = await workbook.read()
        try:
            output = await process_workbook(payload, reviewer, effective_settings)
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

    return application


app = create_app()

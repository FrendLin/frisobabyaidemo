from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.models import ImageQuality


class InvalidImageError(ValueError):
    pass


def inspect_quality(payload: bytes) -> ImageQuality:
    try:
        with Image.open(BytesIO(payload)) as source:
            source.verify()
        with Image.open(BytesIO(payload)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise InvalidImageError("文件不是可识别的图片") from error

    width, height = image.size
    grayscale = image.convert("L")
    grayscale.thumbnail((768, 768))
    stats = ImageStat.Stat(grayscale)
    brightness = float(stats.mean[0])
    contrast = float(stats.stddev[0])
    edge_stats = ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES))
    sharpness = float(edge_stats.var[0])

    warnings: list[str] = []
    if min(width, height) < 640:
        warnings.append("图片短边低于 640px，细节可能不足")
    if brightness < 45:
        warnings.append("图片偏暗")
    elif brightness > 225:
        warnings.append("图片可能过曝")
    if contrast < 22:
        warnings.append("图片对比度偏低")
    if sharpness < 90:
        warnings.append("图片可能模糊")

    return ImageQuality(
        width=width,
        height=height,
        brightness=round(brightness, 2),
        contrast=round(contrast, 2),
        sharpness=round(sharpness, 2),
        warnings=warnings,
    )


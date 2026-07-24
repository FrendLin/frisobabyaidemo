#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from app.config import Settings
from app.domain import Brand, MaterialType
from app.providers.openai_compatible import OpenAICompatibleProvider


async def evaluate(manifest: Path, output: Path, target_accuracy: float) -> int:
    settings = Settings.from_env()
    if not settings.vision_api_key or not settings.vision_model:
        raise RuntimeError("请先配置 VISION_API_KEY 和 VISION_MODEL")
    provider = OpenAICompatibleProvider(settings)

    with manifest.open(encoding="utf-8-sig") as handle:
        samples = [row for row in csv.DictReader(handle) if row["split"] == "test"]

    semaphore = asyncio.Semaphore(settings.batch_concurrency)
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    predictions = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

        async def predict(sample: dict[str, str]) -> dict[str, object]:
            async with semaphore:
                response = await client.get(sample["image_url"])
                response.raise_for_status()
                content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
                detected = await provider.analyze(response.content, content_type)
            actual_brand = Brand(sample["brand"])
            actual_type = MaterialType(sample["material_type"])
            return {
                "sample_id": sample["sample_id"],
                "actual_brand": actual_brand.value,
                "actual_material_type": actual_type.value,
                "predicted_brand": detected.brand.value if detected.brand else None,
                "predicted_material_type": (
                    detected.material_type.value if detected.material_type else None
                ),
                "confidence": detected.confidence,
                "brand_correct": detected.brand == actual_brand,
                "type_correct": detected.material_type == actual_type,
                "exact_correct": (
                    detected.brand == actual_brand
                    and detected.material_type == actual_type
                ),
            }

        predictions = await asyncio.gather(*(predict(sample) for sample in samples))

    total = len(predictions)
    by_label: dict[str, Counter] = defaultdict(Counter)
    for item in predictions:
        label = f'{item["actual_brand"]}/{item["actual_material_type"]}'
        by_label[label]["total"] += 1
        by_label[label]["correct"] += int(bool(item["exact_correct"]))

    report = {
        "manifest": str(manifest),
        "provider": provider.name,
        "model": settings.vision_model,
        "test_count": total,
        "target_accuracy": target_accuracy,
        "exact_accuracy": sum(bool(item["exact_correct"]) for item in predictions) / total,
        "brand_accuracy": sum(bool(item["brand_correct"]) for item in predictions) / total,
        "type_accuracy": sum(bool(item["type_correct"]) for item in predictions) / total,
        "by_label": {
            label: {
                "correct": counts["correct"],
                "total": counts["total"],
                "accuracy": counts["correct"] / counts["total"],
            }
            for label, counts in sorted(by_label.items())
        },
        "predictions": predictions,
        "limitations": [
            "原始数据均为正样本，不能据此计算真实审核场景的通过/驳回准确率。",
            "店内海报（非货架）在原始数据中为 0 张。",
            "源悦/吊旗与尊悦/包柱画面仅 1 张，只进入训练集，测试集无法覆盖。",
        ],
    }
    report["gate_passed"] = report["exact_accuracy"] >= target_accuracy
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "test_count", "exact_accuracy", "brand_accuracy", "type_accuracy", "gate_passed"
    )}, ensure_ascii=False, indent=2))
    return 0 if report["gate_passed"] else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="在固定 20% 测试集上执行 90% 门禁")
    parser.add_argument(
        "--manifest", type=Path, default=Path("data/dataset_manifest.csv")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation_report.json")
    )
    parser.add_argument("--target-accuracy", type=float, default=0.90)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(evaluate(args.manifest, args.output, args.target_accuracy)))


if __name__ == "__main__":
    main()


from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from app.domain import Brand, MaterialType


@dataclass(frozen=True, slots=True)
class TrainingExample:
    sample_id: str
    brand: Brand
    material_type: MaterialType
    image_url: str


def load_training_examples(
    manifest: Path,
    *,
    max_per_label: int = 1,
) -> list[TrainingExample]:
    if max_per_label < 1:
        return []
    examples: list[TrainingExample] = []
    counts: dict[tuple[Brand, MaterialType], int] = {}
    with manifest.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["split"] != "train":
                continue
            brand = Brand(row["brand"])
            material_type = MaterialType(row["material_type"])
            label = (brand, material_type)
            if counts.get(label, 0) >= max_per_label:
                continue
            examples.append(
                TrainingExample(
                    sample_id=row["sample_id"],
                    brand=brand,
                    material_type=material_type,
                    image_url=row["image_url"],
                )
            )
            counts[label] = counts.get(label, 0) + 1
    return examples

from __future__ import annotations

from pathlib import Path

from app.training import load_training_examples


def test_training_examples_never_include_test_rows(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "sample_id,brand,material_type,image_url,split\n"
        "train-1,皇家,灯箱,https://example.test/train.jpg,train\n"
        "test-1,皇家,灯箱,https://example.test/test.jpg,test\n",
        encoding="utf-8",
    )

    examples = load_training_examples(manifest)

    assert [example.sample_id for example in examples] == ["train-1"]

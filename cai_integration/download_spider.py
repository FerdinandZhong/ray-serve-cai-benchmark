#!/usr/bin/env python3
"""
Download and prepare the Spider text-to-SQL dataset.

Downloads:
1. Spider validation split from HuggingFace (xlangai/spider)
2. SQLite databases from https://github.com/taoyds/spider

Cached at /home/cdsw/datasets/spider/ to avoid re-downloading on subsequent runs.

Usage:
    python cai_integration/download_spider.py
"""

import json
import os
import subprocess
import zipfile
from pathlib import Path

SPIDER_DATA_DIR = Path(os.environ.get("SPIDER_DATA_DIR", "/home/cdsw/datasets/spider"))
SPIDER_DB_URL = "https://github.com/taoyds/spider/archive/refs/heads/master.zip"


def download_databases(data_dir: Path) -> Path:
    """Download Spider SQLite databases from GitHub.

    Returns path to the database/ directory containing all 140+ databases.
    """
    db_dir = data_dir / "databases"
    if db_dir.exists() and any(db_dir.iterdir()):
        print(f"Spider databases already cached at {db_dir}")
        return db_dir

    zip_path = data_dir / "spider-master.zip"
    data_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading Spider databases from GitHub...")
    subprocess.run(
        ["curl", "-L", "-o", str(zip_path), SPIDER_DB_URL],
        check=True,
    )

    print("Extracting databases...")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.startswith("spider-master/database/"):
                target = data_dir / member.replace("spider-master/", "", 1)
                if member.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())

    zip_path.unlink()
    print(f"Databases extracted to {db_dir}")
    return db_dir


def download_validation_split(data_dir: Path) -> Path:
    """Download Spider validation split from HuggingFace.

    Returns path to the validation JSON file.
    """
    val_file = data_dir / "validation.json"
    if val_file.exists():
        print(f"Validation split already cached at {val_file}")
        return val_file

    data_dir.mkdir(parents=True, exist_ok=True)

    print("Downloading Spider validation split from HuggingFace...")
    from datasets import load_dataset

    ds = load_dataset("xlangai/spider", split="validation")

    records = []
    for item in ds:
        records.append({
            "question": item["question"],
            "query": item["query"],
            "db_id": item["db_id"],
        })

    with open(val_file, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Saved {len(records)} validation examples to {val_file}")
    return val_file


def prepare_spider(data_dir: Path = None) -> tuple:
    """Download and prepare both datasets and databases.

    Returns:
        (validation_file, databases_dir)
    """
    if data_dir is None:
        data_dir = SPIDER_DATA_DIR

    val_file = download_validation_split(data_dir)
    db_dir = download_databases(data_dir)
    return val_file, db_dir


if __name__ == "__main__":
    prepare_spider()

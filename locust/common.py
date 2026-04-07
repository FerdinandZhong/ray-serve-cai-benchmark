"""Shared utilities for Locust load tests."""

import itertools
import json
import os
import random
from pathlib import Path

from dotenv import load_dotenv

# Load cluster config
_env_path = Path(__file__).resolve().parent.parent / "configs" / "cluster.env"
load_dotenv(_env_path)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
VLLM_ROUTE = os.environ.get("VLLM_ROUTE", "/qwen-2b")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "/home/cdsw/models/Qwen3.5-2B")
YOLO_ROUTE = os.environ.get("YOLO_ROUTE", "/yolo")
MCP_ROUTE = os.environ.get("MCP_ROUTE", "/weather-mcp")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() not in ("false", "0", "no")

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"
DATASET_DIR = os.environ.get("DATASET_DIR", "")


def load_prompts(filename: str = "prompts_short.jsonl") -> list[dict]:
    """Load prompts from a JSONL file. Each line: {"prompt": "...", "max_tokens": N}."""
    path = DATASETS_DIR / filename
    if not path.exists():
        return [{"prompt": "What is machine learning?", "max_tokens": 128}]
    prompts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                prompts.append(json.loads(line))
    return prompts


def prompt_cycle(filename: str = "prompts_short.jsonl"):
    """Return an infinite iterator that cycles through prompts."""
    prompts = load_prompts(filename)
    return itertools.cycle(prompts)


def random_prompt(prompts: list[dict]) -> dict:
    """Pick a random prompt from a loaded list."""
    return random.choice(prompts)


def load_image_paths() -> list[Path]:
    """Load all image file paths from DATASET_DIR or datasets/sample_images/.

    If the DATASET_DIR environment variable is set, images are loaded from that
    directory (recursively). Otherwise falls back to datasets/sample_images/.
    """
    if DATASET_DIR:
        img_dir = Path(DATASET_DIR)
    else:
        img_dir = DATASETS_DIR / "sample_images"
    if not img_dir.exists():
        return []
    return sorted(img_dir.rglob("*.png")) + sorted(img_dir.rglob("*.jpg")) + sorted(img_dir.rglob("*.jpeg"))


def random_image_bytes(image_paths: list[Path]) -> bytes:
    """Read a random image file as bytes."""
    if not image_paths:
        # Generate a tiny 1x1 red PNG as fallback
        from PIL import Image
        import io
        img = Image.new("RGB", (64, 64), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    return random.choice(image_paths).read_bytes()


def chat_payload(prompt: str, max_tokens: int = 128, stream: bool = False) -> dict:
    """Build an OpenAI-compatible chat completion request body."""
    return {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": stream,
    }

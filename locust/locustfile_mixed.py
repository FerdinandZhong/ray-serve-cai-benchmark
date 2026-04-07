"""
Mixed workload Locust test — simulates realistic cluster usage.

Combines chat completions, YOLO detection, health probes, and metrics scraping.

Usage:
    locust -f locust/locustfile_mixed.py --headless -u 50 -r 5 -t 120s
"""

from locust import HttpUser, between, task

from common import (
    BASE_URL,
    VERIFY_SSL,
    VLLM_ROUTE,
    YOLO_ROUTE,
    chat_payload,
    load_image_paths,
    load_prompts,
    random_image_bytes,
    random_prompt,
)


class MixedWorkloadUser(HttpUser):
    host = BASE_URL
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.prompts = load_prompts("prompts_short.jsonl")
        self.image_paths = load_image_paths()
        if not VERIFY_SSL:
            self.client.verify = False

    # ── 50% chat completions ─────────────────────────────────────────────

    @task(5)
    def chat_completion(self):
        p = random_prompt(self.prompts)
        payload = chat_payload(p["prompt"], p.get("max_tokens", 128), stream=False)
        with self.client.post(
            f"{VLLM_ROUTE}/v1/chat/completions",
            json=payload,
            name="[mix] chat",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    # ── 30% YOLO detection ───────────────────────────────────────────────

    @task(3)
    def yolo_detect(self):
        img_bytes = random_image_bytes(self.image_paths)
        with self.client.post(
            f"{YOLO_ROUTE}/v1/detect",
            files={"file": ("test.png", img_bytes, "image/png")},
            name="[mix] yolo",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    # ── 15% health checks ────────────────────────────────────────────────

    @task(1)
    def health_vllm(self):
        self.client.get(f"{VLLM_ROUTE}/health", name="[mix] health/vllm")

    @task(0.5)
    def health_yolo(self):
        self.client.get(f"{YOLO_ROUTE}/health", name="[mix] health/yolo")

    # ── 5% metrics scrape ────────────────────────────────────────────────

    @task(0.5)
    def metrics_apps(self):
        self.client.get("/api/v1/metrics/apps", name="[mix] metrics/apps")

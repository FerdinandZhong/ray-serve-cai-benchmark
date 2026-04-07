"""
Locust load test for YOLO object detection.

Usage:
    locust -f locust/locustfile_yolo.py --headless -u 20 -r 5 -t 60s
    locust -f locust/locustfile_yolo.py   # web UI

Set BASE_URL and YOLO_ROUTE in configs/cluster.env before running.
"""

from locust import HttpUser, between, task

from common import BASE_URL, VERIFY_SSL, YOLO_ROUTE, load_image_paths, random_image_bytes


class YOLODetectionUser(HttpUser):
    host = BASE_URL
    wait_time = between(0.2, 1.0)

    def on_start(self):
        self.image_paths = load_image_paths()
        if not VERIFY_SSL:
            self.client.verify = False

    @task(8)
    def detect(self):
        """POST /v1/detect with a random image file."""
        img_bytes = random_image_bytes(self.image_paths)
        with self.client.post(
            f"{YOLO_ROUTE}/v1/detect",
            files={"file": ("test.png", img_bytes, "image/png")},
            name="yolo detect",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                # Optionally validate response shape
                if "items" in data and "total_count" in data:
                    resp.success()
                else:
                    resp.failure(f"Unexpected response: {list(data.keys())}")
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")

    @task(1)
    def health(self):
        """GET /health — lightweight liveness probe."""
        with self.client.get(
            f"{YOLO_ROUTE}/health",
            name="yolo health",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @task(1)
    def info(self):
        """GET /info — model metadata."""
        self.client.get(f"{YOLO_ROUTE}/info", name="yolo info")

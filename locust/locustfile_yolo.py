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

    @task
    def detect(self):
        """POST /v1/detect with a random image file."""
        img_bytes = random_image_bytes(self.image_paths)
        with self.client.post(
            f"{YOLO_ROUTE}",
            files={"file": ("test.png", img_bytes, "image/png")},
            name="yolo detect",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")

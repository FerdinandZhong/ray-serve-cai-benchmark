"""
Locust load test for vLLM chat completions.

Usage:
    locust -f locust/locustfile_chat.py --headless -u 10 -r 2 -t 60s
    locust -f locust/locustfile_chat.py   # web UI at http://localhost:8089

Set BASE_URL and VLLM_ROUTE in configs/cluster.env before running.
"""

import time

from locust import HttpUser, between, task

from common import (
    BASE_URL,
    VERIFY_SSL,
    VLLM_ROUTE,
    chat_payload,
    load_prompts,
    random_prompt,
)


class ChatCompletionUser(HttpUser):
    host = BASE_URL
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.short_prompts = load_prompts("prompts_short.jsonl")
        self.long_prompts = load_prompts("prompts_long.jsonl")
        # Disable SSL verification if configured
        if not VERIFY_SSL:
            self.client.verify = False

    @task(6)
    def chat_non_streaming(self):
        """Non-streaming chat completion — measure total latency."""
        p = random_prompt(self.short_prompts)
        payload = chat_payload(p["prompt"], p.get("max_tokens", 128), stream=False)
        with self.client.post(
            f"{VLLM_ROUTE}/v1/chat/completions",
            json=payload,
            name="chat (non-stream)",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")

    @task(3)
    def chat_streaming(self):
        """Streaming chat completion — measure TTFT and total time."""
        p = random_prompt(self.short_prompts)
        payload = chat_payload(p["prompt"], p.get("max_tokens", 128), stream=True)
        start = time.perf_counter()
        ttft = None

        with self.client.post(
            f"{VLLM_ROUTE}/v1/chat/completions",
            json=payload,
            name="chat (stream)",
            stream=True,
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            for line in resp.iter_lines():
                if ttft is None and line:
                    ttft = (time.perf_counter() - start) * 1000  # ms
            resp.success()

        total = (time.perf_counter() - start) * 1000
        if ttft is not None:
            self.environment.events.request.fire(
                request_type="TTFT",
                name="chat (stream) TTFT",
                response_time=ttft,
                response_length=0,
                exception=None,
                context={},
            )

    @task(1)
    def chat_long_prompt(self):
        """Long prompt (2K-8K tokens) — stress KV cache."""
        p = random_prompt(self.long_prompts)
        payload = chat_payload(p["prompt"], p.get("max_tokens", 256), stream=False)
        with self.client.post(
            f"{VLLM_ROUTE}/v1/chat/completions",
            json=payload,
            name="chat (long prompt)",
            catch_response=True,
            timeout=120,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}: {resp.text[:200]}")

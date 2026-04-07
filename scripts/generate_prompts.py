#!/usr/bin/env python3
"""
Generate JSONL prompt datasets for benchmarking.

Creates:
  datasets/prompts_short.jsonl      — 50 prompts, 50-100 tokens each
  datasets/prompts_long.jsonl       — 20 prompts, 2K-8K tokens each
  datasets/prompts_multi_turn.jsonl — 15 multi-turn conversations

Usage:
    python scripts/generate_prompts.py
"""

import json
import random
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

SHORT_TOPICS = [
    "What is machine learning?",
    "Explain the difference between TCP and UDP.",
    "Write a Python function that reverses a string.",
    "What causes ocean tides?",
    "Describe the architecture of a transformer model.",
    "How does garbage collection work in Java?",
    "What is the CAP theorem in distributed systems?",
    "Explain how RSA encryption works.",
    "What are the main differences between SQL and NoSQL databases?",
    "Describe the process of photosynthesis.",
    "How does a compiler differ from an interpreter?",
    "What is Kubernetes and why is it useful?",
    "Explain the concept of recursion with an example.",
    "What are microservices and how do they compare to monoliths?",
    "How does HTTP/2 improve on HTTP/1.1?",
    "What is a neural network activation function?",
    "Explain the concept of eventual consistency.",
    "What are the SOLID principles in software engineering?",
    "How does DNS resolution work?",
    "What is the difference between a process and a thread?",
    "Explain how a hash table works internally.",
    "What is gradient descent and why is it important?",
    "Describe the OSI model layers.",
    "How does TLS/SSL secure a connection?",
    "What is Docker and how does it differ from virtual machines?",
    "Explain MapReduce in simple terms.",
    "What is a REST API?",
    "How does Git branching work?",
    "What is the difference between supervised and unsupervised learning?",
    "Explain the concept of database normalization.",
    "What is Ray Serve and how does it handle scaling?",
    "Describe the benefits of using FastAPI over Flask.",
    "How does a load balancer distribute traffic?",
    "What is the difference between latency and throughput?",
    "Explain what a placement group is in Ray.",
    "How does vLLM achieve high throughput for LLM inference?",
    "What is continuous batching in LLM serving?",
    "Explain the KV cache and why it matters for transformers.",
    "What is tensor parallelism?",
    "How does prefix caching improve LLM serving performance?",
    "What is the difference between greedy and beam search decoding?",
    "Explain attention mechanisms in transformers.",
    "What is quantization in the context of neural networks?",
    "How does RLHF work for aligning language models?",
    "What is the difference between BF16 and FP16?",
    "Explain the concept of speculative decoding.",
    "What is a LoRA adapter?",
    "How does flash attention reduce memory usage?",
    "What are embedding models used for?",
    "Explain the difference between encoder and decoder transformers.",
]

LONG_PREFIXES = [
    "Write a comprehensive technical guide on",
    "Provide a detailed analysis of the pros and cons of",
    "Create a step-by-step tutorial with code examples for",
    "Write an in-depth comparison between",
    "Explain in great detail, with examples and edge cases,",
]

LONG_TOPICS = [
    "implementing a distributed key-value store from scratch in Python, covering consistency models, replication strategies, failure handling, and performance optimization techniques",
    "building a production-ready REST API with FastAPI including authentication, rate limiting, database integration, caching, error handling, logging, and deployment considerations",
    "the evolution of transformer architectures from the original Attention Is All You Need paper through GPT, BERT, T5, and modern large language models, discussing architectural choices and their implications",
    "setting up a complete CI/CD pipeline for a microservices architecture using Docker, Kubernetes, GitHub Actions, including testing strategies, rollback mechanisms, and monitoring",
    "implementing a custom neural network framework from scratch in Python using only NumPy, covering forward propagation, backpropagation, various optimizers, and common layer types",
]

MULTI_TURN = [
    [
        {"role": "user", "content": "I want to build a web scraper in Python. Where should I start?"},
        {"role": "assistant", "content": "Start with the `requests` library for fetching pages and `BeautifulSoup` for parsing HTML. For dynamic sites, use `playwright` or `selenium`."},
        {"role": "user", "content": "How do I handle rate limiting and being polite to servers?"},
    ],
    [
        {"role": "user", "content": "What's the best way to structure a FastAPI project?"},
        {"role": "assistant", "content": "Use a modular structure with routers, services, and models in separate directories. Keep business logic out of route handlers."},
        {"role": "user", "content": "Can you show me an example directory layout with explanations?"},
    ],
    [
        {"role": "user", "content": "Explain how Ray Serve works for model serving."},
        {"role": "assistant", "content": "Ray Serve is a scalable model serving library built on Ray. It supports batching, autoscaling, and composition of multiple models."},
        {"role": "user", "content": "How does it compare to TensorFlow Serving and Triton Inference Server?"},
    ],
]


def generate_short():
    prompts = []
    for topic in SHORT_TOPICS:
        prompts.append({
            "prompt": topic,
            "max_tokens": random.randint(64, 192),
        })
    return prompts


def generate_long():
    prompts = []
    for _ in range(20):
        prefix = random.choice(LONG_PREFIXES)
        topic = random.choice(LONG_TOPICS)
        prompt = f"{prefix} {topic}. Be thorough and include code examples where relevant."
        # Pad with context to push prompt tokens toward 2K-4K range
        padding = " ".join([
            f"Consider aspect {i}: how this relates to scalability, maintainability, and real-world production use cases."
            for i in range(1, random.randint(8, 20))
        ])
        prompts.append({
            "prompt": f"{prompt}\n\nAdditional context to consider:\n{padding}",
            "max_tokens": random.randint(256, 512),
        })
    return prompts


def generate_multi_turn():
    prompts = []
    for conversation in MULTI_TURN:
        # Repeat with slight variations
        for _ in range(5):
            prompts.append({
                "messages": conversation,
                "max_tokens": random.randint(128, 384),
            })
    return prompts


def main():
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    # Short prompts
    short = generate_short()
    with open(DATASETS_DIR / "prompts_short.jsonl", "w") as f:
        for p in short:
            f.write(json.dumps(p) + "\n")
    print(f"Generated {len(short)} short prompts")

    # Long prompts
    long = generate_long()
    with open(DATASETS_DIR / "prompts_long.jsonl", "w") as f:
        for p in long:
            f.write(json.dumps(p) + "\n")
    print(f"Generated {len(long)} long prompts")

    # Multi-turn
    multi = generate_multi_turn()
    with open(DATASETS_DIR / "prompts_multi_turn.jsonl", "w") as f:
        for p in multi:
            f.write(json.dumps(p) + "\n")
    print(f"Generated {len(multi)} multi-turn prompts")


if __name__ == "__main__":
    main()

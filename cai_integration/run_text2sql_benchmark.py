#!/usr/bin/env python3
"""
Text-to-SQL accuracy benchmark using the Spider dataset.

Calls an OpenAI-compatible endpoint to generate SQL from natural language,
then evaluates execution accuracy by comparing result sets.

Environment Variables:
    INFERENCE_URL:   Base URL of the OpenAI-compatible API (required)
    MODEL_NAME:      Model name for the API (default: "default")
    MAX_SAMPLES:     Maximum examples to evaluate, 0 = all (default: 0)
    SPIDER_DATA_DIR: Path to cached Spider data (default: /home/cdsw/datasets/spider)
    CONCURRENCY:     Parallel API requests (default: 4)
    TIMEOUT:         Per-request timeout in seconds (default: 60)
    TEMPERATURE:     Sampling temperature (default: 0.0)
"""

import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional


# ─── Configuration ────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load configuration from environment variables."""
    inference_url = os.environ.get("INFERENCE_URL")
    if not inference_url:
        print("Error: INFERENCE_URL environment variable is required")
        sys.exit(1)

    return {
        "inference_url": inference_url.rstrip("/"),
        "model_name": os.environ.get("MODEL_NAME", "default"),
        "max_samples": int(os.environ.get("MAX_SAMPLES", "0")),
        "spider_data_dir": Path(os.environ.get("SPIDER_DATA_DIR", "/home/cdsw/datasets/spider")),
        "concurrency": int(os.environ.get("CONCURRENCY", "4")),
        "timeout": int(os.environ.get("TIMEOUT", "60")),
        "temperature": float(os.environ.get("TEMPERATURE", "0.0")),
    }


# ─── Schema Extraction ────────────────────────────────────────────────────────


def get_db_schema(db_path: Path) -> str:
    """Extract CREATE TABLE statements from a SQLite database."""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL;")
    schemas = [row[0] for row in cursor.fetchall()]
    conn.close()
    return "\n\n".join(schemas)


def find_database(db_id: str, databases_dir: Path) -> Optional[Path]:
    """Find the SQLite file for a given database ID."""
    db_path = databases_dir / db_id / f"{db_id}.sqlite"
    if db_path.exists():
        return db_path
    for d in databases_dir.iterdir():
        if d.name.lower() == db_id.lower() and d.is_dir():
            sqlite_file = d / f"{d.name}.sqlite"
            if sqlite_file.exists():
                return sqlite_file
    return None


# ─── Model API ────────────────────────────────────────────────────────────────


def call_model(question: str, schema: str, config: dict) -> tuple:
    """Call the OpenAI-compatible API to generate SQL.

    Returns:
        (generated_sql, error_message_or_None)
    """
    import openai

    client = openai.OpenAI(
        base_url=f"{config['inference_url']}/v1",
        api_key=os.environ.get("OPENAI_API_KEY", "dummy"),
    )

    system_prompt = (
        "You are a SQL expert. Given the database schema below, write a SQLite query "
        "that answers the user's question. Return ONLY the SQL query, no explanation.\n\n"
        f"Schema:\n{schema}"
    )

    try:
        response = client.chat.completions.create(
            model=config["model_name"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            temperature=config["temperature"],
            max_tokens=512,
            timeout=config["timeout"],
        )
        raw = response.choices[0].message.content.strip()
        sql = extract_sql(raw)
        return sql, None
    except Exception as e:
        return "", str(e)


def extract_sql(text: str) -> str:
    """Extract SQL from model response, handling markdown code blocks."""
    match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip().rstrip(";")


# ─── Execution Accuracy ───────────────────────────────────────────────────────


def execute_sql(db_path: Path, sql: str) -> tuple:
    """Execute SQL against a database and return the result set.

    Returns:
        (set_of_result_tuples, error_message_or_None)
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout = 5000;")
        cursor = conn.cursor()
        cursor.execute(sql)
        results = set(cursor.fetchall())
        conn.close()
        return results, None
    except Exception as e:
        return None, str(e)


def compare_results(gold_results: set, pred_results: set) -> bool:
    """Compare two result sets for execution accuracy."""
    if gold_results is None or pred_results is None:
        return False
    return gold_results == pred_results


# ─── Single Example Evaluation ────────────────────────────────────────────────


def evaluate_example(example: dict, databases_dir: Path, config: dict) -> dict:
    """Evaluate a single text-to-SQL example."""
    db_id = example["db_id"]
    question = example["question"]
    gold_sql = example["query"]

    result = {
        "question": question,
        "db_id": db_id,
        "gold_sql": gold_sql,
        "pred_sql": "",
        "correct": False,
        "error": None,
        "latency_ms": 0,
    }

    db_path = find_database(db_id, databases_dir)
    if not db_path:
        result["error"] = f"Database not found: {db_id}"
        return result

    schema = get_db_schema(db_path)

    start = time.time()
    pred_sql, api_error = call_model(question, schema, config)
    result["latency_ms"] = int((time.time() - start) * 1000)
    result["pred_sql"] = pred_sql

    if api_error:
        result["error"] = f"API error: {api_error}"
        return result

    if not pred_sql:
        result["error"] = "Empty SQL generated"
        return result

    gold_results, gold_error = execute_sql(db_path, gold_sql)
    if gold_error:
        result["error"] = f"Gold SQL execution error: {gold_error}"
        return result

    pred_results, pred_error = execute_sql(db_path, pred_sql)
    if pred_error:
        result["error"] = f"Predicted SQL execution error: {pred_error}"
        return result

    result["correct"] = compare_results(gold_results, pred_results)
    return result


# ─── Report Generation ────────────────────────────────────────────────────────


def generate_report(results: list, config: dict, results_dir: Path, elapsed_s: float):
    """Generate JSON detail file and Markdown summary."""
    json_path = results_dir / "text2sql_results.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Detailed results: {json_path}")

    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    accuracy = correct / total if total > 0 else 0

    # Error breakdown
    errors = {"api_error": 0, "execution_error": 0, "wrong_result": 0, "empty_sql": 0}
    for r in results:
        if r["correct"]:
            continue
        err = r.get("error") or ""
        if "API error" in err:
            errors["api_error"] += 1
        elif "execution error" in err:
            errors["execution_error"] += 1
        elif "Empty SQL" in err:
            errors["empty_sql"] += 1
        else:
            errors["wrong_result"] += 1

    # Latency stats
    latencies = [r["latency_ms"] for r in results if r["latency_ms"] > 0]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0
    p90 = sorted(latencies)[int(len(latencies) * 0.9)] if latencies else 0

    # By database
    by_db = {}
    for r in results:
        db = r["db_id"]
        by_db.setdefault(db, {"total": 0, "correct": 0})
        by_db[db]["total"] += 1
        if r["correct"]:
            by_db[db]["correct"] += 1

    md_lines = [
        "# Text-to-SQL Benchmark Results",
        "",
        f"**Model**: {config['model_name']}",
        f"**Endpoint**: {config['inference_url']}",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total time**: {elapsed_s:.1f}s",
        f"**Examples evaluated**: {total}",
        "",
        "## Overall Accuracy",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total examples | {total} |",
        f"| Correct | {correct} |",
        f"| **Execution Accuracy** | **{accuracy:.1%}** |",
        f"| Avg latency | {avg_latency:.0f}ms |",
        f"| P50 latency | {p50}ms |",
        f"| P90 latency | {p90}ms |",
        "",
        "## Error Breakdown",
        "",
        "| Error Type | Count |",
        "|------------|-------|",
        f"| API errors | {errors['api_error']} |",
        f"| SQL execution errors | {errors['execution_error']} |",
        f"| Empty SQL generated | {errors['empty_sql']} |",
        f"| Wrong result set | {errors['wrong_result']} |",
        "",
        "## Accuracy by Database (top 20)",
        "",
        "| Database | Total | Correct | Accuracy |",
        "|----------|-------|---------|----------|",
    ]

    sorted_dbs = sorted(by_db.items(), key=lambda x: x[1]["total"], reverse=True)[:20]
    for db_name, d in sorted_dbs:
        acc = d["correct"] / d["total"] if d["total"] > 0 else 0
        md_lines.append(f"| {db_name} | {d['total']} | {d['correct']} | {acc:.1%} |")

    md_path = results_dir / "text2sql_summary.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")
    print(f"  Summary report: {md_path}")

    print("\n" + "=" * 60)
    print(f"  EXECUTION ACCURACY: {accuracy:.1%} ({correct}/{total})")
    print(f"  Avg Latency: {avg_latency:.0f}ms | P50: {p50}ms | P90: {p90}ms")
    print("=" * 60)


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    """Run the text-to-SQL benchmark."""
    project_root = Path("/home/cdsw")
    config = load_config()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = project_root / "results" / f"text2sql_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  Text-to-SQL Accuracy Benchmark (Spider)")
    print(f"  Endpoint:    {config['inference_url']}")
    print(f"  Model:       {config['model_name']}")
    print(f"  Max samples: {config['max_samples'] or 'all'}")
    print(f"  Concurrency: {config['concurrency']}")
    print(f"  Results:     {results_dir}")
    print("=" * 60)

    # Prepare dataset
    sys.path.insert(0, str(project_root / "cai_integration"))
    from download_spider import prepare_spider

    val_file, db_dir = prepare_spider(config["spider_data_dir"])

    with open(val_file) as f:
        examples = json.load(f)

    if config["max_samples"] > 0:
        examples = examples[: config["max_samples"]]

    print(f"\n  Evaluating {len(examples)} examples...")
    print(f"  Databases: {db_dir}")
    print()

    # Run evaluation
    start_time = time.time()
    results = []
    completed = 0

    with ThreadPoolExecutor(max_workers=config["concurrency"]) as executor:
        futures = {
            executor.submit(evaluate_example, ex, db_dir, config): i
            for i, ex in enumerate(examples)
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1

            if completed % 50 == 0 or completed == len(examples):
                acc_so_far = sum(1 for r in results if r["correct"]) / len(results)
                print(
                    f"  Progress: {completed}/{len(examples)} "
                    f"(running accuracy: {acc_so_far:.1%})"
                )

    elapsed = time.time() - start_time

    # Generate reports
    print("\nGenerating reports...")
    generate_report(results, config, results_dir, elapsed)

    print(f"\nResult files:")
    for f in sorted(results_dir.iterdir()):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()

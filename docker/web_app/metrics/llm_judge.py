"""
LLM-as-judge semantic equivalence metric for SQL.

Calls an OpenAI-compatible endpoint and asks the judge model whether
the predicted SQL query is semantically equivalent to the gold SQL
(i.e., would produce identical results on any valid database).

config keys (passed via EvaluationJob.metric_config["llm_as_judge_sql"]):
    url     Base URL of the judge endpoint (required)
    token   API key / bearer token (default: "dummy")
    model   Model name to use (default: "default")

Additionally the evaluator injects:
    question   The natural language question
    schema     The dataset schema DDL (for context)
"""

import os
from typing import Optional

_JUDGE_PROMPT = """\
You are an expert SQL evaluator. Your task is to determine whether two SQL \
queries are semantically equivalent — that is, they would produce identical \
result sets on any valid database that matches the schema below.

Schema:
{schema}

Question: {question}

Gold SQL:
{gold_sql}

Predicted SQL:
{pred_sql}

Are these two SQL queries semantically equivalent? \
Answer with ONLY "yes" or "no", nothing else."""


def score(gold_sql: str, pred_sql: str, config: Optional[dict] = None) -> float:
    """Return 1.0 if the judge deems the queries semantically equivalent, else 0.0."""
    return score_detailed(gold_sql, pred_sql, config)[0]


def score_detailed(gold_sql: str, pred_sql: str, config: Optional[dict] = None) -> tuple:
    """Return (score, trace_dict) where trace_dict contains prompt, response, model."""
    cfg = config or {}
    url = cfg.get("url", "").strip()
    if not url:
        raise ValueError("llm_as_judge_sql requires 'url' in metric config")

    token    = cfg.get("token", "dummy").strip() or "dummy"
    model    = cfg.get("model", "default").strip() or "default"
    question = cfg.get("question", "")
    schema   = cfg.get("schema", "")

    prompt = _JUDGE_PROMPT.format(
        schema=schema or "(schema not provided)",
        question=question or "(question not provided)",
        gold_sql=gold_sql,
        pred_sql=pred_sql,
    )

    trace = {
        "judge_model": model,
        "judge_prompt": prompt,
        "judge_response": "",
        "judge_error": None,
    }

    try:
        import openai
        base = url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        client = openai.OpenAI(base_url=base, api_key=token)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=16,
            timeout=30,
        )
        answer = response.choices[0].message.content.strip()
        trace["judge_response"] = answer
        return (1.0 if answer.lower().startswith("yes") else 0.0), trace
    except Exception as e:
        print(f"[llm_judge] error: {e}", flush=True)
        trace["judge_error"] = str(e)
        return 0.0, trace

"""Token-level F1 score between predicted and gold SQL."""

import re


def _tokenize(sql: str) -> list:
    sql = sql.strip().rstrip(";").lower()
    return re.findall(r"[a-z0-9_]+|[^\s\w]", sql)


def score(gold_sql: str, pred_sql: str, config=None) -> float:
    gold_tokens = _tokenize(gold_sql)
    pred_tokens = _tokenize(pred_sql)

    if not gold_tokens and not pred_tokens:
        return 1.0
    if not gold_tokens or not pred_tokens:
        return 0.0

    gold_counts: dict = {}
    for t in gold_tokens:
        gold_counts[t] = gold_counts.get(t, 0) + 1

    pred_counts: dict = {}
    for t in pred_tokens:
        pred_counts[t] = pred_counts.get(t, 0) + 1

    overlap = sum(min(gold_counts.get(t, 0), pred_counts.get(t, 0)) for t in pred_counts)

    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)

    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)

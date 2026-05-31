"""
Component (clause-level) match for SQL evaluation.

Splits SQL into clauses (SELECT, FROM, WHERE, GROUP BY, ORDER BY, HAVING, LIMIT)
and computes the fraction of clauses that match token-for-token after normalization.

Inspired by the Spider partial-match evaluation methodology.
"""

import re


_CLAUSE_KEYWORDS = ["select", "from", "where", "group by", "order by", "having", "limit"]

# Regex to split on top-level clause keywords (not inside parentheses)
_SPLIT_RE = re.compile(
    r"\b(select|from|where|group\s+by|order\s+by|having|limit)\b",
    re.IGNORECASE,
)


def _normalize(sql: str) -> str:
    sql = sql.strip().rstrip(";").lower()
    sql = re.sub(r"\s+", " ", sql)
    return sql


def _extract_clauses(sql: str) -> dict:
    """Return {keyword: body_tokens} for top-level clauses only (depth=0)."""
    sql = _normalize(sql)
    clauses: dict = {}
    current_key = None
    current_body: list = []
    depth = 0

    # Walk character by character to respect parentheses
    tokens = re.split(r"(\(|\)|,|\s+)", sql)
    i = 0
    buffer = []

    while i < len(tokens):
        tok = tokens[i]
        if tok == "(":
            depth += 1
            buffer.append(tok)
        elif tok == ")":
            depth -= 1
            buffer.append(tok)
        elif depth == 0:
            # Check if this token starts a new clause
            remaining = " ".join([tok] + tokens[i + 1: i + 3]).strip()
            matched_kw = None
            for kw in sorted(_CLAUSE_KEYWORDS, key=len, reverse=True):
                if remaining.lower().startswith(kw):
                    matched_kw = kw
                    break
            if matched_kw:
                if current_key is not None:
                    clauses[current_key] = " ".join(buffer).strip()
                current_key = matched_kw
                buffer = []
                # Skip the tokens that form this keyword
                kw_token_count = len(matched_kw.split())
                i += kw_token_count
                continue
            else:
                buffer.append(tok)
        else:
            buffer.append(tok)
        i += 1

    if current_key is not None:
        clauses[current_key] = " ".join(buffer).strip()

    return clauses


def _clause_tokens(body: str) -> set:
    return set(re.findall(r"[a-z0-9_.]+", body.lower()))


def score(gold_sql: str, pred_sql: str, config=None) -> float:
    """Return fraction of SQL clauses with matching token sets."""
    gold_clauses = _extract_clauses(gold_sql)
    pred_clauses = _extract_clauses(pred_sql)

    all_keys = set(gold_clauses) | set(pred_clauses)
    if not all_keys:
        return 0.0

    matched = 0
    for key in all_keys:
        g = _clause_tokens(gold_clauses.get(key, ""))
        p = _clause_tokens(pred_clauses.get(key, ""))
        if g == p:
            matched += 1

    return matched / len(all_keys)

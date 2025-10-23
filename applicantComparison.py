#!/usr/bin/env python3
"""
compare_applicant_responses.py

Compare JSON response bodies for applicants across two environments, matching:
- Applicants by first + last name (top-level 'applicant' object)
- Tradelines and similar lists of dicts by 'accountNumber'
- Model factors by 'code'

Ordering differences are ignored. Differences are written to CSV.

Usage:
    python compare_applicant_responses.py \
        --env-a /path/to/az1.json \
        --env-b /path/to/stg.json \
        --out /path/to/differences.csv

Optional flags:
    --scope report|full   Compare only the response body 'report' (default: report)
                          or the entire top-level entry ('full').
"""

import argparse
import json
import csv
import sys
from collections import Counter
from typing import Any, Dict, List, Tuple, Iterable

# ---------------------------
# Helpers: I/O and extraction
# ---------------------------

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_applicant_key(entry: Dict[str, Any]) -> str:
    """
    Use the top-level applicant first+last name as the matching key.
    Fallback to report.applicant if needed.
    """
    try:
        a = entry["applicant"]
        return f"{a['firstName']}_{a['lastName']}"
    except Exception:
        pass
    # Fallback (rare)
    try:
        ra = entry["response"]["body"][0]["report"]["applicant"]
        return f"{ra['firstName']}_{ra['lastName']}"
    except Exception:
        return "UNKNOWN_UNKNOWN"

def extract_report(entry: Dict[str, Any], scope: str) -> Any:
    """
    scope = 'report' -> entry['response']['body'][0]['report'] (default)
    scope = 'full'   -> entire entry
    """
    if scope == "full":
        return entry
    try:
        return entry["response"]["body"][0]["report"]
    except Exception:
        return {}

def index_by_applicant(data: List[Dict[str, Any]], scope: str) -> Dict[str, Any]:
    out = {}
    for entry in data:
        key = get_applicant_key(entry)
        out[key] = extract_report(entry, scope)
    return out

# --------------------------------------
# Deep comparison, ignoring order issues
# --------------------------------------

def json_equivalent(a: Any, b: Any) -> bool:
    """Strict equality for scalars; for dicts sort keys; for lists compare as multisets of JSON strings when not keyed."""
    if type(a) != type(b):
        return False
    if isinstance(a, dict):
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    if isinstance(a, list):
        # Generic list comparison as multiset of JSON-serialized items
        sa = Counter(json.dumps(x, sort_keys=True) for x in a)
        sb = Counter(json.dumps(x, sort_keys=True) for x in b)
        return sa == sb
    return a == b

def map_by_key(items: Iterable[Dict[str, Any]], key_field: str) -> Dict[Any, Dict[str, Any]]:
    m = {}
    for it in items:
        # Only map items that actually have the key; others are ignored here
        if isinstance(it, dict) and key_field in it:
            m[it[key_field]] = it
    return m

def detect_key_field(path: str, a_list: List[Dict[str, Any]], b_list: List[Dict[str, Any]]) -> str:
    """
    Prefer explicit matches:
      - 'accountNumber' for tradelines/collections/etc.
      - 'code' for model factors
    Otherwise, try to infer if a majority of items have one of these keys.
    """
    # Strong hints from path
    if path.endswith("tradeLines") or path.endswith("collections") or "tradeLines" in path or "collections" in path:
        return "accountNumber"
    if path.endswith("factors") or "factors" in path:
        return "code"

    # Heuristic: if many items have accountNumber, use it; else if many have code, use it.
    acc_count = sum(1 for x in a_list + b_list if isinstance(x, dict) and "accountNumber" in x)
    code_count = sum(1 for x in a_list + b_list if isinstance(x, dict) and "code" in x)
    if acc_count >= code_count and acc_count > 0:
        return "accountNumber"
    if code_count > 0:
        return "code"
    return ""

def list_compare(
    a_list: List[Any], b_list: List[Any], path: str, diffs: List[Dict[str, Any]], applicant: str
) -> None:
    """
    Compare lists. If list of dicts with a reliable key field (accountNumber/code), match by that key.
    Otherwise compare as multisets (ignoring order).
    """
    if all(isinstance(x, dict) for x in a_list) and all(isinstance(x, dict) for x in b_list):
        key_field = detect_key_field(path, a_list, b_list)
        if key_field:
            a_map = map_by_key(a_list, key_field)
            b_map = map_by_key(b_list, key_field)

            # Missing/extra keyed items
            for k in sorted(set(a_map.keys()) | set(b_map.keys()), key=lambda x: (str(type(x)), str(x))):
                sub_path = f"{path}[{key_field}={k}]"
                if k not in a_map:
                    diffs.append(row(applicant, "missing_in_env_a", sub_path, None, summarize(b_map[k])))
                elif k not in b_map:
                    diffs.append(row(applicant, "missing_in_env_b", sub_path, summarize(a_map[k]), None))
                else:
                    deep_compare(a_map[k], b_map[k], sub_path, diffs, applicant)
            # Note: items lacking key_field are ignored in this keyed branch
            # If there are many items without the key field, we fall back to multiset compare below
            a_unk = [x for x in a_list if not (isinstance(x, dict) and key_field in x)]
            b_unk = [x for x in b_list if not (isinstance(x, dict) and key_field in x)]
            if a_unk or b_unk:
                # Compare the "unknown-key" leftovers as multisets
                if not json_equivalent(a_unk, b_unk):
                    diffs.append(row(applicant, "list_unkeyed_mismatch", f"{path}[* no-{key_field} items]", summarize(a_unk), summarize(b_unk)))
            return

    # Fallback: generic multiset compare (order-insensitive)
    if not json_equivalent(a_list, b_list):
        diffs.append(row(applicant, "list_mismatch", path, summarize(a_list), summarize(b_list)))

def summarize(value: Any, maxlen: int = 400) -> str:
    """Compact JSON summary for CSV."""
    try:
        s = json.dumps(value, sort_keys=True)
    except Exception:
        s = str(value)
    if len(s) > maxlen:
        s = s[: maxlen - 3] + "..."
    return s

def row(applicant: str, kind: str, path: str, env_a: Any, env_b: Any) -> Dict[str, Any]:
    return {
        "applicant": applicant,
        "difference_type": kind,
        "path": path,
        "env_a_value": summarize(env_a),
        "env_b_value": summarize(env_b),
    }

def deep_compare(a: Any, b: Any, path: str, diffs: List[Dict[str, Any]], applicant: str) -> None:
    # Type mismatch
    if type(a) != type(b):
        diffs.append(row(applicant, "type_mismatch", path, type(a).__name__, type(b).__name__))
        return

    # Dict
    if isinstance(a, dict):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in sorted(a_keys | b_keys):
            sub_path = f"{path}.{k}" if path else k
            if k not in a:
                diffs.append(row(applicant, "missing_in_env_a", sub_path, None, summarize(b.get(k))))
            elif k not in b:
                diffs.append(row(applicant, "missing_in_env_b", sub_path, summarize(a.get(k)), None))
            else:
                deep_compare(a[k], b[k], sub_path, diffs, applicant)
        return

    # List
    if isinstance(a, list):
        list_compare(a, b, path, diffs, applicant)
        return

    # Scalars
    if a != b:
        diffs.append(row(applicant, "value_mismatch", path, a, b))

# ---------------------------
# CSV writing
# ---------------------------

def write_csv(rows: List[Dict[str, Any]], out_path: str) -> None:
    fieldnames = ["applicant", "difference_type", "path", "env_a_value", "env_b_value"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

# ---------------------------
# Main flow
# ---------------------------

def compare_files(env_a_path: str, env_b_path: str, out_csv: str, scope: str = "report") -> None:
    data_a = load_json(env_a_path)
    data_b = load_json(env_b_path)

    # Expect lists of entries
    if not isinstance(data_a, list) or not isinstance(data_b, list):
        print("ERROR: Both input files must be JSON arrays of applicant entries.", file=sys.stderr)
        sys.exit(2)

    idx_a = index_by_applicant(data_a, scope)
    idx_b = index_by_applicant(data_b, scope)

    diffs: List[Dict[str, Any]] = []

    # Compare applicants present in env A
    for applicant, a_report in idx_a.items():
        if applicant not in idx_b:
            diffs.append(row(applicant, "missing_in_env_b", "(applicant)", summarize(a_report), None))
            continue
        b_report = idx_b[applicant]
        deep_compare(a_report, b_report, "", diffs, applicant)

    # Applicants present only in env B
    for applicant in idx_b.keys():
        if applicant not in idx_a:
            diffs.append(row(applicant, "missing_in_env_a", "(applicant)", None, summarize(idx_b[applicant])))

    write_csv(diffs, out_csv)

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare applicant response bodies across two JSON files and output differences to CSV.")
    p.add_argument("--env-a", required=True, help="Path to Environment A JSON (e.g., az1)")
    p.add_argument("--env-b", required=True, help="Path to Environment B JSON (e.g., stg)")
    p.add_argument("--out", required=True, help="Path to output CSV")
    p.add_argument("--scope", choices=["report", "full"], default="report",
                   help="Compare only response body 'report' (default) or entire entry ('full').")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    compare_files(args.env_a, args.env_b, args.out, scope=args.scope)

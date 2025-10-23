#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests

ENV_TARGETS = {
    "test1": {
        "url": "https://aztest1.devops.dev-openlending.com/lpcr-service/reports",
        "host": "aztest1.devops.dev-openlending.com",
    },
    "test4": {
        "url": "https://aztest4.devops.dev-openlending.com/lpcr-service/reports",
        "host": "aztest4.devops.dev-openlending.com",
    },
    "staging": {
        "url": "https://staging.stg.aks.prd.lend-pro.com/lpcr-service/reports",
        "host": "staging.stg.aks.prd.lend-pro.com",
    },
}

EFX_SETTINGS = {
    "institutionId": "1239438",
    "origin": "INDIRECT",
    "products": [
        "05201" 
    ],
    "credentials": {
        "subscriberCode": "999ZS06891",
        "password": "[INSERT PW]"
    },
    "productCode": "07000",
    "industryCode": "I",
    "permissiblePurpose": "CI"
}

TU_SETTINGS = {
    "institutionId": "1239438",
    "origin": "INDIRECT",
    "products": [
        "00W82" 
    ],
    "credentials": {
         "subscriberCode": "06226909913",
         "password": "[INSERT PW]"
    },
    "productCode": "07000",
    "industryCode": "I",
    "permissiblePurpose": "CI"
}

XPN_SETTINGS = {
    "institutionId": "25693",
    "origin": "INDIRECT",
    "products": [
        "FE"
    ],
    "credentials": {
         "subscriberCode": "5991774",
        "password": "[INSERT PW]"
    },
    "productCode": "",
    "industryCode": "",
    "permissiblePurpose": ""
}

LN_SETTINGS = {
    "institutionId": "1239438",
    "origin": "INDIRECT",
    "products": [
    "RVA1503_0" 
    ],
    "credentials": {
        "subscriberCode": "AmTrustNADEVRVXML",
        "password": "[INSERT PW]"
    },
    "productCode": "RISK_VIEW",
    "industryCode": "",
    "permissiblePurpose": "Written Consent Prequalification"
}

BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "PostmanRuntime/7.49.0",
    "Accept": "*/*",
    "Cache-Control": "no-cache",
    "Postman-Token": "fe217bfb-e71c-4e46-8cf2-3a2a80a4da6e",
    # Host is set dynamically per environment
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def load_applicants(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Input file must be a JSON array of applicant objects.")
    return data

def make_payload(applicant: Dict[str, Any], bureau: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bureau": bureau,          # now configurable
        "type": "SOFT",
        "settings": settings,
        "applicants": [applicant],
    }

def build_headers(token: str, host_header: str) -> Dict[str, str]:
    headers = dict(BASE_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    headers["Host"] = host_header
    return headers

def post_once(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: float,
    verify_ssl: bool
) -> requests.Response:
    return requests.post(url, headers=headers, json=payload, timeout=timeout, verify=verify_ssl)

def post_with_retries(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    retries: int,
    backoff_seconds: float,
    timeout: float,
    verify_ssl: bool
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return post_once(url, headers, payload, timeout=timeout, verify_ssl=verify_ssl)
        except Exception as e:
            last_exc = e
            if attempt < retries:
                sleep_for = backoff_seconds * (2 ** attempt)
                print(f"Retrying in {sleep_for:.1f}s ...")
                time.sleep(sleep_for)
            else:
                raise e
    if last_exc:
        raise last_exc
    raise RuntimeError("Unknown error in post_with_retries")

def parse_response(resp: requests.Response) -> Dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return {
        "status_code": resp.status_code,
        "reason": resp.reason,
        "headers": dict(resp.headers),
        "body": body,
    }

def resolve_target(env: str, url_override: Optional[str], host_override: Optional[str]) -> Dict[str, str]:
    if env not in ENV_TARGETS:
        raise ValueError(f"Unknown env '{env}'. Valid options: {', '.join(ENV_TARGETS.keys())}")
    target = ENV_TARGETS[env].copy()
    if url_override:
        target["url"] = url_override
    if host_override:
        target["host"] = host_override
    return target

def main():
    parser = argparse.ArgumentParser(description="Submit LPCR report requests sequentially for applicants from a JSON file and collect responses.")
    parser.add_argument("--input", "-i", required=True, help="Path to input JSON file (array of applicant objects).")
    parser.add_argument("--output", "-o", required=True, help="Path to write output JSON file (array of responses).")
    parser.add_argument("--token", "-t", help="Bearer token. If omitted, reads from env var LPCR_TOKEN.")
    parser.add_argument("--env", choices=list(ENV_TARGETS.keys()), default="test1",
                        help="Target environment (default: test1).")
    parser.add_argument("--url", help="Override URL (optional).")
    parser.add_argument("--host", help="Override Host header (optional).")
    parser.add_argument("--bureau", choices=["EFX", "TU", "XPN", "LN"], default="EFX",
                        help="Credit bureau to use in the request payload (default: EFX).")
    parser.add_argument("--retries", type=int, default=2, help="Number of retry attempts per request (default: 2).")
    parser.add_argument("--backoff", type=float, default=0.5, help="Initial backoff seconds for retries (exponential) (default: 0.5).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30).")
    parser.add_argument("--insecure", action="store_true",
                        help="Disable SSL verification (NOT recommended). Useful only for certain test environments.")
    args = parser.parse_args()

    if (args.bureau == "EFX"):
        FIXED_SETTINGS = EFX_SETTINGS
    elif (args.bureau == "TU"):
        FIXED_SETTINGS = TU_SETTINGS
    elif (args.bureau == "XPN"):
        FIXED_SETTINGS = XPN_SETTINGS
    elif (args.bureau == "LN"):
        FIXED_SETTINGS = LN_SETTINGS
    else:
        print("Bureau not recognized: " + args.bureau)

    token = args.token or os.getenv("LPCR_TOKEN")
    if not token:
        print("Error: Missing bearer token. Provide --token or set LPCR_TOKEN env var.", file=sys.stderr)
        sys.exit(2)

    try:
        applicants = load_applicants(args.input)
    except Exception as e:
        print(f"Error reading input file: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        target = resolve_target(args.env, args.url, args.host)
    except Exception as e:
        print(f"Error resolving target: {e}", file=sys.stderr)
        sys.exit(2)

    url = target["url"]
    host_header = target["host"]
    headers = build_headers(token, host_header)

    # Log startup config
    print(f"Environment: {args.env}")
    print(f"Using URL:  {url}")
    print(f"Host header: {host_header}")
    print(f"Bureau: {args.bureau}")

    results: List[Dict[str, Any]] = []

    for idx, applicant in enumerate(applicants):
        echo = {
            "index": idx,
            "firstName": applicant.get("firstName"),
            "lastName": applicant.get("lastName"),
            "ssn_last4": (applicant.get("ssn") or "")[-4:],
        }

        payload = make_payload(applicant, bureau=args.bureau, settings=FIXED_SETTINGS)

        print(f"[{idx+1}/{len(applicants)}] POST {url} (bureau={args.bureau})")

        try:
            resp = post_with_retries(
                url=url,
                headers=headers,
                payload=payload,
                retries=args.retries,
                backoff_seconds=args.backoff,
                timeout=args.timeout,
                verify_ssl=not args.insecure
            )
            parsed = parse_response(resp)
            results.append({
                "applicant": echo,
                "request_payload": payload,  # remove if you don't want to log requests
                "response": parsed
            })
            print(f" -> status={resp.status_code}")
        except Exception as e:
            results.append({
                "applicant": echo,
                "request_payload": payload,
                "error": repr(e)
            })
            print(f" -> ERROR: {e}", file=sys.stderr)

    try:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {len(results)} result(s) to {args.output}")
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()

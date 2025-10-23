# LPCR Report Submitter – README

A small CLI tool that reads a JSON array of applicant objects, submits one LPCR report request **per applicant** to a selected environment, and writes all responses to an output JSON file.

---

## Features
- Reads applicants from a JSON file (array of objects).
- Sends **one POST request per applicant** with fixed `settings`.
- Selectable environments via `--env {test1,test4,staging}` with correct URL **and** `Host` header.
- Optional `--url`/`--host` overrides for custom targets.
- Bearer token via flag or environment variable.
- Retries with exponential backoff, request timeouts, and optional SSL disable for test setups.
- Collects and writes all responses (status, headers, body) to a single output JSON file.
- Console logging of environment, URL/Host, and per-request status.

---

## Requirements
- **Python**: 3.8+
- **Packages**: `requests`

Install dependencies:

```bash
pip install requests
```

---

## Input File Format (applicants)
The input file **must** be a JSON array of applicant objects. Example:

```json
[
  {
    "firstName": "PNTDHB",
    "middleName": "",
    "lastName": "FYHOAOX",
    "ssn": "666019362",
    "street1": "9690 FWAPZQIWN",
    "city": "EAST SPARTA",
    "state": "OH",
    "zip": "44626",
    "birthDate": "1972-07-09",
    "phone": "5555555555"
  },
  {
    "firstName": "CIYQ",
    "middleName": "C",
    "lastName": "DHLPHVA",
    "ssn": "666009422",
    "street1": "3753 HLUBABVXRMIG",
    "city": "LEWISTON",
    "state": "ID",
    "zip": "99472",
    "birthDate": "1960-12-09",
    "phone": "5555555555"
  }
]
```

> The script sends **each** applicant as the single element of the `applicants` array in the request payload, combined with a fixed `settings` block (shown below).

---

## Environments & URLs
You can choose the target with `--env`. The script sets both the request URL and the `Host` header.

| Env      | URL                                                                  | Host header                           |
|----------|----------------------------------------------------------------------|---------------------------------------|
| `test1`  | `https://aztest1.devops.dev-openlending.com/lpcr-service/reports`    | `aztest1.devops.dev-openlending.com`  |
| `test4`  | `https://aztest4.devops.dev-openlending.com/lpcr-service/reports`    | `aztest4.devops.dev-openlending.com`  |
| `staging`| `https://staging.stg.aks.prd.lend-pro.com/lpcr-service/reports`      | `staging.stg.aks.prd.lend-pro.com`    |

Overrides:
- `--url` to replace the request URL
- `--host` to replace the `Host` header

---

## Fixed Request Structure
For each applicant, the request body looks like:

```json
{
  "bureau": "EFX",
  "type": "SOFT",
  "settings": {
    "institutionId": "1239438",
    "origin": "INDIRECT",
    "products": ["05201"],
    "credentials": {"subscriberCode": "999ZS06891", "password": "@U1"},
    "productCode": "07000",
    "industryCode": "I",
    "permissiblePurpose": "CI"
  },
  "applicants": [ { /* one applicant from the input file */ } ]
}
```

HTTP headers sent include:
- `Content-Type: application/json`
- `Authorization: Bearer <token>`
- `User-Agent: PostmanRuntime/7.49.0`
- `Accept: */*`
- `Cache-Control: no-cache`
- `Postman-Token: fe217bfb-e71c-4e46-8cf2-3a2a80a4da6e`
- `Host: <per environment>`
- `Accept-Encoding: gzip, deflate, br`
- `Connection: keep-alive`

> `Content-Length` is intentionally omitted (managed by `requests`).

---

## Authentication
Provide the bearer token via either:

- Command-line flag: `--token "YOUR_BEARER_TOKEN"`
- Environment variable: `LPCR_TOKEN`

If neither is supplied, the script exits with an error.

---

## Usage

Basic invocation (defaults to `--env test1`):

```bash
python submit_reports.py \
  --input applicants.json \
  --output responses.json \
  --token "YOUR_BEARER_TOKEN"
```

Pick a different environment:

```bash
python submit_reports.py -i applicants.json -o responses.json -t "YOUR_BEARER_TOKEN" --env test4
python submit_reports.py -i applicants.json -o responses.json -t "YOUR_BEARER_TOKEN" --env staging
```

Override URL/Host explicitly:

```bash
python submit_reports.py -i applicants.json -o responses.json -t "YOUR_BEARER_TOKEN" \
  --env test1 \
  --url  "https://custom.example.com/lpcr-service/reports" \
  --host "custom.example.com"
```

Common options:

- `--retries INT`  (default: `2`) – retry attempts per request
- `--backoff SEC`  (default: `0.5`) – initial backoff; doubles each retry (0.5, 1.0, 2.0, ...)
- `--timeout SEC`  (default: `30`) – per-request timeout
- `--insecure` – disables SSL verification (test environments only)

---

## Output File
The script writes a JSON array with one element per applicant, including a small identifying echo and the server response.

Example `responses.json` (shape only):

```json
[
  {
    "applicant": {
      "index": 0,
      "firstName": "PNTDHB",
      "lastName": "FYHOAOX",
      "ssn_last4": "9362"
    },
    "request_payload": { /* request body that was sent */ },
    "response": {
      "status_code": 200,
      "reason": "OK",
      "headers": { /* response headers */ },
      "body": { /* parsed JSON or raw text */ }
    }
  },
  {
    "applicant": { /* ... */ },
    "error": "<repr(exception)>"
  }
]
```

> If response parsing as JSON fails, `body` contains the raw text response instead.

---

## Logging & Verbosity
- At startup, the script logs the resolved **environment**, **URL**, and **Host**.
- For each applicant, it logs `POST <url>` and the resulting HTTP status or error.

If you prefer structured logs (timestamp, level, file output), convert the `print` statements to Python’s `logging` module and add a `--log-file` flag.

---

## Exit Codes
- `0` – success
- `2` – usage/config/read/write errors (e.g., missing token, unreadable input, output write failure)
- Nonzero (propagated) – other unhandled exceptions

---

## Troubleshooting
- **401/403** – Check bearer token or permissions for the chosen environment.
- **404** – Verify URL/Host or environment selection; confirm any custom overrides.
- **5xx / timeouts** – Increase `--timeout`, `--retries`, and/or `--backoff`. Try again later.
- **SSL errors** – For test setups with custom certs, try `--insecure` (not for production).
- **Malformed input** – Ensure the input is a **JSON array** and each applicant object contains the expected fields.

---

## Security Notes
- Treat bearer tokens as secrets. Prefer passing via environment variable (`LPCR_TOKEN`).
- Avoid committing tokens, responses with PII, or detailed request payloads to version control.
- Consider removing `request_payload` from the results if you don’t need that echo in your logs.

---

## License
Internal tooling; apply your organization’s standard internal use policy.

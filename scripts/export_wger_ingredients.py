#!/usr/bin/env python3
"""Stream wger ingredientinfo pages into a JSON array file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

from pete_e.infrastructure.wger_url_policy import (
    INVALID_NEXT_URL,
    MAX_PAGES,
    PAGE_LIMIT_EXCEEDED,
    PAGINATION_CYCLE,
    REDIRECT_REJECTED,
    WgerUrlPolicy,
    WgerUrlPolicyError,
)


RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


def normalize_base_url(raw_url: str) -> str:
    return _url_policy(raw_url).api_root


def _url_policy(raw_url: str) -> WgerUrlPolicy:
    try:
        return WgerUrlPolicy.from_base(raw_url)
    except WgerUrlPolicyError as exc:
        raise RuntimeError(str(exc)) from None


def build_headers(auth_header: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def resolve_auth_header(cli_header: str | None) -> str | None:
    if cli_header:
        return cli_header

    env_header = os.getenv("WGER_AUTH_HEADER")
    if env_header:
        return env_header

    api_key = os.getenv("WGER_API_KEY")
    if api_key:
        return f"Token {api_key}"

    return None


def request_json(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    for attempt in range(retries + 1):
        response: requests.Response | None = None
        try:
            response = session.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise RuntimeError(REDIRECT_REJECTED)
            if response.status_code not in RETRY_STATUSES:
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError(f"Expected JSON object from {url}")
                return data
        except (requests.RequestException, ValueError) as exc:
            if attempt >= retries:
                raise RuntimeError(f"Request failed for {url}: {exc}") from exc
        else:
            if attempt >= retries:
                response.raise_for_status()

        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after and retry_after.isdigit():
            sleep_seconds = int(retry_after)
        else:
            sleep_seconds = min(60, 2**attempt)

        print(f"Retrying in {sleep_seconds}s after request problem at {url}", file=sys.stderr)
        time.sleep(sleep_seconds)

    raise RuntimeError(f"Request failed for {url}")


def resolve_next_page(policy: WgerUrlPolicy, current_url: str, next_value: object) -> str:
    """Return the next safe page URL, or an empty string at pagination end."""
    if next_value is None or next_value == "":
        return ""
    if not isinstance(next_value, str):
        raise RuntimeError(INVALID_NEXT_URL)

    try:
        return policy.resolve_pagination(current_url, next_value)
    except WgerUrlPolicyError as exc:
        raise RuntimeError(str(exc)) from None


def export_ingredients(
    *,
    base_url: str,
    language: int,
    limit: int,
    offset: int,
    output: Path,
    auth_header: str | None,
    timeout: float,
    retries: int,
    max_pages: int | None,
) -> int:
    if max_pages is not None and max_pages > MAX_PAGES:
        raise RuntimeError(PAGE_LIMIT_EXCEEDED)

    policy = _url_policy(base_url)
    url = policy.resolve_endpoint("/ingredientinfo/")
    params: dict[str, Any] | None = {
        "language": language,
        "limit": limit,
        "offset": offset,
        "ordering": "id",
    }
    headers = build_headers(auth_header)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(f"{output.suffix}.tmp")

    total_seen = 0
    page_number = 0
    expected_total: int | None = None
    first_item = True
    seen_urls: set[str] = set()

    with requests.Session() as session, tmp_output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")

        while url:
            request_url = policy.request_url(url, params)
            if request_url in seen_urls:
                raise RuntimeError(PAGINATION_CYCLE)
            if page_number >= MAX_PAGES:
                raise RuntimeError(PAGE_LIMIT_EXCEEDED)
            seen_urls.add(request_url)

            page_number += 1
            data = request_json(
                session,
                url,
                headers=headers,
                params=params,
                timeout=timeout,
                retries=retries,
            )

            if expected_total is None and isinstance(data.get("count"), int):
                expected_total = data["count"]

            results = data.get("results", [])
            if not isinstance(results, list):
                raise RuntimeError(f"Expected results array on page {page_number}")

            for item in results:
                if first_item:
                    first_item = False
                else:
                    handle.write(",\n")
                json.dump(item, handle, ensure_ascii=False, separators=(",", ":"))

            total_seen += len(results)
            total_label = expected_total if expected_total is not None else "unknown"
            print(f"Fetched page {page_number}: {total_seen}/{total_label} ingredients")

            if max_pages is not None and page_number >= max_pages:
                break

            url = resolve_next_page(policy, request_url, data.get("next"))
            params = None

        handle.write("\n]\n")

    tmp_output.replace(output)
    return total_seen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("WGER_BASE_URL", "https://wger.de/api/v2"))
    parser.add_argument("--language", type=int, default=2)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("docs/postman/out/wger_ingredientinfo_language_2.json"))
    parser.add_argument("--auth-header", default=None, help='Optional Authorization header, e.g. "Token ..."')
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit <= 0:
        raise SystemExit("--limit must be greater than zero")
    if args.offset < 0:
        raise SystemExit("--offset must be zero or greater")
    if args.max_pages is not None and args.max_pages <= 0:
        raise SystemExit("--max-pages must be greater than zero")
    if args.max_pages is not None and args.max_pages > MAX_PAGES:
        raise SystemExit(f"--max-pages cannot exceed {MAX_PAGES}")

    total = export_ingredients(
        base_url=args.base_url,
        language=args.language,
        limit=args.limit,
        offset=args.offset,
        output=args.output,
        auth_header=resolve_auth_header(args.auth_header),
        timeout=args.timeout,
        retries=args.retries,
        max_pages=args.max_pages,
    )
    print(f"Wrote {total} ingredients to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

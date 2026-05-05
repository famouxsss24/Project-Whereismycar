from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def post_json(server_url: str, payload: dict[str, object], timeout: float) -> tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        server_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8", errors="replace")
        status = getattr(response, "status", response.getcode())
    return status, content


def emit_payload(payload: dict[str, object], server_url: str | None, timeout: float, pretty: bool) -> None:
    indent = 2 if pretty else None
    print(json.dumps(payload, ensure_ascii=False, indent=indent))
    if not server_url:
        return

    try:
        status, content = post_json(server_url, payload, timeout)
        print(f"POST {server_url} -> {status}", file=sys.stderr)
        if content:
            print(content, file=sys.stderr)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to POST JSON to {server_url}: {exc}") from exc

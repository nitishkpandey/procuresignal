"""Structural full-stack smoke test for ProcureSignal.

Runs against a live stack (default http://localhost:8000). Verifies REST and
WebSocket contracts and exits non-zero on the first violation. Tolerant of async
retrieval: it does not require the feed to be populated, and it asserts the WS
frame *protocol*, not LLM content.

Requires: httpx, websockets  (pip install httpx websockets)
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx

VALID_TERMINAL = {"end", "error"}
VALID_TYPES = {"start", "stream", "end", "error"}


def assert_valid_frame_sequence(frames: list[dict]) -> None:
    """Raise AssertionError unless frames form a valid chat-WS sequence."""
    assert frames, "no frames received"
    assert frames[0].get("type") == "start", f"first frame must be 'start', got {frames[0]!r}"
    for f in frames:
        assert f.get("type") in VALID_TYPES, f"unknown frame type: {f!r}"
    assert (
        frames[-1].get("type") in VALID_TERMINAL
    ), f"sequence must end with 'end' or 'error', got {frames[-1]!r}"


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + (f" - {detail}" if detail and not ok else ""))
        if not ok:
            self.failures += 1


def wait_for_health(base: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/health", timeout=3.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2.0)
    return False


async def collect_ws_frames(ws_url: str, user_id: str, conversation_id: str) -> list[dict]:
    import websockets  # lazy import so the validator is unit-testable without the dep

    url = f"{ws_url}/api/ws/chat/{user_id}/{conversation_id}"
    frames: list[dict] = []
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"message": "What does a tariff mean for my supply chain?"}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
            frame = json.loads(raw)
            frames.append(frame)
            if frame.get("type") in VALID_TERMINAL:
                break
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description="ProcureSignal full-stack smoke test")
    parser.add_argument("--wait", action="store_true", help="poll /health before running")
    parser.add_argument("--api-url", default=os.getenv("API_URL", "http://localhost:8000"))
    parser.add_argument("--ws-url", default=os.getenv("WS_URL", "ws://localhost:8000"))
    args = parser.parse_args()

    api = args.api_url.rstrip("/")
    c = Checker()
    user_id = "smoke@example.com"

    if args.wait:
        print(f"Waiting for {api}/health ...")
        if not wait_for_health(api):
            print("✗ API never became healthy", file=sys.stderr)
            return 1

    print("REST checks:")
    r = httpx.get(f"{api}/health", timeout=5.0)
    c.check("GET /health", r.status_code == 200 and r.json().get("status") == "healthy")

    r = httpx.get(f"{api}/api/health", timeout=5.0)
    c.check(
        "GET /api/health database connected",
        r.status_code == 200 and r.json().get("database") == "connected",
    )

    prefs = {
        "user_id": user_id,
        "interested_categories": ["automotive"],
        "interested_suppliers": ["Bosch"],
        "interested_regions": ["Germany"],
        "interested_signals": ["tariff"],
        "excluded_categories": [],
        "excluded_suppliers": [],
        "excluded_regions": [],
        "excluded_signals": [],
    }
    r = httpx.post(f"{api}/api/preferences", json=prefs, timeout=10.0)
    c.check("POST /api/preferences", r.status_code == 200)
    r = httpx.get(f"{api}/api/preferences", params={"user_id": user_id}, timeout=10.0)
    c.check(
        "GET /api/preferences round-trips",
        r.status_code == 200
        and "bosch" in [s.lower() for s in r.json().get("interested_suppliers", [])],
    )

    r = httpx.get(f"{api}/api/feed", params={"user_id": user_id, "limit": 10}, timeout=20.0)
    body = r.json() if r.status_code == 200 else {}
    c.check(
        "GET /api/feed valid shape",
        r.status_code == 200
        and isinstance(body.get("articles"), list)
        and body.get("total_count", -1) >= 0,
    )

    r = httpx.get(f"{api}/api/search", params={"q": "tariff", "limit": 5}, timeout=10.0)
    body = r.json() if r.status_code == 200 else {}
    c.check(
        "GET /api/search valid shape",
        r.status_code == 200
        and isinstance(body.get("results"), list)
        and body.get("query") == "tariff",
    )

    r = httpx.post(f"{api}/api/conversations", params={"user_id": user_id}, timeout=10.0)
    conv_id = r.json().get("conversation_id") if r.status_code == 200 else None
    c.check("POST /api/conversations", bool(conv_id))

    r = httpx.get(f"{api}/api/conversations", params={"user_id": user_id}, timeout=10.0)
    ids = (
        [conv.get("conversation_id") for conv in r.json().get("conversations", [])]
        if r.status_code == 200
        else []
    )
    c.check("GET /api/conversations lists new id", conv_id in ids)

    if conv_id:
        r = httpx.get(f"{api}/api/conversations/{conv_id}/messages", timeout=10.0)
        c.check("GET messages (empty)", r.status_code == 200 and r.json().get("total_count") == 0)

    print("WebSocket check:")
    ws_conv = conv_id or str(uuid.uuid4())
    try:
        frames = asyncio.run(collect_ws_frames(args.ws_url.rstrip("/"), user_id, ws_conv))
        assert_valid_frame_sequence(frames)
        c.check(f"WS chat protocol ({len(frames)} frames, ends {frames[-1]['type']})", True)
    except Exception as exc:  # noqa: BLE001
        c.check("WS chat protocol", False, str(exc))

    print()
    if c.failures:
        print(f"SMOKE TEST FAILED: {c.failures} check(s) failed.")
        return 1
    print("SMOKE TEST PASSED: all checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

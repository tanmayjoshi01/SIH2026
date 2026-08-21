"""
scripts/_ws_client_subprocess.py

Helper process for scripts/ws_reconnect_test.py. Connects to /ws/incidents
and prints one line per received event ("EVENT <json>") plus a "CONNECTED"
line once the handshake completes, so the parent process can synchronize
on both without needing a shared queue across the process boundary.

Not meant to be run directly -- the parent test script launches this as a
subprocess and kills it (SIGKILL-equivalent, no cooperative shutdown) to
simulate a client that vanishes without a clean WebSocket close handshake
(a crashed tab, a dropped network link).
"""

from __future__ import annotations

import asyncio
import sys

import websockets


async def main(url: str) -> None:
    async with websockets.connect(url) as ws:
        print("CONNECTED", flush=True)
        async for message in ws:
            print(f"EVENT {message}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))

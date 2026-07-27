"""Generate a project asset with Gemini. Kept in-repo so images are regenerable.

    python tools/gen_image.py docs/img/hero.png "a prompt"

Needs GEMINI_API_KEY in .env. The images are committed; this exists so nobody
has to guess what prompt produced them.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

MODEL = os.environ.get("NANOLOOP_IMAGE_MODEL", "gemini-3-pro-image")


def generate(prompt: str, out: Path) -> bool:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("no GEMINI_API_KEY")
        return False
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=300).read())
    except Exception as e:  # noqa: BLE001
        detail = getattr(e, "read", lambda: b"")().decode("utf-8", "replace")[:300]
        print(f"  failed: {e} {detail}")
        return False
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        blob = part.get("inlineData", {}).get("data")
        if blob:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(blob))
            print(f"  wrote {out} ({out.stat().st_size // 1024} KB)")
            return True
    print("  no image in response")
    return False


if __name__ == "__main__":
    ok = generate(sys.argv[2], Path(sys.argv[1]))
    raise SystemExit(0 if ok else 1)

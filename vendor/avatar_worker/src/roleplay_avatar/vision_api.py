"""Image-understanding requests over the shared provider gateway."""

import base64
import json
from pathlib import Path

from .agents import ModelGateway


async def image_json(prompt, paths, *, gateway=None, max_tokens=2400):
    content = [{"type": "text", "text": prompt + "\nReturn one JSON object."}]
    for path in paths:
        path = Path(path)
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        data = base64.b64encode(path.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    raw = ""
    async for token in (gateway or ModelGateway("vision")).stream(
        "Read the supplied character reference images.",
        [{"role": "user", "content": content}],
        max_tokens=max_tokens,
        temperature=0.2,
    ):
        raw += token
        if len(raw) > 32000:
            raise ValueError("Vision output exceeded its limit")
    value, _ = json.JSONDecoder().raw_decode(raw[raw.index("{") :])
    return value, raw

from __future__ import annotations

import json
import re
from hashlib import sha256


def tuple_id(prefix: str, *components: str) -> str:
    payload = json.dumps(components, separators=(",", ":"))
    digest = sha256(payload.encode()).hexdigest()[:12]
    readable = "_".join(readable_component(component) for component in components)
    return f"{prefix}_{readable}_{digest}"


def readable_component(component: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9]+", "_", component).strip("_").lower()
    return readable or "blank"

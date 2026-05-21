"""SHA256 file-based cache for LLM synthesis outputs.

Cache key = SHA256 of the serialised input data (sorted for stability).
Cache value = JSON dict stored at .synth-cache/{level}/{hash}.json

Levels: "modules" | "repos" | "features"
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, cache_dir: Path, enabled: bool = True) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, level: str, key_data: Any) -> dict | None:
        """Return cached value or None on miss."""
        if not self.enabled:
            return None
        path = self._key_path(level, key_data)
        if path.exists():
            self._hits += 1
            return json.loads(path.read_text(encoding="utf-8"))
        self._misses += 1
        return None

    def set(self, level: str, key_data: Any, value: dict) -> None:
        """Persist a value to the cache."""
        if not self.enabled:
            return
        path = self._key_path(level, key_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self, level: str | None = None) -> None:
        """Remove cached entries. Pass level to clear only that level."""
        if level:
            shutil.rmtree(self.cache_dir / level, ignore_errors=True)
        else:
            shutil.rmtree(self.cache_dir, ignore_errors=True)

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 2) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _key_path(self, level: str, key_data: Any) -> Path:
        key_str = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(key_str.encode()).hexdigest()
        return self.cache_dir / level / f"{h}.json"

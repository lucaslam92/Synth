"""Tests for synth.cache — SHA256 file-based cache."""

import json
from pathlib import Path

import pytest

from synth.cache import Cache


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / ".synth-cache")


class TestCacheGetSet:
    def test_miss_returns_none(self, cache: Cache) -> None:
        assert cache.get("modules", {"key": "val"}) is None

    def test_set_then_get(self, cache: Cache) -> None:
        data = {"text": "hello world", "code_map": {}}
        cache.set("modules", {"label": "auth"}, data)
        result = cache.get("modules", {"label": "auth"})
        assert result == data

    def test_different_keys_are_independent(self, cache: Cache) -> None:
        cache.set("modules", {"label": "auth"}, {"text": "auth desc"})
        cache.set("modules", {"label": "order"}, {"text": "order desc"})
        assert cache.get("modules", {"label": "auth"}) == {"text": "auth desc"}
        assert cache.get("modules", {"label": "order"}) == {"text": "order desc"}

    def test_same_key_different_levels_are_independent(self, cache: Cache) -> None:
        key = {"repo": "svc-a"}
        cache.set("modules", key, {"text": "module"})
        cache.set("repos", key, {"text": "repo"})
        assert cache.get("modules", key) == {"text": "module"}
        assert cache.get("repos", key) == {"text": "repo"}

    def test_key_order_stable(self, cache: Cache) -> None:
        """Key serialisation must be stable regardless of dict insertion order."""
        cache.set("modules", {"b": 2, "a": 1}, {"text": "ok"})
        result = cache.get("modules", {"a": 1, "b": 2})
        assert result == {"text": "ok"}

    def test_value_persisted_to_disk(self, cache: Cache, tmp_path: Path) -> None:
        cache.set("repos", {"repo": "svc"}, {"text": "persisted"})
        # Recreate cache from same dir — value must survive
        cache2 = Cache(tmp_path / ".synth-cache")
        assert cache2.get("repos", {"repo": "svc"}) == {"text": "persisted"}

    def test_unicode_value_roundtrips(self, cache: Cache) -> None:
        payload = {"text": "中文描述 ✓", "code_map": {"模块": []}}
        cache.set("modules", {"k": 1}, payload)
        assert cache.get("modules", {"k": 1}) == payload


class TestCacheDisabled:
    def test_disabled_cache_always_misses(self, tmp_path: Path) -> None:
        c = Cache(tmp_path / "cache", enabled=False)
        c.set("modules", {"k": 1}, {"text": "x"})
        assert c.get("modules", {"k": 1}) is None

    def test_disabled_creates_no_files(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        c = Cache(cache_dir, enabled=False)
        c.set("modules", {"k": 1}, {"text": "x"})
        assert not cache_dir.exists()


class TestCacheClear:
    def test_clear_specific_level(self, cache: Cache) -> None:
        cache.set("modules", {"k": 1}, {"text": "mod"})
        cache.set("repos", {"k": 1}, {"text": "repo"})
        cache.clear("modules")
        assert cache.get("modules", {"k": 1}) is None
        assert cache.get("repos", {"k": 1}) == {"text": "repo"}

    def test_clear_all_levels(self, cache: Cache) -> None:
        cache.set("modules", {"k": 1}, {"text": "mod"})
        cache.set("repos", {"k": 1}, {"text": "repo"})
        cache.clear()
        assert cache.get("modules", {"k": 1}) is None
        assert cache.get("repos", {"k": 1}) is None

    def test_clear_nonexistent_level_is_safe(self, cache: Cache) -> None:
        cache.clear("features")  # Should not raise


class TestCacheStats:
    def test_initial_stats(self, cache: Cache) -> None:
        stats = cache.stats
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_hit_rate_calculation(self, cache: Cache) -> None:
        cache.set("modules", {"k": 1}, {"text": "x"})
        cache.get("modules", {"k": 1})   # hit
        cache.get("modules", {"k": 2})   # miss
        cache.get("modules", {"k": 1})   # hit
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.67, abs=0.01)

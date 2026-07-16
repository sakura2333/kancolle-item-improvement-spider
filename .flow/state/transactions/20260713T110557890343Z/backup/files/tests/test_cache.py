import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import util.cache as cache
from util.http_cache import client, settings, storage, transport


class FakeResponse:
    def __init__(self, status_code=200, text="fresh", content=b"fresh", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class CacheFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base_patch = patch.object(settings, "BASE_DIR", self.temp.name)
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)
        cache.reset_fetch_audit()

    def _write_cache(
        self,
        url: str,
        text: str = "cached",
        *,
        age_seconds: int = 0,
    ) -> Path:
        path = Path(cache.url_to_path(url))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        meta = {
            cache.cache_key(str(path)): {
                "url": url,
                "fetched_at": int(time.time()) - age_seconds,
                "etag": '"fixture"',
                "fetch_status": "fresh",
                "used_cache_fallback": False,
            }
        }
        Path(cache.meta_index_path()).write_text(json.dumps(meta), encoding="utf-8")
        return path

    def test_strict_fetch_rejects_cache_fallback_after_ttl_expires(self):
        url = "https://example.test/data.json"
        self._write_cache(url, age_seconds=settings.LOCAL_CACHE_TTL_SECONDS + 1)
        with patch.object(
            client.transport,
            "request_with_cache_headers",
            side_effect=requests.ConnectionError("offline"),
        ):
            with self.assertRaisesRegex(RuntimeError, "fresh fetch required"):
                cache.fetch(url, require_fresh=True)

        meta = cache.get_fetch_meta(url)
        self.assertEqual(meta["fetch_status"], "stale")
        self.assertTrue(meta["used_cache_fallback"])
        self.assertFalse(meta["validated_in_run"])

    def test_non_strict_fetch_can_fall_back(self):
        url = "https://example.test/data.json"
        self._write_cache(url)
        with patch.object(
            client.transport,
            "request_with_cache_headers",
            side_effect=requests.ConnectionError("offline"),
        ):
            self.assertEqual(cache.fetch(url, require_fresh=False, force=True), "cached")

    def test_strict_304_revalidates_expired_cached_content(self):
        url = "https://example.test/data.json"
        self._write_cache(url, age_seconds=settings.LOCAL_CACHE_TTL_SECONDS + 1)
        response = FakeResponse(status_code=304, headers={"ETag": '"fixture"'})
        with patch.object(client.transport, "request_with_cache_headers", return_value=response):
            self.assertEqual(cache.fetch(url, require_fresh=True), "cached")

        meta = cache.get_fetch_meta(url)
        self.assertEqual(meta["fetch_status"], "fresh")
        self.assertFalse(meta["used_cache_fallback"])
        self.assertTrue(meta["validated_in_run"])


    def test_text_cache_ttl_is_48_hours(self):
        self.assertEqual(settings.LOCAL_CACHE_TTL_SECONDS, 48 * 60 * 60)

    def test_strict_fetch_reuses_cache_within_48_hours_without_network(self):
        url = "https://example.test/data.json"
        self._write_cache(url, age_seconds=47 * 60 * 60 + 59 * 60)

        with patch.object(client.transport, "request_with_cache_headers") as request_mock:
            self.assertEqual(cache.fetch(url, require_fresh=True), "cached")

        request_mock.assert_not_called()
        self.assertTrue(cache.get_fetch_meta(url)["validated_in_run"])

    def test_strict_fetch_revalidates_once_48_hour_ttl_expires(self):
        url = "https://example.test/data.json"
        self._write_cache(url, age_seconds=settings.LOCAL_CACHE_TTL_SECONDS + 1)
        response = FakeResponse(status_code=304, headers={"ETag": '"fixture"'})

        with patch.object(client.transport, "request_with_cache_headers", return_value=response) as request_mock:
            self.assertEqual(cache.fetch(url, require_fresh=True), "cached")

        request_mock.assert_called_once()

    def test_strict_download_pic_reuses_cache_within_30_days_without_network(self):
        url = "https://example.test/image.png"
        relative_path = "cache/useitem/1.png"
        path = Path(settings.BASE_DIR) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cached-image")
        meta = {
            cache.cache_key(str(path)): {
                "url": url,
                "fetched_at": int(time.time()) - (29 * 24 * 3600),
                "etag": '"fixture-image"',
                "fetch_status": "fresh",
                "used_cache_fallback": False,
            }
        }
        Path(cache.meta_index_path()).write_text(json.dumps(meta), encoding="utf-8")

        with patch.object(client.transport, "request_with_cache_headers") as request_mock:
            actual = cache.download_pic(
                url=url,
                save_path=relative_path,
                require_fresh=True,
            )

        self.assertEqual(actual, str(path))
        request_mock.assert_not_called()
        self.assertTrue(cache.was_validated_in_run(url))

    def test_json_url_keeps_json_extension(self):
        path = cache.url_to_path("https://example.test/wiki/ship.json")
        self.assertTrue(path.endswith("ship.json"), path)

    def test_download_pic_uses_30_day_cache_ttl(self):
        with patch.object(client, "download_file", return_value="cached.png") as download_mock:
            actual = cache.download_pic(
                url="https://example.test/image.png",
                save_path="cache/useitem/1.png",
            )

        self.assertEqual(actual, "cached.png")
        download_mock.assert_called_once_with(
            url="https://example.test/image.png",
            save_path="cache/useitem/1.png",
            force=False,
            expire_seconds=30 * 24 * 3600,
            require_fresh=None,
        )

    def test_collection_completion_marker_is_process_local_and_resettable(self):
        self.assertFalse(cache.collection_completed_in_run("akashi-list"))
        cache.mark_collection_completed("akashi-list")
        self.assertTrue(cache.collection_completed_in_run("akashi-list"))
        cache.reset_fetch_audit()
        self.assertFalse(cache.collection_completed_in_run("akashi-list"))

    def test_transient_ssl_error_is_retried_and_then_succeeds(self):
        url = "https://example.test/data.json"
        response = FakeResponse(status_code=200, text="fresh")
        with patch.object(
            transport.requests,
            "get",
            side_effect=[requests.exceptions.SSLError("temporary eof"), response],
        ) as request_mock, patch.object(transport.time, "sleep") as sleep_mock, patch.object(
            transport.random, "uniform", return_value=0.0
        ):
            actual = cache.request_with_cache_headers(url, {}, 10, max_attempts=4)

        self.assertIs(actual, response)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(1.0)

    def test_retryable_http_status_is_retried(self):
        url = "https://example.test/data.json"
        overloaded = FakeResponse(status_code=503, headers={"Retry-After": "2"})
        overloaded.close = lambda: None
        response = FakeResponse(status_code=304)
        with patch.object(transport.requests, "get", side_effect=[overloaded, response]) as request_mock, patch.object(
            cache.time, "sleep"
        ) as sleep_mock:
            actual = cache.request_with_cache_headers(url, {}, 10, max_attempts=4)

        self.assertIs(actual, response)
        self.assertEqual(request_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2.0)

    def test_exhausted_transient_retries_raise_without_cache_fallback(self):
        url = "https://example.test/data.json"
        self._write_cache(url)
        with patch.object(
            transport.requests,
            "get",
            side_effect=requests.exceptions.SSLError("temporary eof"),
        ) as request_mock, patch.object(transport.time, "sleep"), patch.object(
            transport.random, "uniform", return_value=0.0
        ):
            with self.assertRaisesRegex(RuntimeError, "fresh fetch required"):
                cache.fetch(url, require_fresh=True, force=True)

        self.assertEqual(request_mock.call_count, cache.NETWORK_MAX_ATTEMPTS)
        self.assertFalse(cache.get_fetch_meta(url)["validated_in_run"])


if __name__ == "__main__":
    unittest.main()

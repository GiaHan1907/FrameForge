"""Unit tests for the additional license-aware image sources and crop.

Covers the search backends added on top of DuckDuckGo (Wikimedia Commons,
Openverse, Pexels, Pixabay, Unsplash) plus the crop_ratio / sources.tsv
download path.  Network is fully mocked; no real HTTP happens.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.google_images import (
    CROP_RATIOS,
    ImageResult,
    _resolve_crop,
    _strip_html,
    download_results,
    search_images,
)


def _resp(payload, error=None):
    m = Mock()
    m.json.return_value = payload
    m.text = ""
    if error is not None:
        m.raise_for_status.side_effect = error
    return m


def _patched_get(payload):
    return patch("core.google_images.requests.get", return_value=_resp(payload))


class WikimediaParseTests(unittest.TestCase):
    def test_parses_pages_and_license(self):
        payload = {
            "query": {
                "pages": {
                    "1": {
                        "title": "File:Hanoi, Vietnam, Hoan Kiem Lake.jpg",
                        "imageinfo": [{
                            "url": "https://upload.wikimedia.org/wikipedia/commons/a/a1/HK.jpg",
                            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/HK.jpg/400px-HK.jpg",
                            "width": 3984, "height": 2656, "mime": "image/jpeg",
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY 4.0"},
                                "Artist": {"value": '<a href="//x">Vyacheslav Argenberg</a>'},
                            },
                        }],
                    }
                }
            }
        }
        from core.google_images import _wikimedia_search_images
        with _patched_get(payload):
            results = _wikimedia_search_images("Hoan Kiem", num_results=5)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["license"], "CC BY 4.0")
        self.assertEqual(r["author"], "Vyacheslav Argenberg")
        self.assertEqual(r["title"], "Hanoi, Vietnam, Hoan Kiem Lake.jpg")
        self.assertTrue(r["page_url"].startswith("https://commons.wikimedia.org/wiki/"))

    def test_skips_non_image_mime(self):
        payload = {
            "query": {
                "pages": {
                    "1": {"title": "File:Doc.pdf",
                          "imageinfo": [{"url": "https://upload/x.pdf", "mime": "application/pdf"}]},
                    "2": {"title": "File:Photo.jpg",
                          "imageinfo": [{"url": "https://upload/y.jpg", "mime": "image/jpeg",
                                         "width": 100, "height": 50}]},
                }
            }
        }
        from core.google_images import _wikimedia_search_images
        with _patched_get(payload):
            results = _wikimedia_search_images("test", num_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://upload/y.jpg")

    def test_network_error_returns_empty(self):
        import requests
        from core.google_images import _wikimedia_search_images
        with patch("core.google_images.requests.get",
                   side_effect=requests.RequestException("boom")):
            self.assertEqual(_wikimedia_search_images("x"), [])



class KeyedSourceParseTests(unittest.TestCase):
    def test_openverse_parse_and_token(self):
        from core.google_images import _openverse_search_images
        payload = {"results": [{
            "title": "Hoan Kiem", "url": "https://cdn.openverse.org/1.jpg",
            "thumbnail": "https://cdn.openverse.org/1_t.jpg",
            "license": "by-nc-sa", "license_version": "4.0",
            "creator": "Someone", "source": "flickr",
            "width": 100, "height": 200,
        }]}
        with patch("core.google_images.requests.get", return_value=_resp(payload)) as get_mock:
            results = _openverse_search_images("Hoan Kiem", num_results=5, token="tok-123")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["license"], "by-nc-sa 4.0")
        self.assertEqual(results[0]["author"], "Someone")
        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Token tok-123")
        self.assertEqual(kwargs["params"]["per_page"], 5)

    def test_openverse_no_token_no_auth_header(self):
        from core.google_images import _openverse_search_images
        with patch("core.google_images.requests.get", return_value=_resp({"results": []})) as get_mock:
            self.assertEqual(_openverse_search_images("q", token=""), [])
        _, kwargs = get_mock.call_args
        self.assertNotIn("Authorization", kwargs["headers"])

    def test_pexels_requires_key(self):
        from core.google_images import _pexels_search_images
        self.assertEqual(_pexels_search_images("q", api_key=""), [])

    def test_pixabay_requires_key(self):
        from core.google_images import _pixabay_search_images
        self.assertEqual(_pixabay_search_images("q", api_key=""), [])

    def test_unsplash_requires_key(self):
        from core.google_images import _unsplash_search_images
        self.assertEqual(_unsplash_search_images("q", api_key=""), [])

    def test_pexels_parse_with_key(self):
        from core.google_images import _pexels_search_images
        payload = {"photos": [{
            "src": {"original": "https://images.pexels.com/1.jpg",
                    "medium": "https://images.pexels.com/1_m.jpg",
                    "large2x": "https://images.pexels.com/1_l.jpg"},
            "alt": "a lake", "photographer": "Jane", "url": "https://www.pexels.com/photo/1",
            "width": 640, "height": 480,
        }]}
        with patch("core.google_images.requests.get", return_value=_resp(payload)) as get_mock:
            results = _pexels_search_images("lake", api_key="k")
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["author"], "Jane")
        self.assertIn("Pexels", r["license"])
        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "k")

    def test_unsplash_parse_with_key(self):
        from core.google_images import _unsplash_search_images
        payload = {"results": [{
            "urls": {"full": "https://images.unsplash.com/1", "thumb": "https://images.unsplash.com/1_t"},
            "alt_description": "lake view", "width": 300, "height": 400,
            "user": {"name": "Bob"}, "links": {"html": "https://unsplash.com/photos/1"},
        }]}
        with patch("core.google_images.requests.get", return_value=_resp(payload)) as get_mock:
            results = _unsplash_search_images("lake", api_key="k")
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["author"], "Bob")
        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Client-ID k")

    def test_pixabay_parse_with_key(self):
        from core.google_images import _pixabay_search_images
        payload = {"hits": [{
            "largeImageURL": "https://cdn.pixabay.com/1.jpg", "webformatURL": "https://cdn.pixabay.com/1_w.jpg",
            "tags": "lake, tree", "user": "Carol", "pageURL": "https://pixabay.com/photo/1",
            "imageWidth": 800, "imageHeight": 600,
        }]}
        with patch("core.google_images.requests.get", return_value=_resp(payload)) as get_mock:
            results = _pixabay_search_images("lake", api_key="k")
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["author"], "Carol")
        self.assertIn("Pixabay", r["license"])
        _, kwargs = get_mock.call_args
        self.assertEqual(kwargs["params"]["key"], "k")



class AuthRejectionTests(unittest.TestCase):
    """401/403 = rejected API key -> ImageSearchAuthError; other failures -> []."""

    @staticmethod
    def _http_error(status):
        import requests

        return requests.HTTPError(f"HTTP {status}", response=Mock(status_code=status))

    def _expect_auth_error(self, backend, status, **kwargs):
        from core.google_images import ImageSearchAuthError

        with patch("core.google_images.requests.get",
                   return_value=_resp({}, error=self._http_error(status))):
            with self.assertRaises(ImageSearchAuthError) as ctx:
                backend("q", **kwargs)
        self.assertEqual(ctx.exception.status, status)
        return ctx.exception

    def test_pexels_401_raises_auth_error(self):
        from core.google_images import _pexels_search_images

        exc = self._expect_auth_error(_pexels_search_images, 401, api_key="k")
        self.assertEqual(exc.source, "pexels")

    def test_pexels_403_raises_auth_error(self):
        from core.google_images import _pexels_search_images

        self._expect_auth_error(_pexels_search_images, 403, api_key="k")

    def test_pixabay_401_raises_auth_error(self):
        from core.google_images import _pixabay_search_images

        self._expect_auth_error(_pixabay_search_images, 401, api_key="k")

    def test_unsplash_401_raises_auth_error(self):
        from core.google_images import _unsplash_search_images

        self._expect_auth_error(_unsplash_search_images, 401, api_key="k")

    def test_openverse_bad_token_401_raises_auth_error(self):
        from core.google_images import _openverse_search_images

        self._expect_auth_error(_openverse_search_images, 401, token="bad-token")

    def test_rate_limit_and_5xx_still_return_empty(self):
        from core.google_images import _pexels_search_images

        for status in (429, 500, 503):
            with self.subTest(status=status):
                with patch("core.google_images.requests.get",
                           return_value=_resp({}, error=self._http_error(status))):
                    self.assertEqual(_pexels_search_images("q", api_key="k"), [])

    def test_network_error_still_returns_empty(self):
        import requests

        from core.google_images import _pexels_search_images

        with patch("core.google_images.requests.get",
                   side_effect=requests.ConnectionError("down")):
            self.assertEqual(_pexels_search_images("q", api_key="k"), [])

    def test_dispatch_propagates_auth_error(self):
        from core.google_images import ImageSearchAuthError

        with patch("core.google_images._pexels_search_images",
                   side_effect=ImageSearchAuthError("pexels", 401)):
            with self.assertRaises(ImageSearchAuthError):
                search_images("q", source="pexels", api_keys={"pexels": "k"})


class ValidateApiKeyTests(unittest.TestCase):
    """validate_api_key reuses the backend fetch path: 401/403 raise, all else
    returns normally (a 200/4xx-other response means the key was accepted)."""

    def test_valid_key_returns_normally_and_uses_the_typed_key(self):
        from core.google_images import validate_api_key

        with patch("core.google_images._pexels_search_images", return_value=[]) as backend:
            validate_api_key("pexels", "GOOD-KEY")
        # the typed key went through the real dispatcher, not a new probe
        backend.assert_called_once_with("", 1, "GOOD-KEY")

    def test_rejected_key_raises_auth_error(self):
        from core.google_images import ImageSearchAuthError, validate_api_key

        with patch("core.google_images._pexels_search_images",
                   side_effect=ImageSearchAuthError("pexels", 401)):
            with self.assertRaises(ImageSearchAuthError) as ctx:
                validate_api_key("pexels", "BAD-KEY")
        self.assertEqual(ctx.exception.source, "pexels")

    def test_non_auth_failure_is_not_a_rejection(self):
        # network/rate-limit degrade to [] inside the backend - the provider
        # accepted the key, so validation must NOT raise.
        from core.google_images import validate_api_key

        with patch("core.google_images._pexels_search_images", return_value=[]):
            validate_api_key("pexels", "KEY")  # must not raise


class DispatcherTests(unittest.TestCase):
    def test_dispatcher_routes_wikimedia(self):
        with patch("core.google_images._wikimedia_search_images", return_value=[{
            "url": "https://upload.wikimedia.org/1.jpg", "license": "CC BY 4.0",
        }]):
            results = search_images("Hoan Kiem", num_results=3, source="wikimedia")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].license, "CC BY 4.0")

    def test_dispatcher_default_is_duckduckgo(self):
        with patch("core.google_images.search_google_images",
                   return_value=[ImageResult(url="https://ddg.example/1.jpg")]) as ddg:
            results = search_images("Hoan Kiem", num_results=3)
        ddg.assert_called_once_with("Hoan Kiem", 3)
        self.assertEqual(len(results), 1)

    def test_dispatcher_keyed_source_uses_api_keys(self):
        with patch("core.google_images._pexels_search_images", return_value=[]) as px:
            search_images("Hoan Kiem", source="pexels", api_keys={"pexels": "KEY"})
        px.assert_called_once_with("Hoan Kiem", 20, "KEY")

    def test_dispatcher_reads_env_key(self):
        import os
        with patch.dict(os.environ, {"FRAMEFORGE_UNSPLASH_ACCESS_KEY": "ENVKEY"}, clear=False):
            with patch("core.google_images._unsplash_search_images", return_value=[]) as unsplash:
                search_images("Hoan Kiem", source="unsplash")
        unsplash.assert_called_once_with("Hoan Kiem", 20, "ENVKEY")

    def test_unknown_source_falls_back_to_ddg(self):
        with patch("core.google_images.search_google_images", return_value=[]) as ddg:
            search_images("q", source="not-a-source")
        ddg.assert_called_once_with("q", 20)


class CropHelperTests(unittest.TestCase):
    def test_resolve_crop_maps_presets(self):
        self.assertEqual(_resolve_crop("1:1"), (1, 1))
        self.assertEqual(_resolve_crop("16:9"), (16, 9))
        self.assertEqual(_resolve_crop("9:16"), (9, 16))
        self.assertEqual(_resolve_crop("original"), None)
        self.assertEqual(_resolve_crop(None), None)
        self.assertEqual(_resolve_crop((4, 5)), (4, 5))
        self.assertEqual(_resolve_crop("  3:2  "), (3, 2))
        self.assertEqual(_resolve_crop("bogus"), None)

    def test_strip_html_removes_tags(self):
        self.assertEqual(_strip_html('<a href="//x">Jane</a>'), "Jane")
        self.assertEqual(_strip_html("plain text"), "plain text")
        self.assertEqual(_strip_html(""), "")


class CropBoxTests(unittest.TestCase):
    """Verify center-crop box math with a fake PIL (no Pillow installed here)."""

    def _make_fake_pil(self, width, height, calls):
        import sys
        from types import SimpleNamespace

        class FakeImageFile:
            def __init__(self, source):
                self._source = source

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def load(self):
                return None

            @property
            def size(self):
                return (width, height)

            def crop(self, box):
                calls["box"] = box
                return SimpleNamespace(save=lambda *a, **k: calls.setdefault("saved", True))

        class FakeImageModule:
            @staticmethod
            def open(source):
                return FakeImageFile(source)

        class FakeImageOps:
            @staticmethod
            def exif_transpose(img):
                return img

        return {
            "PIL": SimpleNamespace(Image=FakeImageModule, ImageOps=FakeImageOps),
            "PIL.Image": FakeImageModule,
            "PIL.ImageOps": FakeImageOps,
        }

    def _run_crop(self, width, height, ratio_key):
        import sys
        calls = {}
        fakes = self._make_fake_pil(width, height, calls)
        with patch.dict(sys.modules, fakes):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "test.jpg"
                path.write_bytes(b"fake")
                from core.google_images import CROP_RATIOS, _crop_image_file
                _crop_image_file(path, CROP_RATIOS[ratio_key])
        return calls

    def test_landscape_crops_sides_for_square(self):
        # 400x200 -> 1:1 means 200x200, centered horizontally
        calls = self._run_crop(400, 200, "1:1")
        self.assertEqual(calls.get("box"), (100, 0, 300, 200))
        self.assertTrue(calls.get("saved"))

    def test_portrait_crops_top_bottom_for_square(self):
        # 200x400 -> 1:1 means 200x200, centered vertically
        calls = self._run_crop(200, 400, "1:1")
        self.assertEqual(calls.get("box"), (0, 100, 200, 300))

    def test_wide_crops_sides_for_9x16(self):
        # 1600x900 -> 9:16 needs portrait; height limits -> 506x900
        calls = self._run_crop(1600, 900, "9:16")
        box = calls.get("box")
        self.assertIsNotNone(box)
        self.assertEqual(box[2] - box[0], 506)
        self.assertEqual(box[3] - box[1], 900)


class DownloadResultsTests(unittest.TestCase):
    def _fake_download(self, url, save_dir, filename=None, crop_ratio=None):
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / ("img_" + url.split("/")[-1])
        path.write_bytes(b"fake-image-bytes")
        return path

    def test_sources_tsv_written_when_license_present(self):
        results = [
            ImageResult(url="https://upload.wikimedia.org/a.jpg", title="A",
                        license="CC BY 4.0", author="Author A",
                        page_url="https://commons.wikimedia.org/wiki/File:A.jpg"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.google_images.download_image", side_effect=self._fake_download):
                outcome = download_results(results, tmp, delay=0)
            self.assertEqual(len(outcome["paths"]), 1)
            self.assertIsNotNone(outcome["sources_file"])
            content = Path(tmp, "sources.tsv").read_text(encoding="utf-8")
            self.assertIn("CC BY 4.0", content)
            self.assertIn("Author A", content)
            self.assertIn("a.jpg", content)
            self.assertIn("https://upload.wikimedia.org/a.jpg", content)

    def test_no_sidecar_without_metadata(self):
        results = [ImageResult(url="https://ddg.example/x.jpg", title="X")]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.google_images.download_image", side_effect=self._fake_download):
                outcome = download_results(results, tmp, delay=0)
            self.assertEqual(len(outcome["paths"]), 1)
            self.assertIsNone(outcome["sources_file"])
            self.assertFalse(Path(tmp, "sources.tsv").exists())

    def test_failed_downloads_reported(self):
        results = [ImageResult(url="https://broken.example/a.jpg")]
        with tempfile.TemporaryDirectory() as tmp:
            def boom(url, save_dir, filename=None, crop_ratio=None):
                raise RuntimeError("403")
            with patch("core.google_images.download_image", side_effect=boom):
                outcome = download_results(results, tmp, delay=0)
            self.assertEqual(outcome["paths"], [])
            self.assertEqual(len(outcome["failed"]), 1)
            self.assertIn("403", outcome["failed"][0])

class DownloadRetryTests(unittest.TestCase):
    """download_image retries HTTP 429 / 5xx / network errors with backoff."""

    def _make_resp(self, status=200, body=b"img", retry_after=None):
        import requests

        resp = Mock()
        resp.status_code = status
        resp.headers = {}
        if retry_after is not None:
            resp.headers["Retry-After"] = str(retry_after)
        resp.iter_content.return_value = iter([body])

        def do_raise():
            error = requests.HTTPError(str(status), response=resp)
            raise error

        if status >= 400:
            resp.raise_for_status.side_effect = do_raise
        return resp

    def _run(self, responses, max_retries=2, retry_delays=(2.0, 5.0), check=None):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.google_images.requests.get", side_effect=responses) as get_mock:
                with patch("core.google_images.time.sleep") as sleep_mock:
                    from core.google_images import download_image

                    path = download_image(
                        "https://cdn.example/a.jpg", tmp,
                        max_retries=max_retries,
                        retry_delays=retry_delays,
                    )
                    if check is not None:
                        check(path, get_mock, sleep_mock)
    def test_429_then_success_retries_and_saves(self):
        def check(path, get_mock, sleep_mock):
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b"img")
            self.assertEqual(get_mock.call_count, 2)
            sleep_mock.assert_called_once_with(2.0)

        self._run([self._make_resp(429), self._make_resp(200)], check=check)
    def test_two_500_then_success_backoff_escalates(self):
        def check(path, get_mock, sleep_mock):
            self.assertTrue(path.exists())
            self.assertEqual(get_mock.call_count, 3)
            self.assertEqual(sleep_mock.call_args_list[0].args, (2.0,))
            self.assertEqual(sleep_mock.call_args_list[1].args, (5.0,))

        self._run(
            [self._make_resp(500), self._make_resp(503), self._make_resp(200)],
            check=check,
        )
    def test_permanent_404_fails_immediately(self):
        import requests
        import tempfile

        with self.assertRaises(requests.HTTPError):
            with tempfile.TemporaryDirectory() as tmp:
                with patch("core.google_images.requests.get",
                           return_value=self._make_resp(404)) as get_mock:
                    with patch("core.google_images.time.sleep") as sleep_mock:
                        from core.google_images import download_image

                        download_image("https://cdn.example/gone.jpg", tmp)
        self.assertEqual(get_mock.call_count, 1)
        sleep_mock.assert_not_called()
    def test_persistent_429_raises_after_max_retries(self):
        import requests
        import tempfile

        with self.assertRaises(requests.HTTPError):
            with tempfile.TemporaryDirectory() as tmp:
                with patch("core.google_images.requests.get",
                           return_value=self._make_resp(429)) as get_mock:
                    with patch("core.google_images.time.sleep"):
                        from core.google_images import download_image

                        download_image(
                            "https://cdn.example/busy.jpg", tmp, max_retries=1,
                            retry_delays=(2.0,),
                        )
        self.assertEqual(get_mock.call_count, 2)

    def test_network_error_then_success_retries(self):
        import requests

        network_error = requests.ConnectionError("reset")

        def check(path, get_mock, sleep_mock):
            self.assertTrue(path.exists())
            self.assertEqual(get_mock.call_count, 2)
            sleep_mock.assert_called_once_with(2.0)

        self._run([network_error, self._make_resp(200)], check=check)
    def test_retry_after_header_overrides_delay(self):
        def check(path, get_mock, sleep_mock):
            self.assertTrue(path.exists())
            sleep_mock.assert_called_once_with(12.0)

        self._run(
            [self._make_resp(429, retry_after=12), self._make_resp(200)],
            check=check,
        )
    def test_persistent_network_error_raises(self):
        import requests
        import tempfile

        with self.assertRaises(requests.ConnectionError):
            with tempfile.TemporaryDirectory() as tmp:
                with patch("core.google_images.requests.get",
                           side_effect=requests.ConnectionError("down")) as get_mock:
                    with patch("core.google_images.time.sleep"):
                        from core.google_images import download_image

                        download_image(
                            "https://cdn.example/down.jpg", tmp, max_retries=2,
                            retry_delays=(1.0, 1.0),
                        )
        self.assertEqual(get_mock.call_count, 3)



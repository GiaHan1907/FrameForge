"""Unit tests for core/google_images.py search backends (network mocked).

Guards the 0-results regression that shipped in an earlier build: Google
Images returns a JS-required page to plain scrapers, so DuckDuckGo Images
is the primary engine and the legacy Google parser is the fallback.  These
tests pin down that behaviour with mocked HTTP so no real network is hit:

* _ddg_search_images parses i.js JSON, dedupes, caps and paginates;
* blocked pages (no vqd token), network errors and bad JSON yield an
  empty list instead of a crash;
* search_google_images prefers DDG results and falls back to the legacy
  Google parser only when DDG comes back empty.
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import requests

from core.google_images import (
    ImageResult,
    _ddg_search_images,
    search_google_images,
)


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, text="", payload=None, error=None, json_error=None):
        self._text = text
        self._payload = payload
        self._error = error
        self._json_error = json_error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    @property
    def text(self):
        return self._text

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def make_session(*responses):
    """Mock requests.Session whose get() returns the responses in order."""
    session = Mock()
    session.get.side_effect = list(responses)
    return session


def ddg_item(url, n=1, title="Hoan Kiem", thumb=None):
    """One DuckDuckGo i.js result dict with the url repeated n times."""
    items = []
    for i in range(n):
        items.append({
            "image": url,
            "title": "  " + title + " " + str(i) + "  ",
            "thumbnail": thumb or (url + "_t"),
            "url": "https://source.example/page/" + str(i),
            "width": 640,
            "height": 480,
        })
    return items


VQD_HTML = "<html><body>window.vqd=123-456 stored</body></html>"


def patch_net(session):
    """Patches that make _ddg_search_images deterministic and offline."""
    return [
        patch("core.google_images.requests.Session", return_value=session),
        patch("core.google_images.time.sleep"),
        patch("core.google_images.random.uniform", return_value=1.0),
        patch("core.google_images.random.choice", return_value="UA-Test"),
    ]

class TestDdgSearchBackend(unittest.TestCase):
    """_ddg_search_images with mocked Session."""

    def run_ddg(self, session, query="Hoan Kiem", num=5):
        with ExitStack() as stack:
            for patcher in patch_net(session):
                stack.enter_context(patcher)
            return _ddg_search_images(query, num_results=num)

    def test_parses_json_and_maps_fields(self):
        data = {"results": ddg_item("https://cdn.example/a.jpg", n=1), "next": ""}
        session = make_session(FakeResponse(text=VQD_HTML), FakeResponse(payload=data))
        results = self.run_ddg(session)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["url"], "https://cdn.example/a.jpg")
        self.assertEqual(item["title"], "Hoan Kiem 0")
        self.assertEqual(item["thumbnail"], "https://cdn.example/a.jpg_t")
        self.assertEqual(item["source"], "https://source.example/page/0")
        self.assertEqual(item["width"], 640)
        self.assertEqual(item["height"], 480)

    def test_missing_vqd_returns_empty(self):
        # Regression: DDG changing its page shape (or blocking us) means no
        # vqd token. Must yield [] - never a crash or a partial garbage list.
        session = make_session(FakeResponse(text="<html>no token here</html>"))
        self.assertEqual(self.run_ddg(session), [])

    def test_page_request_error_returns_empty(self):
        session = make_session(FakeResponse(error=requests.RequestException("blocked")))
        self.assertEqual(self.run_ddg(session), [])

    def test_json_request_error_returns_empty(self):
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(error=requests.RequestException("timeout")),
        )
        self.assertEqual(self.run_ddg(session), [])

    def test_invalid_json_returns_empty(self):
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(json_error=ValueError("not json")),
        )
        self.assertEqual(self.run_ddg(session), [])

    def test_dedupes_duplicate_image_urls(self):
        items = ddg_item("https://cdn.example/dup.jpg", n=2)
        items += ddg_item("https://cdn.example/unique1.jpg", n=1)
        items += ddg_item("https://cdn.example/unique2.jpg", n=1)
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(payload={"results": items, "next": ""}),
        )
        results = self.run_ddg(session, num=10)
        urls = [r["url"] for r in results]
        self.assertEqual(len(results), 3)
        self.assertEqual(len(set(urls)), len(urls))

    def test_truncates_at_num_results(self):
        items = [ddg_item("https://cdn.example/i%d.jpg" % i, n=1)[0] for i in range(5)]
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(payload={"results": items, "next": ""}),
        )
        results = self.run_ddg(session, num=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["url"], "https://cdn.example/i0.jpg")

    def test_paginates_until_num_results_reached(self):
        # Page 1: u1, u2.  Page 2: u2 (dup), u3, u4.  Page 3: u4 (dup), u5, u6.
        pages = [
            {"results": ddg_item("https://cdn.example/u1.jpg") + ddg_item("https://cdn.example/u2.jpg"),
             "next": "https://duckduckgo.com/i.js?q=hoan&s=100"},
            {"results": ddg_item("https://cdn.example/u2.jpg") + ddg_item("https://cdn.example/u3.jpg")
             + ddg_item("https://cdn.example/u4.jpg"),
             "next": "https://duckduckgo.com/i.js?q=hoan&s=200"},
            {"results": ddg_item("https://cdn.example/u4.jpg") + ddg_item("https://cdn.example/u5.jpg")
             + ddg_item("https://cdn.example/u6.jpg"),
             "next": ""},
        ]
        session = make_session(
            FakeResponse(text=VQD_HTML),
            *(FakeResponse(payload=pg) for pg in pages),
        )
        with ExitStack() as stack:
            for patcher in patch_net(session):
                stack.enter_context(patcher)
            sleep_mock = stack.enter_context(patch("core.google_images.time.sleep"))
            results = _ddg_search_images("Hoan Kiem", num_results=6)

        self.assertEqual(len(results), 6)
        urls = [r["url"] for r in results]
        self.assertEqual(len(set(urls)), 6)  # cross-page dedupe
        self.assertEqual(session.get.call_count, 4)  # 1 page + 3 i.js
        self.assertEqual(sleep_mock.call_count, 2)  # between the 3 i.js calls

    def test_stops_when_no_more_pages(self):
        # One page, next has no s= -> single fetch, no sleep.
        data = {"results": ddg_item("https://cdn.example/only.jpg"), "next": ""}
        session = make_session(FakeResponse(text=VQD_HTML), FakeResponse(payload=data))
        with ExitStack() as stack:
            for patcher in patch_net(session):
                stack.enter_context(patcher)
            sleep_mock = stack.enter_context(patch("core.google_images.time.sleep"))
            results = _ddg_search_images("Hoan Kiem", num_results=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(session.get.call_count, 2)
        sleep_mock.assert_not_called()

    def test_region_lang_adds_l_param(self):
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(payload={"results": ddg_item("https://cdn.example/x.jpg"), "next": ""}),
        )
        with ExitStack() as stack:
            for patcher in patch_net(session):
                stack.enter_context(patcher)
            _ddg_search_images("Hoan Kiem", num_results=5, lang="en-US")
        _, second_kwargs = session.get.call_args_list[1]
        self.assertEqual(second_kwargs["params"]["l"], "en-US")
        self.assertEqual(second_kwargs["params"]["vqd"], "123-456")
        self.assertEqual(second_kwargs["headers"]["Referer"], "https://duckduckgo.com/")

    def test_plain_lang_omits_l_param(self):
        session = make_session(
            FakeResponse(text=VQD_HTML),
            FakeResponse(payload={"results": ddg_item("https://cdn.example/x.jpg"), "next": ""}),
        )
        with ExitStack() as stack:
            for patcher in patch_net(session):
                stack.enter_context(patcher)
            _ddg_search_images("Hoan Kiem", num_results=5, lang="vi")
        _, second_kwargs = session.get.call_args_list[1]
        self.assertNotIn("l", second_kwargs["params"])

class TestSearchGoogleImages(unittest.TestCase):
    """search_google_images fallback order: DDG first, legacy Google second."""

    def test_prefers_ddg_results_over_legacy(self):
        ddg_dicts = [
            {"url": "https://cdn.example/d1.jpg", "title": "First", "source": "https://src.example/1",
             "width": 100, "height": 200, "thumbnail": "https://cdn.example/d1_t.jpg"},
            {"url": "https://cdn.example/d2.jpg", "title": "Second", "source": "https://src.example/2",
             "width": 300, "height": 400, "thumbnail": "https://cdn.example/d2_t.jpg"},
        ]
        with patch("core.google_images._ddg_search_images", return_value=ddg_dicts) as ddg_mock:
            with patch("core.google_images._search_google_images_legacy",
                       side_effect=AssertionError("legacy must not run when DDG has results")) as legacy_mock:
                results = search_google_images("Hoan Kiem", num_results=5)

        ddg_mock.assert_called_once_with("Hoan Kiem", 5, "vi")
        legacy_mock.assert_not_called()
        self.assertEqual(len(results), 2)
        self.assertIsInstance(results[0], ImageResult)
        self.assertEqual(results[0].url, "https://cdn.example/d1.jpg")
        self.assertEqual(results[0].thumbnail, "https://cdn.example/d1_t.jpg")
        self.assertEqual(results[1].source, "https://src.example/2")
        self.assertEqual(results[1].height, 400)

    def test_falls_back_to_legacy_when_ddg_empty(self):
        legacy_result = ImageResult(
            url="https://legacy.example/g.jpg", title="Old parser", thumbnail="https://legacy.example/g_t.jpg"
        )
        with patch("core.google_images._ddg_search_images", return_value=[]) as ddg_mock:
            with patch("core.google_images._search_google_images_legacy",
                       return_value=[legacy_result]) as legacy_mock:
                results = search_google_images("Ben Thanh", num_results=3)

        ddg_mock.assert_called_once_with("Ben Thanh", 3, "vi")
        legacy_mock.assert_called_once_with("Ben Thanh", 3, "vi", "active")
        self.assertEqual(results, [legacy_result])

    def test_ddg_network_failure_falls_back_to_legacy(self):
        # A network failure inside the DDG engine is caught there and yields
        # [], so search must fall back to the legacy Google parser instead of
        # crashing the UI with zero results and no explanation.
        legacy_result = ImageResult(url="https://legacy.example/safe.jpg", title="Safe")
        session = make_session(FakeResponse(error=requests.RequestException("dns fail")))
        with patch("core.google_images.requests.Session", return_value=session):
            with patch("core.google_images._search_google_images_legacy",
                       return_value=[legacy_result]):
                results = search_google_images("Anywhere")
        self.assertEqual(results, [legacy_result])

    def test_returns_empty_when_both_backends_empty(self):
        with patch("core.google_images._ddg_search_images", return_value=[]):
            with patch("core.google_images._search_google_images_legacy", return_value=[]):
                results = search_google_images("Nowhere")
        self.assertEqual(results, [])

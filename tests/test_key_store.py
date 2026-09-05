"""Tests for the persistent encrypted API-key store (core/key_store.py).

key_store owns BOTH the storage and the resolution rule (explicit argument >
FRAMEFORGE_* env var > stored value) consumed by core/google_images.py and
ui/image_search_inline.py, so those callers never re-derive precedence.
No real network or user config is touched - every test uses a temporary
directory.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import google_images, key_store
from core.key_store import STORAGE_FILENAME, ApiKeyStore

# Neutralize only the FRAMEFORGE_* vars (NOT the whole environment): wiping
# every var breaks Streamlit AppTest, whose first config resolution calls
# Path.home() and dies when USERPROFILE/HOME are gone.
_FRAMEFORGE_ENV_OFF = {name: "" for name in key_store.ENV_NAMES.values()}


def _search_widget_script() -> str:
    """AppTest script that renders the inline image-search widget."""
    root = repr(str(Path(__file__).resolve().parents[1]))
    return (
        "import sys\n"
        f"sys.path.insert(0, {root})\n"
        "from ui.image_search_inline import render_inline_image_search\n"
        "render_inline_image_search()\n"
    )


def _settings_keys_script() -> str:
    """AppTest script that renders the settings-tab key management surface."""
    root = repr(str(Path(__file__).resolve().parents[1]))
    return (
        "import sys\n"
        f"sys.path.insert(0, {root})\n"
        "from ui.key_settings import render_settings_api_keys\n"
        "render_settings_api_keys()\n"
    )


def _select_pexels(at) -> None:
    """Switch the inline search widget to the Pexels source."""
    at.run()
    at.selectbox[0].select("Pexels")
    at.run()


def _type_query(at) -> None:
    next(t for t in at.text_input if t.label == "\u0110\u1ecba \u0111i\u1ec3m / keywords").input("Hoan Kiem")
    at.run()


def _click_search(at) -> None:
    """Click the T\u00ecm ki\u1ebfm button (by key - not index, other buttons
    such as Ki\u1ec3m tra key are created before it)."""
    next(b for b in at.button if b.key == "_inline_img_search_btn").click()
    at.run()


def _search_query(at) -> None:
    """Type a query and click T\u00ecm ki\u1ebfm in the widget."""
    _type_query(at)
    _click_search(at)


def _captions(at):
    return [c.value or "" for c in at.caption]


class KeyStoreRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ApiKeyStore(base_dir=Path(self._tmp.name))
        self.path = Path(self._tmp.name) / STORAGE_FILENAME

    def test_save_and_load_roundtrip(self):
        self.store.set("pexels", "PEXEL-123")
        self.assertEqual(self.store.get("pexels"), "PEXEL-123")
        self.assertTrue(self.path.exists())

    def test_reload_from_disk(self):
        self.store.set("pixabay", "PIXA-456")
        other = ApiKeyStore(base_dir=Path(self._tmp.name))
        self.assertEqual(other.get("pixabay"), "PIXA-456")

    def test_overwrite_updates_value(self):
        self.store.set("unsplash", "OLD")
        self.store.set("unsplash", "NEW")
        self.assertEqual(self.store.get("unsplash"), "NEW")

    def test_delete(self):
        self.store.set("pexels", "X")
        self.store.delete("pexels")
        self.assertEqual(self.store.get("pexels"), "")
        self.store.delete("pexels")  # second delete is a no-op
        self.assertFalse(self.path.exists())

    def test_empty_value_deletes_entry(self):
        self.store.set("pexels", "X")
        self.store.set("pexels", "   ")
        self.assertEqual(self.store.get("pexels"), "")
        self.assertFalse(self.path.exists())

    def test_unknown_source_returns_empty(self):
        self.assertEqual(self.store.get("nope"), "")

    def test_source_names_are_case_insensitive(self):
        self.store.set("Pexels", "K")
        self.assertEqual(self.store.get("pexels"), "K")

    def test_corrupt_file_degrades_gracefully(self):
        self.path.write_text("{definitely not json", encoding="utf-8")
        self.assertEqual(self.store.get("pexels"), "")

    def test_non_dict_file_degrades_gracefully(self):
        self.path.write_text('"just a string"', encoding="utf-8")
        self.assertEqual(self.store.get("pexels"), "")

    @unittest.skipUnless(sys.platform == "win32", "DPAPI encryption is Windows-only")
    def test_windows_file_contains_no_plaintext(self):
        self.store.set("pexels", "TOPSECRET-VALUE-123")
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("TOPSECRET-VALUE-123", raw)
        self.assertIn("dpapi-v1", raw)

    @unittest.skipIf(sys.platform == "win32", "POSIX permission bits are meaningless on Windows")
    def test_file_permissions_restricted(self):
        self.store.set("pexels", "K")
        mode = self.path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class ResolveApiKeyPrecedenceTests(unittest.TestCase):
    """key_store resolution (single owner): explicit > env var > store.

    The rule is pointed at an explicit store (``resolve_api_key(store=...)``
    or ``ApiKeyStore.resolve``) - never at the process-global default - so
    these tests need no default_store() patching.
    """

    def test_explicit_beats_env_and_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, {"FRAMEFORGE_PEXELS_API_KEY": "from-env"}, clear=False):
                res = key_store.resolve_api_key("pexels", explicit="from-explicit", store=store)
        self.assertEqual(res.value, "from-explicit")
        self.assertEqual(res.origin, "explicit")
        self.assertEqual(res.env_name, "")
        self.assertEqual(res.stored, "")

    def test_env_beats_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "from-store")  # env must win over the stored value
            with mock.patch.dict(os.environ, {"FRAMEFORGE_PEXELS_API_KEY": "from-env"}, clear=False):
                res = store.resolve("pexels")  # instance-method path
        self.assertEqual(res.value, "from-env")
        self.assertEqual(res.origin, "env")
        self.assertEqual(res.env_name, "FRAMEFORGE_PEXELS_API_KEY")
        self.assertTrue(res.from_env)

    def test_store_is_last_resort(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "from-store")
            with mock.patch.dict(os.environ, {}, clear=True):
                res = key_store.resolve_api_key("pexels", store=store)
        self.assertEqual(res.value, "from-store")
        self.assertEqual(res.origin, "store")
        self.assertEqual(res.stored, "from-store")
        self.assertFalse(res.from_env)

    def test_none_when_nothing_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, {}, clear=True):
                res = key_store.resolve_api_key("pexels", store=store)
        self.assertEqual(res.value, "")
        self.assertEqual(res.origin, "none")
        self.assertEqual(res.stored, "")

    def test_blank_explicit_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "stored")
            with mock.patch.dict(os.environ, {}, clear=True):
                res = key_store.resolve_api_key("pexels", explicit="   ", store=store)
        self.assertEqual(res.value, "stored")
        self.assertEqual(res.origin, "store")

    def test_unknown_source_has_no_env_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            res = key_store.resolve_api_key("duckduckgo", store=store)
        self.assertEqual(res.origin, "none")
        self.assertEqual(res.value, "")

    def test_injected_store_never_leaks_the_process_default(self):
        # Regression for the design seam: when a store is injected, the rule
        # must consult ONLY that store - a key sitting in default_store() has
        # to be invisible, or a row could claim stored=True from one store
        # while another is empty.
        with tempfile.TemporaryDirectory() as tmp:
            injected = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch("core.key_store.default_store") as default_mock:
                default_mock.return_value = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
                default_mock.return_value.set("pexels", "PROCESS-GLOBAL")
                with mock.patch.dict(os.environ, {}, clear=True):
                    res = key_store.resolve_api_key("pexels", store=injected)
            self.assertEqual(res.origin, "none")
            self.assertEqual(res.value, "")

    def test_module_helper_defaults_to_default_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "DEFAULT-STORE-KEY")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("core.key_store.default_store", return_value=store):
                    res = key_store.resolve_api_key("pexels")  # no store arg
        self.assertEqual(res.value, "DEFAULT-STORE-KEY")
        self.assertEqual(res.origin, "store")

    def test_search_images_uses_store_when_no_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pixabay", "STORED-KEY")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pixabay_search_images", return_value=[]) as px:
                        google_images.search_images("q", source="pixabay")
            px.assert_called_once_with("q", 20, "STORED-KEY")

    def test_explicit_still_beats_store_in_search_images(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("core.google_images._pexels_search_images", return_value=[]) as px:
                google_images.search_images("q", source="pexels", api_keys={"pexels": "EXPLICIT"})
            px.assert_called_once_with("q", 20, "EXPLICIT")


class StoredKeyRejectionTests(unittest.TestCase):
    """A rejected STORED key must surface distinctly, not as an empty search."""

    def test_stored_key_rejection_propagates_through_search_images(self):
        # Real store holds the key; no env/explicit -> engine resolves it from
        # the store, the backend rejects it (401), and the error propagates so
        # the UI can show a distinct message instead of "no images found".
        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "EXPIRED-KEY")
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch(
                        "core.google_images._pexels_search_images",
                        side_effect=google_images.ImageSearchAuthError("pexels", 401),
                    ) as px:
                        with self.assertRaises(google_images.ImageSearchAuthError) as ctx:
                            google_images.search_images("q", source="pexels")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(ctx.exception.source, "pexels")
        # prove the key that got rejected came from the store
        self.assertEqual(px.call_args.args[2], "EXPIRED-KEY")


class AuthErrorMessageTests(unittest.TestCase):
    """_auth_error_message names source + cause and hints where the key lives."""

    def test_session_key_suggests_retyping(self):
        from ui.image_search_inline import _auth_error_message

        msg = _auth_error_message("Unsplash", 401)
        self.assertIn("t\u1eeb ch\u1ed1i API key", msg)
        self.assertIn("ki\u1ec3m tra l\u1ea1i key", msg)
        self.assertIn("Nh\u1eadp l\u1ea1i key", msg)
        self.assertNotIn("L\u01b0u key tr\u00ean m\u00e1y", msg)

    def test_stored_key_hints_reenter(self):
        from ui.image_search_inline import _auth_error_message

        msg = _auth_error_message("Pexels", 401, stored=True)
        self.assertIn("L\u01b0u key tr\u00ean m\u00e1y", msg)
        self.assertIn("nh\u1eadp key m\u1edbi", msg)
        self.assertNotIn("bi\u1ebfn m\u00f4i tr\u01b0\u1eddng", msg)

    def test_env_key_names_env_var(self):
        from ui.image_search_inline import _auth_error_message

        msg = _auth_error_message("Pixabay", 403, used_env="FRAMEFORGE_PIXABAY_API_KEY")
        self.assertIn("FRAMEFORGE_PIXABAY_API_KEY", msg)
        self.assertIn("bi\u1ebfn m\u00f4i tr\u01b0\u1eddng", msg)
        self.assertNotIn("L\u01b0u key tr\u00ean m\u00e1y", msg)


class StoredKeyRejectionUiTests(unittest.TestCase):
    """Full UI flow (Streamlit AppTest): a rejected STORED key shows the
    distinct error + re-enter hint, and NOT the generic no-results info."""

    def test_ui_shows_distinct_auth_message_when_stored_key_rejected(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "EXPIRED-KEY")
            with mock.patch("core.key_store.default_store", return_value=store):
                with mock.patch(
                    "core.google_images._pexels_search_images",
                    side_effect=google_images.ImageSearchAuthError("pexels", 401),
                ):
                    at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                    at.run()
                    self.assertFalse(at.exception, f"render raised: {at.exception}")
                    _select_pexels(at)
                    self.assertFalse(at.exception, f"select raised: {at.exception}")
                    _type_query(at)
                    self.assertFalse(at.exception, f"query raised: {at.exception}")
                    _click_search(at)
            self.assertFalse(at.exception, f"search raised: {at.exception}")
            errors = [e.value for e in at.error]
            infos = [e.value for e in at.info]
            self.assertTrue(any("t\u1eeb ch\u1ed1i API key" in e for e in errors), errors)
            self.assertTrue(any("L\u01b0u key tr\u00ean m\u00e1y" in e for e in errors), errors)
            self.assertFalse(any("Kh\u00f4ng t\u00ecm th\u1ea5y \u1ea3nh" in e for e in infos), infos)


class SearchKeyRowsTests(unittest.TestCase):
    """Settings management surface rows (ui.logic.search_key_rows).

    Built on the owned resolution rule + ApiKeyStore only; plaintext keys
    never appear in a row.
    """

    def _rows(self, store, env=None):
        from ui.logic import search_key_rows

        # search_key_rows reads ONLY the injected store (resolve + get) - no
        # default_store() patching needed.
        with mock.patch.dict(os.environ, env or {}, clear=True):
            return search_key_rows(store)

    def test_all_six_sources_present(self):
        store = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
        rows = self._rows(store)
        self.assertEqual(len(rows), 6)
        sources = [r["source"] for r in rows]
        self.assertIn("pexels", sources)
        self.assertIn("unsplash", sources)
        self.assertIn("duckduckgo", sources)

    def test_no_key_sources_marked(self):
        store = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
        duck = next(r for r in self._rows(store) if r["source"] == "duckduckgo")
        self.assertFalse(duck["needs_key"])
        self.assertFalse(duck["stored"])

    def test_stored_key_roundtrip_and_delete_via_surface(self):
        store = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
        store.set("pexels", "MY-SECRET-KEY-42")
        row = next(r for r in self._rows(store) if r["source"] == "pexels")
        self.assertTrue(row["stored"])
        # masked: last 4 visible, full key never present
        self.assertTrue(row["stored_masked"].endswith("42"))
        self.assertNotIn("MY-SECRET-KEY-42", row["stored_masked"])
        # delete through the surface's store
        store.delete("pexels")
        row2 = next(r for r in self._rows(store) if r["source"] == "pexels")
        self.assertFalse(row2["stored"])
        self.assertEqual(row2["stored_masked"], "")

    def test_env_override_labeled_with_env_name(self):
        store = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
        store.set("pexels", "STORED-KEY")
        rows = self._rows(store, env={"FRAMEFORGE_PEXELS_API_KEY": "ENV-KEY"})
        row = next(r for r in rows if r["source"] == "pexels")
        self.assertTrue(row["env_override"])
        self.assertEqual(row["env_name"], "FRAMEFORGE_PEXELS_API_KEY")
        # the stored key is still reported (masked) so the user knows it is there
        self.assertTrue(row["stored"])
        # other sources are not marked as overridden
        pixabay = next(r for r in rows if r["source"] == "pixabay")
        self.assertFalse(pixabay["env_override"])

    def test_nothing_stored_no_env(self):
        store = ApiKeyStore(base_dir=Path(tempfile.mkdtemp()))
        row = next(r for r in self._rows(store) if r["source"] == "unsplash")
        self.assertFalse(row["stored"])
        self.assertFalse(row["env_override"])

    def test_mask_never_reveals_full_or_short_keys(self):
        from ui.logic import mask_key

        self.assertEqual(mask_key(""), "")
        self.assertEqual(mask_key("abcd"), "••••")  # too short to reveal anything
        self.assertNotIn("abcd", mask_key("abcd"))
        masked = mask_key("VERY-SECRET-1234")
        self.assertTrue(masked.endswith("1234"))
        self.assertNotIn("VERY-SECRET", masked)


class SettingsApiKeysUiTests(unittest.TestCase):
    """Settings management surface driven through Streamlit AppTest:
    masked display, env-override label, delete button removes the stored key.
    """

    def test_settings_panel_flow(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "PEXELS-FULL-SECRET-99")
            with mock.patch.dict(os.environ, {"FRAMEFORGE_PIXABAY_API_KEY": "PIX-ENV"}, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    at = AppTest.from_string(_settings_keys_script(), default_timeout=60)
                    at.run()
                    self.assertFalse(at.exception, f"render raised: {at.exception}")
                    # env override clearly labeled
                    marks = " ".join(m.value or "" for m in at.markdown)
                    self.assertIn("FRAMEFORGE_PIXABAY_API_KEY", marks)
                    # masked display: bullets present, full key never shown
                    self.assertIn("•", marks)
                    self.assertNotIn("PEXELS-FULL-SECRET-99", marks)
                    # delete is two-step: first click arms, confirm click deletes
                    arm_btn = next(b for b in at.button if b.key == "_settings_key_delete_pexels")
                    arm_btn.click()
                    at.run()
                    self.assertFalse(at.exception, f"arm raised: {at.exception}")
                    self.assertEqual(store.get("pexels"), "PEXELS-FULL-SECRET-99",
                                     "first click must NOT delete")
                    confirm_btn = next(
                        b for b in at.button if b.key == "_settings_key_delete_confirm_pexels"
                    )
                    confirm_btn.click()
                    at.run()
                    self.assertFalse(at.exception, f"delete raised: {at.exception}")
                    self.assertEqual(store.get("pexels"), "")


class TwoStepDeleteUiTests(unittest.TestCase):
    """No stored key may be lost by a single accidental click (settings tab)."""

    def _setup(self):
        from streamlit.testing.v1 import AppTest

        tmp = tempfile.TemporaryDirectory()
        store = ApiKeyStore(base_dir=Path(tmp.name))
        store.set("pexels", "TWO-STEP-SECRET")
        at = AppTest.from_string(_settings_keys_script(), default_timeout=60)
        return tmp, store, at

    def _key_button(self, at, suffix):
        return next(b for b in at.button if b.key == f"_settings_key_delete_{suffix}")

    def test_first_click_never_deletes(self):
        tmp, store, at = self._setup()
        with tmp:
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    at.run()
                    self._key_button(at, "pexels").click()
                    at.run()
                    # key still there after ONE click
                    self.assertEqual(store.get("pexels"), "TWO-STEP-SECRET")
                    # confirmation bar + Hủy are now visible
                    self.assertTrue(any(
                        b.key == "_settings_key_delete_confirm_pexels" for b in at.button
                    ))
                    self.assertTrue(any(
                        b.key == "_settings_key_delete_cancel_pexels" for b in at.button
                    ))
                    marks = " ".join(m.value or "" for m in at.markdown)
                    warnings = " ".join(w.value or "" for w in at.warning)
                    # confirm flow never reveals the full key
                    self.assertNotIn("TWO-STEP-SECRET", marks + warnings)
                    # cancel leaves the key and disarms
                    self._key_button(at, "cancel_pexels").click()
                    at.run()
                    self.assertEqual(store.get("pexels"), "TWO-STEP-SECRET")
                    self.assertTrue(any(
                        b.key == "_settings_key_delete_pexels" for b in at.button
                    ), "Xóa (first step) must be visible again after Hủy")

    def test_confirmation_click_deletes(self):
        tmp, store, at = self._setup()
        with tmp:
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    at.run()
                    self._key_button(at, "pexels").click()
                    at.run()
                    self._key_button(at, "confirm_pexels").click()
                    at.run()
                    self.assertEqual(store.get("pexels"), "", "confirm click must delete")
                    self.assertFalse(any(
                        "delete_confirm" in b.key or "delete_cancel" in b.key for b in at.button
                    ), "confirmation bar must disappear after delete")


class SaveConfirmationUiTests(unittest.TestCase):
    """Save/delete must confirm in the SAME run as the search click - the
    caption-only behavior left the click silent until a later rerun."""

    def _key_input(self, at):
        return next(t for t in at.text_input if (t.label or "").startswith("\U0001f511 API key cho"))

    def test_save_confirms_in_same_run_as_click(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        self._key_input(at).input("BRAND-NEW-KEY")
                        next(c for c in at.checkbox).check()
                        _type_query(at)
                        _click_search(at)  # <-- the run where the save happens
                        self.assertFalse(at.exception, at.exception)
                        self.assertEqual(store.get("pexels"), "BRAND-NEW-KEY")
                        successes = [s.value for s in at.success]
                        self.assertTrue(any("\u0110\u00e3 l\u01b0u key" in s for s in successes), successes)

    def test_delete_confirms_in_same_run_as_click(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "EXISTING-KEY")
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        next(c for c in at.checkbox).uncheck()
                        _type_query(at)
                        _click_search(at)  # <-- the run where the delete happens
                        self.assertFalse(at.exception, at.exception)
                        self.assertEqual(store.get("pexels"), "")
                        successes = [s.value for s in at.success]
                        self.assertTrue(any("\u0110\u00e3 x\u00f3a key" in s for s in successes), successes)
                        # No stale stored-status caption may survive the run
                        # that removed the key: the same frame must not both
                        # claim the key is saved and report the deletion.
                        captions = [c.value or "" for c in at.caption]
                        self.assertFalse(
                            any("Key \u0111\u00e3 \u0111\u01b0\u1ee3c l\u01b0u tr\u00ean m\u00e1y" in cap for cap in captions),
                            captions,
                        )
                        # The search on this run was served by the typed box
                        # key (the store copy was just removed) - the origin
                        # line must say so, not claim the stored key served.
                        self.assertTrue(
                            any("nh\u1eadp trong phi\u00ean n\u00e0y" in cap for cap in captions),
                            captions,
                        )
                        self.assertFalse(
                            any("\u0111\u00e3 d\u00f9ng key \u0111\u00e3 l\u01b0u" in cap for cap in captions),
                            captions,
                        )

    def test_save_failure_shows_error_in_same_run(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        with mock.patch("core.key_store.ApiKeyStore.set", side_effect=OSError("disk full")):
                            at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                            _select_pexels(at)
                            self._key_input(at).input("K1")
                            next(c for c in at.checkbox).check()
                            _type_query(at)
                            _click_search(at)
                            self.assertFalse(at.exception, at.exception)
                            errors = [e.value for e in at.error]
                            self.assertTrue(any("Kh\u00f4ng l\u01b0u \u0111\u01b0\u1ee3c key" in e for e in errors), errors)


class KeyOriginLineUiTests(unittest.TestCase):
    """After a search the UI states which key served it (stored / env / typed),
    in the same run - and stays silent for anonymous sources and rejections."""

    def test_stored_key_origin_line_shown(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "STORED-ORIGIN-KEY")
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        _search_query(at)
                        self.assertFalse(at.exception, at.exception)
                        caps = _captions(at)
                        self.assertTrue(
                            any("\u0110\u00e3 d\u00f9ng key \u0111\u00e3 l\u01b0u tr\u00ean m\u00e1y (m\u00e3 h\u00f3a)." == c.strip()
                                for c in caps), caps
                        )
                        # never reveal the key itself
                        all_text = " ".join(caps)
                        self.assertNotIn("STORED-ORIGIN-KEY", all_text)

    def test_env_origin_line_names_env_var_when_shadowing(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "INERT-STORED-KEY")  # shadowed by the env var
            with mock.patch.dict(os.environ, {"FRAMEFORGE_PEXELS_API_KEY": "ENV-KEY"}, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        _search_query(at)
                        self.assertFalse(at.exception, at.exception)
                        caps = _captions(at)
                        self.assertTrue(any(
                            "\u0110\u00e3 d\u00f9ng key t\u1eeb bi\u1ebfn m\u00f4i tr\u01b0\u1eddng" in c
                            and "FRAMEFORGE_PEXELS_API_KEY" in c for c in caps
                        ), caps)
                        self.assertFalse(any(
                            "\u0110\u00e3 d\u00f9ng key \u0111\u00e3 l\u01b0u" in c for c in caps
                        ), "env served the search, not the inert stored key")

    def test_no_origin_line_for_anonymous_source(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images.search_google_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        at.run()  # default source: DuckDuckGo (anonymous)
                        _search_query(at)
                        self.assertFalse(at.exception, at.exception)
                        caps = _captions(at)
                        self.assertFalse(any("\u0110\u00e3 d\u00f9ng key" in c for c in caps), caps)

    def test_no_origin_line_on_auth_rejection(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            store.set("pexels", "REJECTED-KEY")
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch(
                        "core.google_images._pexels_search_images",
                        side_effect=google_images.ImageSearchAuthError("pexels", 401),
                    ):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        _search_query(at)
                        self.assertFalse(at.exception, at.exception)
                        caps = _captions(at)
                        self.assertFalse(any("\u0110\u00e3 d\u00f9ng key" in c for c in caps), caps)
                        errors = [e.value for e in at.error]
                        self.assertTrue(any("t\u1eeb ch\u1ed1i API key" in e for e in errors), errors)


class ValidateKeyUiTests(unittest.TestCase):
    """Ki\u1ec3m tra key: the typed key is verified BEFORE persisting - a
    rejected key is never written to the store, a valid one is saved and
    confirmed in the same run, and env-shadowed sources show no UI at all."""

    def _type_key(self, at, key):
        next(t for t in at.text_input if (t.label or "").startswith("\U0001f511 API key cho")).input(key)

    def _validate_button(self, at):
        return next(b for b in at.button if b.key == "_inline_img_validate_btn")

    def test_valid_key_persists_and_confirms_in_same_run(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch("core.google_images._pexels_search_images", return_value=[]):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        self._type_key(at, "GOOD-KEY")
                        self._validate_button(at).click()
                        at.run()  # <-- the run where validation + save happen
                        self.assertFalse(at.exception, at.exception)
                        self.assertEqual(store.get("pexels"), "GOOD-KEY")
                        successes = [s.value for s in at.success]
                        self.assertTrue(any("ho\u1ea1t \u0111\u1ed9ng" in s and "\u0111\u00e3 l\u01b0u" in s for s in successes), successes)
                        self.assertFalse(at.error, [e.value for e in at.error])
                        # the key itself never appears in any message
                        self.assertNotIn("GOOD-KEY", " ".join(successes))

    def test_rejected_key_is_not_persisted_and_shows_distinct_error(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, _FRAMEFORGE_ENV_OFF, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    with mock.patch(
                        "core.google_images._pexels_search_images",
                        side_effect=google_images.ImageSearchAuthError("pexels", 401),
                    ):
                        at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                        _select_pexels(at)
                        self._type_key(at, "BAD-KEY")
                        self._validate_button(at).click()
                        at.run()
                        self.assertFalse(at.exception, at.exception)
                        self.assertEqual(store.get("pexels"), "", "rejected key must NOT be stored")
                        errors = [e.value for e in at.error]
                        self.assertTrue(any("t\u1eeb ch\u1ed1i API key" in e for e in errors), errors)
                        self.assertFalse(
                            any("\u0111\u00e3 l\u01b0u" in (s.value or "") for s in at.success),
                            [s.value for s in at.success],
                        )

    def test_env_shadow_hides_validation_ui(self):
        from streamlit.testing.v1 import AppTest

        with tempfile.TemporaryDirectory() as tmp:
            store = ApiKeyStore(base_dir=Path(tmp))
            with mock.patch.dict(os.environ, {"FRAMEFORGE_PEXELS_API_KEY": "ENV-KEY"}, clear=False):
                with mock.patch("core.key_store.default_store", return_value=store):
                    at = AppTest.from_string(_search_widget_script(), default_timeout=60)
                    _select_pexels(at)
                    self.assertFalse(any(b.key == "_inline_img_validate_btn" for b in at.button))
                    self.assertEqual(len(at.checkbox), 0, "no save UI under env shadow")


if __name__ == "__main__":
    unittest.main()
from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import video_downloader
from video_downloader import _rename_downloaded_files, _timestamped_video_path


class VideoDownloaderFilenameTests(unittest.TestCase):
    def test_timestamped_path_is_compact_and_keeps_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            path = _timestamped_video_path(output, "20260826_091500", 1, ".mp4")
            self.assertEqual(path.name, "video_20260826_091500.mp4")

    def test_timestamped_path_avoids_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "video_20260826_091500.mp4").write_bytes(b"old")
            path = _timestamped_video_path(output, "20260826_091500", 1, ".mp4")
            self.assertEqual(path.name, "video_20260826_091500_01.mp4")

    def test_download_batch_returns_timestamped_video(self) -> None:
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, url, download=True):
                self.assert_download = download
                target_dir = Path(self.options['outtmpl']).parent
                (target_dir / 'mocksite_abc_original-title.mp4').write_bytes(b'video')
                return {
                    'id': 'abc',
                    'title': 'Original title',
                    'webpage_url': url,
                    'extractor_key': 'MockSite',
                    'height': 720,
                    'duration': 12.0,
                }

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
            fake_datetime = types.SimpleNamespace(
                now=lambda: types.SimpleNamespace(
                    strftime=lambda _format: '20260826_091500'
                )
            )
            with patch.object(video_downloader, 'yt_dlp', fake_module), patch.object(
                video_downloader, 'ffmpeg_health', return_value={'ffmpeg_path': None}
            ), patch.object(video_downloader, 'datetime', fake_datetime):
                results = video_downloader.download_public_videos(
                    ['https://www.tiktok.com/@example/video/123'], output, max_playlist_items=1
                )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].path.name, 'video_20260826_091500.mp4')
            self.assertEqual(results[0].title, 'Original title')
            self.assertTrue(results[0].path.exists())

    def test_download_uses_isolated_staging_and_cleans_it(self) -> None:
        observed_templates = []

        class FakeYoutubeDL:
            def __init__(self, options):
                observed_templates.append(options['outtmpl'])
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, url, download=True):
                target_dir = Path(self.options['outtmpl']).parent
                (target_dir / 'facebook_reel_existing-title.mp4').write_bytes(b'video')
                return {'id': 'reel', 'title': 'Existing title', 'webpage_url': url, 'extractor_key': 'Facebook'}

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / 'video_20260826_091500.mp4').write_bytes(b'old')
            fake_module = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
            fake_datetime = types.SimpleNamespace(now=lambda: types.SimpleNamespace(strftime=lambda _format: '20260826_091500'))
            with patch.object(video_downloader, 'yt_dlp', fake_module), patch.object(
                video_downloader, 'ffmpeg_health', return_value={'ffmpeg_path': None}
            ), patch.object(video_downloader, 'datetime', fake_datetime):
                results = video_downloader.download_public_videos(
                    ['https://www.facebook.com/reel/1629014048842189'], output, max_playlist_items=1, max_retries=0
                )

            self.assertEqual(len(results), 1)
            self.assertTrue(Path(observed_templates[0]).parent.name.startswith('.frameforge_download_'))
            self.assertEqual(sorted(path.name for path in output.iterdir()), [
                'video_20260826_091500.mp4',
                'video_20260826_091500_01.mp4',
            ])
            self.assertFalse(any(path.name.startswith('.frameforge_download_') for path in output.iterdir()))

    def test_rename_batch_returns_timestamped_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            original_a = output / "facebook_abc_title.mp4"
            original_b = output / "facebook_def_title.webm"
            original_a.write_bytes(b"a")
            original_b.write_bytes(b"b")
            renamed = _rename_downloaded_files(
                [original_a, original_b], output, "20260826_091500"
            )
            self.assertEqual(
                [item.name for item in renamed],
                ["video_20260826_091500.mp4", "video_20260826_091500_02.webm"],
            )
            self.assertTrue(all(item.exists() for item in renamed))
            self.assertFalse(original_a.exists())
            self.assertFalse(original_b.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)


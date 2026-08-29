"""Pure timeline tests that don't need cv2/numpy."""

from __future__ import annotations

import unittest

from timeline_utils import build_timeline_entries, filter_timeline_entries


class TimelinePureTests(unittest.TestCase):
    def test_timeline_build_and_filters(self) -> None:
        reports = [
            {
                "video": "/videos/alpha.mp4",
                "scene_times": [1.0, 5.0],
                "selected_times": [1.2, 4.8],
                "cache_hit": True,
            },
            {
                "video": "/videos/beta.mp4",
                "scene_times": [2.5],
                "selected_times": [2.5],
            },
        ]
        entries = build_timeline_entries(reports)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["representative_seconds"], 1.2)
        self.assertTrue(entries[0]["cache_hit"])
        alpha = filter_timeline_entries(entries, video_name="alpha.mp4")
        self.assertEqual(len(alpha), 2)
        late = filter_timeline_entries(
            entries, query="scene 2", min_seconds=4.0, max_seconds=6.0
        )
        self.assertEqual(
            [(item["video"], item["scene"]) for item in late],
            [("alpha.mp4", 2)],
        )


if __name__ == "__main__":
    unittest.main()

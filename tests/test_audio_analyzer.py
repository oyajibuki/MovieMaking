"""区間演算・字幕リマップの単体テスト（重い依存なしで実行できる部分）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autocutter import audio_analyzer as aa
from autocutter import subtitle_utils as su


class TestMergeSegments(unittest.TestCase):
    def test_merges_overlapping_and_sorts(self):
        self.assertEqual(
            aa.merge_segments([(5, 6), (0, 2), (1.5, 3)]),
            [(0, 3), (5, 6)],
        )

    def test_merges_within_gap(self):
        self.assertEqual(aa.merge_segments([(0, 1), (1.2, 2)], gap=0.5), [(0, 2)])
        self.assertEqual(aa.merge_segments([(0, 1), (1.2, 2)], gap=0.1), [(0, 1), (1.2, 2)])

    def test_drops_empty(self):
        self.assertEqual(aa.merge_segments([(1, 1), (2, 1)]), [])


class TestApplyMargin(unittest.TestCase):
    def test_shrinks_cut_from_both_ends(self):
        self.assertEqual(aa.apply_margin([(1.0, 2.0)], 0.1), [(1.1, 1.9)])

    def test_drops_segment_shorter_than_double_margin(self):
        self.assertEqual(aa.apply_margin([(1.0, 1.1)], 0.1), [])

    def test_zero_margin_is_passthrough(self):
        self.assertEqual(aa.apply_margin([(1.0, 2.0)], 0.0), [(1.0, 2.0)])


class TestGenerateKeepSegments(unittest.TestCase):
    def test_inverts_cuts(self):
        self.assertEqual(
            aa.generate_keep_segments(10.0, [(2, 3), (6, 7)]),
            [(0, 2), (3, 6), (7, 10)],
        )

    def test_cut_at_both_edges(self):
        self.assertEqual(aa.generate_keep_segments(10.0, [(0, 2), (8, 10)]), [(2, 8)])

    def test_no_cuts_keeps_everything(self):
        self.assertEqual(aa.generate_keep_segments(10.0, []), [(0, 10)])

    def test_drops_too_short_keeps(self):
        keeps = aa.generate_keep_segments(10.0, [(2, 3), (3.02, 6)], min_keep_len=0.1)
        self.assertEqual(keeps, [(0, 2), (6, 10)])

    def test_clamps_cuts_beyond_duration(self):
        self.assertEqual(aa.generate_keep_segments(5.0, [(4, 99)]), [(0, 4)])


class TestTimeMapper(unittest.TestCase):
    def test_maps_into_compacted_timeline(self):
        mapper = aa.build_time_mapper([(0, 2), (3, 6)])
        self.assertAlmostEqual(mapper(1.0), 1.0)
        self.assertAlmostEqual(mapper(3.0), 2.0)
        self.assertAlmostEqual(mapper(5.0), 4.0)
        self.assertIsNone(mapper(2.5))


class TestRemapSubtitles(unittest.TestCase):
    def test_shifts_subtitle_after_a_cut(self):
        subs = [{"start": 4.0, "end": 5.0, "text": "こんにちは"}]
        out = aa.remap_subtitles(subs, [(0, 2), (3, 6)])
        self.assertAlmostEqual(out[0]["start"], 3.0)
        self.assertAlmostEqual(out[0]["end"], 4.0)
        self.assertEqual(out[0]["text"], "こんにちは")

    def test_drops_fully_cut_subtitle(self):
        subs = [{"start": 2.1, "end": 2.9, "text": "えー"}]
        self.assertEqual(aa.remap_subtitles(subs, [(0, 2), (3, 6)]), [])

    def test_subtitle_spanning_a_cut_keeps_text(self):
        subs = [{"start": 1.0, "end": 4.0, "text": "またぐ"}]
        out = aa.remap_subtitles(subs, [(0, 2), (3, 6)])
        self.assertAlmostEqual(out[0]["start"], 1.0)
        self.assertAlmostEqual(out[0]["end"], 3.0)

    def test_no_overlap_between_consecutive_subtitles(self):
        subs = [
            {"start": 0.0, "end": 1.9, "text": "A"},
            {"start": 3.0, "end": 4.0, "text": "B"},
        ]
        out = aa.remap_subtitles(subs, [(0, 2), (3, 6)])
        self.assertLessEqual(out[0]["end"], out[1]["start"])


class TestDetectFillers(unittest.TestCase):
    def _result(self, words):
        return {
            "segments": [
                {
                    "start": words[0]["start"],
                    "end": words[-1]["end"],
                    "text": "".join(w["word"] for w in words),
                    "words": words,
                }
            ]
        }

    def test_detects_word_level_fillers(self):
        res = self._result([
            {"start": 0.0, "end": 0.4, "word": "えー"},
            {"start": 0.4, "end": 1.0, "word": "本題"},
            {"start": 1.0, "end": 1.3, "word": "あのー"},
        ])
        cuts = aa.detect_fillers(res, ["えー", "あのー"], padding=0.0)
        self.assertEqual(cuts, [(0.0, 0.4), (1.0, 1.3)])

    def test_ignores_punctuation_and_case(self):
        res = self._result([
            {"start": 0.0, "end": 0.4, "word": " Um,"},
            {"start": 0.4, "end": 1.0, "word": "hello"},
        ])
        cuts = aa.detect_fillers(res, ["um"], padding=0.0)
        self.assertEqual(cuts, [(0.0, 0.4)])

    def test_segment_level_fallback_requires_whole_segment_match(self):
        segments = [
            {"start": 0.0, "end": 0.5, "text": "えー。"},
            {"start": 0.5, "end": 2.0, "text": "えー、本題です"},
        ]
        cuts = aa.detect_fillers(segments, ["えー"], padding=0.0)
        self.assertEqual(cuts, [(0.0, 0.5)])

    def test_padding_never_goes_negative(self):
        res = self._result([{"start": 0.0, "end": 0.4, "word": "えー"}])
        cuts = aa.detect_fillers(res, ["えー"], padding=0.1)
        self.assertEqual(cuts[0][0], 0.0)


class TestSubtitleOutput(unittest.TestCase):
    def test_srt_format(self):
        srt = su.create_srt_content([{"start": 0.0, "end": 1.5, "text": "テスト"}])
        self.assertIn("00:00:00,000 --> 00:00:01,500", srt)
        self.assertTrue(srt.startswith("1\n"))

    def test_srt_skips_empty_text(self):
        srt = su.create_srt_content([
            {"start": 0.0, "end": 1.0, "text": "  "},
            {"start": 1.0, "end": 2.0, "text": "あり"},
        ])
        self.assertNotIn("00:00:00,000", srt)

    def test_ass_contains_dialogue_and_style(self):
        ass = su.create_ass_content([{"start": 0.0, "end": 1.5, "text": "テスト"}], font_size=48)
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.50", ass)
        self.assertIn(",48,", ass)

    def test_hex_to_ass_color(self):
        self.assertEqual(su.hex_to_ass_color("#FF0000"), "&H000000FF")
        self.assertEqual(su.hex_to_ass_color("bad"), "&H00FFFFFF")


class TestVoiceChangerMath(unittest.TestCase):
    def test_semitones_to_octaves(self):
        from autocutter import voice_changer as vc
        self.assertAlmostEqual(vc.semitones_to_octaves(12), 1.0)
        self.assertAlmostEqual(vc.semitones_to_octaves(-6), -0.5)

    def test_zero_shift_returns_input_path(self):
        from autocutter import voice_changer as vc
        self.assertEqual(vc.shift_pitch_file("in.wav", "out.wav", 0), "in.wav")


if __name__ == "__main__":
    unittest.main()

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


class TestFragmentedFillers(unittest.TestCase):
    """Whisper の日本語は 1 文字ずつに割れることがあるため、連結して照合する。"""

    def _seg(self, tokens):
        words, t = [], 0.0
        for tok in tokens:
            words.append({"start": t, "end": t + 0.1, "word": tok})
            t += 0.1
        return [{"start": 0.0, "end": t, "text": "".join(tokens), "words": words}]

    def test_matches_filler_split_across_tokens(self):
        seg = self._seg(["え", "ー", "と", "本題"])
        cuts = aa.detect_fillers(seg, ["えーと"], padding=0.0)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0][0], 0.0)
        self.assertAlmostEqual(cuts[0][1], 0.3)

    def test_prefers_longest_match(self):
        # 「えー」も「えーと」も候補にあるとき、長い方を採用する
        seg = self._seg(["え", "ー", "と", "本題"])
        cuts = aa.detect_fillers(seg, ["えー", "えーと"], padding=0.0)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0][1], 0.3)

    def test_does_not_span_past_the_filler(self):
        seg = self._seg(["え", "ー", "本題", "です"])
        cuts = aa.detect_fillers(seg, ["えー"], padding=0.0)
        self.assertAlmostEqual(cuts[0][1], 0.2)

    def test_no_match_leaves_everything(self):
        seg = self._seg(["こんにちは", "本題", "です"])
        self.assertEqual(aa.detect_fillers(seg, ["えーと"], padding=0.0), [])

    def test_punctuation_between_fragments_is_ignored(self):
        seg = self._seg(["えー", "と、", "本題"])
        cuts = aa.detect_fillers(seg, ["えーと"], padding=0.0)
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0][1], 0.2)


class TestRelativeThreshold(unittest.TestCase):
    """静かに録れた素材で喋りごと切ってしまわないための相対閾値。"""

    class FakeAudio:
        def __init__(self, dbfs):
            self.dBFS = dbfs

    def test_absolute_threshold_when_offset_is_none(self):
        self.assertEqual(aa.resolve_threshold(self.FakeAudio(-34.9), -38.0, None), -38.0)

    def test_relative_threshold_follows_material_loudness(self):
        # 平均 -34.9dBFS の素材なら -50.9dBFS が閾値になる
        self.assertAlmostEqual(
            aa.resolve_threshold(self.FakeAudio(-34.9), -38.0, 16.0), -50.9
        )

    def test_quiet_material_gets_a_lower_threshold_than_the_fixed_default(self):
        quiet = aa.resolve_threshold(self.FakeAudio(-34.9), -38.0, 16.0)
        self.assertLess(quiet, -38.0)

    def test_silent_material_falls_back_to_absolute(self):
        silent = self.FakeAudio(float("-inf"))
        self.assertEqual(aa.resolve_threshold(silent, -38.0, 16.0), -38.0)


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


class TestMediaTypeDetection(unittest.TestCase):
    """拡張子だけで判定できる部分のテスト（ffmpeg 不要）。"""

    def setUp(self):
        from autocutter import video_editor
        self.ve = video_editor

    def test_audio_extensions_detected(self):
        for name in ["a.mp3", "a.M4A", "a.wav", "a.flac", "a.ogg", "a.opus", "a.aac", "a.aiff"]:
            self.assertTrue(self.ve.is_audio_only(name), name)

    def test_output_extension_matches_supported_input(self):
        self.assertEqual(self.ve.supported_output_extension("x.mp3"), ".mp3")
        self.assertEqual(self.ve.supported_output_extension("x.M4A"), ".m4a")
        self.assertEqual(self.ve.supported_output_extension("x.flac"), ".flac")

    def test_unsupported_output_extension_falls_back_to_m4a(self):
        self.assertEqual(self.ve.supported_output_extension("x.wma"), ".m4a")
        self.assertEqual(self.ve.supported_output_extension("x.caf"), ".m4a")

    def test_every_audio_extension_has_an_output_target(self):
        # 入力として受け付ける形式は、必ず何らかの形式で書き出せること
        for ext in self.ve.AUDIO_EXTENSIONS:
            out = self.ve.supported_output_extension("x" + ext)
            self.assertIn(out, self.ve._EXPORT_FORMATS, ext)

    def test_ogg_has_a_fallback_encoder_candidate(self):
        # libvorbis を持たない ffmpeg ビルドがあるため候補が 2 つ以上必要
        self.assertGreaterEqual(len(self.ve._EXPORT_FORMATS[".ogg"]), 2)


if __name__ == "__main__":
    unittest.main()

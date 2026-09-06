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
    def setUp(self):
        from autocutter import voice_changer
        self.vc = voice_changer

    def test_semitones_to_octaves(self):
        self.assertAlmostEqual(self.vc.semitones_to_octaves(12), 1.0)
        self.assertAlmostEqual(self.vc.semitones_to_octaves(-6), -0.5)

    def test_zero_shift_returns_input_path(self):
        self.assertEqual(self.vc.shift_pitch_file("in.wav", "out.wav", 0), "in.wav")

    def test_no_change_returns_input_path(self):
        self.assertEqual(
            self.vc.convert_voice_file("in.wav", "out.wav", 0.0, 1.0), "in.wav"
        )


class TestVoicePresets(unittest.TestCase):
    def setUp(self):
        from autocutter import voice_changer
        self.vc = voice_changer

    def test_default_preset_is_a_no_op(self):
        self.assertEqual(self.vc.resolve_preset(self.vc.DEFAULT_PRESET), (0.0, 1.0))

    def test_feminine_presets_raise_pitch_and_formant(self):
        for name in ["女性の声", "高めの女性の声", "子供の声"]:
            semitones, formant = self.vc.resolve_preset(name)
            self.assertGreater(semitones, 0, name)
            self.assertGreater(formant, 1.0, name)

    def test_masculine_presets_lower_pitch_and_formant(self):
        for name in ["太い男の声", "低い男の声"]:
            semitones, formant = self.vc.resolve_preset(name)
            self.assertLess(semitones, 0, name)
            self.assertLess(formant, 1.0, name)

    def test_preset_targets_the_requested_pitch_for_a_low_voice(self):
        # 68Hz の低い声でも「女性の声」は 200Hz 付近に届くこと
        semitones, _ = self.vc.resolve_preset("女性の声", 1.0, source_f0=68.0)
        reached = 68.0 * 2 ** (semitones / 12)
        self.assertAlmostEqual(reached, 200.0, delta=5.0)

    def test_preset_targets_the_requested_pitch_for_a_high_voice(self):
        # 高い声なら同じプリセットでも変化量は小さくなる
        semitones, _ = self.vc.resolve_preset("女性の声", 1.0, source_f0=180.0)
        reached = 180.0 * 2 ** (semitones / 12)
        self.assertAlmostEqual(reached, 200.0, delta=5.0)

    def test_deep_preset_never_raises_pitch(self):
        # 目標より既に低い声に「太い男の声」を掛けても高くならないこと
        for f0 in [60.0, 68.0, 80.0, 120.0]:
            semitones, _ = self.vc.resolve_preset("太い男の声", 1.0, source_f0=f0)
            self.assertLess(semitones, 0, f"f0={f0}")

    def test_high_preset_never_lowers_pitch(self):
        for f0 in [68.0, 220.0, 300.0]:
            semitones, _ = self.vc.resolve_preset("女性の声", 1.0, source_f0=f0)
            self.assertGreater(semitones, 0, f"f0={f0}")

    def test_describe_reports_clamping_for_unreachable_targets(self):
        # 68Hz から 290Hz は上限を超えるので、届かないことが分かるようにする
        info = self.vc.describe_preset("子供の声", 1.0, source_f0=68.0)
        self.assertTrue(info["clamped"])
        self.assertLess(info["reached_f0"], info["target_f0"])

    def test_describe_reports_no_clamping_when_target_is_reachable(self):
        info = self.vc.describe_preset("女性の声", 1.0, source_f0=150.0)
        self.assertFalse(info["clamped"])

    def test_strength_scales_both_axes(self):
        full = self.vc.resolve_preset("女性の声", 1.0)
        half = self.vc.resolve_preset("女性の声", 0.5)
        self.assertAlmostEqual(half[0], full[0] / 2)
        # フォルマントは 1.0 を中心に増減する
        self.assertAlmostEqual(half[1] - 1.0, (full[1] - 1.0) / 2)

    def test_zero_strength_disables_the_effect(self):
        self.assertEqual(self.vc.resolve_preset("子供の声", 0.0), (0.0, 1.0))

    def test_values_are_clamped_to_usable_range(self):
        semitones, formant = self.vc.resolve_preset("子供の声", 10.0)
        self.assertLessEqual(semitones, self.vc.MAX_SEMITONES)
        self.assertLessEqual(formant, self.vc.MAX_FORMANT)

    def test_unknown_preset_falls_back_to_no_op(self):
        self.assertEqual(self.vc.resolve_preset("存在しない声"), (0.0, 1.0))


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


class TestAiVoiceAvailability(unittest.TestCase):
    """AI 声質変換は任意導入なので、未導入でも壊れないこと。"""

    def setUp(self):
        from autocutter import ai_voice
        self.av = ai_voice

    def test_availability_check_never_raises(self):
        self.assertIsInstance(self.av.is_available(), bool)

    def test_unavailable_reason_is_empty_only_when_available(self):
        reason = self.av.unavailable_reason()
        self.assertEqual(bool(reason), not self.av.is_available())

    def test_builtin_voices_is_a_mapping(self):
        voices = self.av.available_builtin_voices()
        self.assertIsInstance(voices, dict)
        # 値は say に渡す音声名なので、既知の一覧に含まれること
        for name in voices.values():
            self.assertIn(name, self.av.MACOS_JA_VOICES.values())

    def test_convert_reports_a_clear_error_when_not_installed(self):
        if self.av.is_available():
            self.skipTest("導入済みの環境ではこの分岐を通らない")
        with self.assertRaises(RuntimeError):
            self.av.convert("a.wav", "b.wav", "c.wav")


class TestVoiceModeSelection(unittest.TestCase):
    """AI 指定があるときは信号処理プリセットより優先されること。"""

    def setUp(self):
        from autocutter import pipeline
        self.pipeline = pipeline

    def test_no_ai_by_default(self):
        self.assertFalse(self.pipeline.CutSettings().uses_ai_voice)

    def test_builtin_voice_enables_ai(self):
        s = self.pipeline.CutSettings(ai_builtin_voice="Kyoko")
        self.assertTrue(s.uses_ai_voice)

    def test_reference_wav_enables_ai(self):
        s = self.pipeline.CutSettings(ai_reference_wav="/tmp/ref.wav")
        self.assertTrue(s.uses_ai_voice)

    def test_preset_still_resolves_alongside_ai(self):
        # AI 指定時もプリセットの解決自体は壊れないこと
        s = self.pipeline.CutSettings(ai_builtin_voice="Kyoko", voice_preset="女性の声")
        semitones, formant = s.resolve_voice(source_f0=120.0)
        self.assertIsInstance(semitones, float)
        self.assertIsInstance(formant, float)


if __name__ == "__main__":
    unittest.main()

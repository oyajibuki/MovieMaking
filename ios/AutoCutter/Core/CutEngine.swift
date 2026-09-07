import AVFoundation

/// 解析から書き出しまでの流れをまとめる。
@MainActor
final class CutEngine: ObservableObject {

    struct Settings {
        var removeSilence = true
        var removeFillers = true
        /// 平均音量から何 dB 下を無音とみなすか。大きいほどカットが控えめになる
        var sensitivity: Double = 16
        var minimumSilence: Double = 0.5
        /// カット前後に残す余白（秒）
        var margin: Double = 0.08
        var voicePreset: VoiceChanger.Preset = VoiceChanger.presets[0]
    }

    struct Analysis {
        var keeps: [Segment]
        var silences: [Segment]
        var fillers: [Segment]
        var originalDuration: Double
        var averageLoudness: Double
        var threshold: Double
        var subtitles: [SubtitleWriter.Line]
        var transcript: String

        var newDuration: Double { SegmentMath.totalDuration(keeps) }
        var removedDuration: Double { max(0, originalDuration - newDuration) }
        var removedRatio: Double {
            originalDuration > 0 ? removedDuration / originalDuration : 0
        }
        var cutCount: Int { silences.count + fillers.count }
    }

    @Published var progress: Double = 0
    @Published var statusMessage = ""

    private var workDirectory: URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("AutoCutter", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    /// 動画（または音声）を解析してカット箇所を求める。
    func analyze(url: URL, settings: Settings) async throws -> Analysis {
        progress = 0.05
        statusMessage = "音声を取り出しています..."

        let asset = AVURLAsset(url: url)
        let duration = try await asset.load(.duration).seconds
        let audioURL = workDirectory.appendingPathComponent("source.m4a")
        _ = try await VideoEditor.extractAudio(from: asset, to: audioURL)

        var silences: [Segment] = []
        var averageLoudness = -Double.infinity
        var threshold = -38.0

        if settings.removeSilence {
            progress = 0.3
            statusMessage = "無音を探しています..."
            let result = try SilenceDetector.detect(
                url: audioURL,
                minimumSilence: settings.minimumSilence,
                relativeOffsetDB: settings.sensitivity
            )
            silences = result.silences
            averageLoudness = result.averageLoudness
            threshold = result.threshold
        }

        var fillers: [Segment] = []
        var subtitleLines: [SubtitleWriter.Line] = []
        var transcript = ""

        if settings.removeFillers {
            progress = 0.5
            statusMessage = "話している内容を認識しています..."
            // 認識に失敗しても無音カットだけで続行する
            if let result = try? await FillerDetector.detect(url: audioURL) {
                fillers = result.fillers
                transcript = result.transcript
                subtitleLines = SubtitleWriter.lines(from: result.words)
            }
        }

        progress = 0.85
        statusMessage = "カットする場所を決めています..."

        let cuts = SegmentMath.applyMargin(silences + fillers, margin: settings.margin)
        let keeps = SegmentMath.keepSegments(totalDuration: duration, cuts: cuts)

        progress = 1
        statusMessage = "完了"

        return Analysis(
            keeps: keeps,
            silences: silences,
            fillers: fillers,
            originalDuration: duration,
            averageLoudness: averageLoudness,
            threshold: threshold,
            subtitles: SubtitleWriter.remap(lines: subtitleLines, keeps: keeps),
            transcript: transcript
        )
    }

    /// カット結果を書き出す。
    func export(
        url: URL,
        analysis: Analysis,
        settings: Settings,
        sourceF0: Double? = nil
    ) async throws -> URL {
        progress = 0
        let asset = AVURLAsset(url: url)

        var replacementAudio: URL?
        let semitones = VoiceChanger.semitones(
            for: settings.voicePreset, sourceF0: sourceF0
        )

        if semitones != 0 {
            statusMessage = "声を変えています..."
            progress = 0.1
            let source = workDirectory.appendingPathComponent("source.m4a")
            let shifted = workDirectory.appendingPathComponent("shifted.caf")
            replacementAudio = try VoiceChanger.process(
                inputURL: source, outputURL: shifted, semitones: semitones
            )
        }

        statusMessage = "書き出しています..."
        let output = workDirectory
            .appendingPathComponent("AutoCutter_\(Int(Date().timeIntervalSince1970)).mp4")

        return try await VideoEditor.export(
            asset: asset,
            keeps: analysis.keeps,
            to: output,
            replacementAudio: replacementAudio,
            progress: { [weak self] value in
                Task { @MainActor in self?.progress = 0.2 + value * 0.8 }
            }
        )
    }
}

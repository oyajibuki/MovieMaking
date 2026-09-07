import AVFoundation

/// 声色変換。
///
/// AVAudioUnitTimePitch を使い、話速を保ったままピッチだけを変える。
/// AVMutableAudioMix にはピッチを変える機能が無いため、
/// AVAudioEngine のオフラインレンダリングで音声ファイルを作り直し、
/// それを映像と合成する。
enum VoiceChanger {

    enum Failure: LocalizedError {
        case renderFailed(String)

        var errorDescription: String? {
            switch self {
            case .renderFailed(let message):
                return "声色の変換に失敗しました: \(message)"
            }
        }
    }

    /// プリセット。目標の声の高さ（Hz）で指定する。
    /// 半音の固定値だと元の声の高さで着地点が変わってしまうため。
    struct Preset: Identifiable, Hashable {
        var id: String { name }
        var name: String
        var emoji: String
        var targetF0: Double?
        var fallbackSemitones: Double
        var lowersPitch: Bool
    }

    static let presets: [Preset] = [
        Preset(name: "そのまま", emoji: "🙂", targetF0: nil, fallbackSemitones: 0, lowersPitch: false),
        Preset(name: "女性の声", emoji: "👩", targetF0: 200, fallbackSemitones: 6, lowersPitch: false),
        Preset(name: "高めの女性", emoji: "👧", targetF0: 240, fallbackSemitones: 8, lowersPitch: false),
        Preset(name: "子供の声", emoji: "🧒", targetF0: 290, fallbackSemitones: 10, lowersPitch: false),
        Preset(name: "太い男の声", emoji: "🧔", targetF0: 85, fallbackSemitones: -4, lowersPitch: true),
        Preset(name: "低い男の声", emoji: "👨", targetF0: 100, fallbackSemitones: -2.5, lowersPitch: true),
        Preset(name: "軽い匿名化", emoji: "🕶️", targetF0: nil, fallbackSemitones: 2, lowersPitch: false),
    ]

    /// 話者の声の高さから、目標に届くだけの半音数を求める。
    static func semitones(for preset: Preset, sourceF0: Double?, strength: Double = 1) -> Double {
        var value = preset.fallbackSemitones

        if let target = preset.targetF0, let source = sourceF0, source > 0 {
            value = 12 * log2(target / source)
            // 既に目標より低い声に「太い男の声」を掛けて逆に高くならないようにする
            if preset.lowersPitch && value > 0 {
                value = preset.fallbackSemitones
            } else if !preset.lowersPitch && value < 0 {
                value = preset.fallbackSemitones
            }
        }

        return min(max(value * strength, -20), 20)
    }

    /// 音声ファイルのピッチを変えて書き出す。長さは変わらない。
    static func process(
        inputURL: URL,
        outputURL: URL,
        semitones: Double
    ) throws -> URL {
        guard semitones != 0 else { return inputURL }

        let inputFile = try AVAudioFile(forReading: inputURL)
        let format = inputFile.processingFormat
        let totalFrames = inputFile.length

        let engine = AVAudioEngine()
        let player = AVAudioPlayerNode()
        let pitchUnit = AVAudioUnitTimePitch()
        pitchUnit.pitch = Float(semitones * 100)   // cents（100 cents = 1 半音）

        engine.attach(player)
        engine.attach(pitchUnit)
        engine.connect(player, to: pitchUnit, format: format)
        engine.connect(pitchUnit, to: engine.mainMixerNode, format: format)

        let maximumFrameCount: AVAudioFrameCount = 4096
        try engine.enableManualRenderingMode(
            .offline, format: format, maximumFrameCount: maximumFrameCount
        )
        try engine.start()
        player.scheduleFile(inputFile, at: nil)
        player.play()

        try? FileManager.default.removeItem(at: outputURL)
        let outputFile = try AVAudioFile(
            forWriting: outputURL, settings: format.settings
        )

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: engine.manualRenderingFormat,
            frameCapacity: engine.manualRenderingMaximumFrameCount
        ) else {
            throw Failure.renderFailed("バッファを確保できませんでした")
        }

        while engine.manualRenderingSampleTime < totalFrames {
            let remaining = totalFrames - engine.manualRenderingSampleTime
            let frames = AVAudioFrameCount(min(Int64(buffer.frameCapacity), remaining))
            let status = try engine.renderOffline(frames, to: buffer)

            switch status {
            case .success:
                try outputFile.write(from: buffer)
            case .insufficientDataFromInputNode:
                continue
            case .cannotDoInCurrentContext, .error:
                throw Failure.renderFailed("レンダリングが中断されました")
            @unknown default:
                throw Failure.renderFailed("想定外の状態です")
            }
        }

        player.stop()
        engine.stop()
        return outputURL
    }
}

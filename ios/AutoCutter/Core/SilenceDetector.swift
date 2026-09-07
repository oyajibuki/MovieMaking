import Accelerate
import AVFoundation

/// 無音区間の検出。
///
/// Python 版と同じく、既定では素材の平均音量を基準に閾値を決める。
/// 固定値（例 -38dBFS）にすると、小さく録れた素材では喋っている部分まで
/// 無音と判定してしまうため。
enum SilenceDetector {

    struct Result {
        var silences: [Segment]
        var averageLoudness: Double   // dBFS
        var threshold: Double         // dBFS
    }

    /// - Parameters:
    ///   - url: 音声を含むファイル
    ///   - windowSeconds: 音量を測る窓の長さ
    ///   - minimumSilence: 無音とみなす最短の長さ（秒）
    ///   - relativeOffsetDB: 平均音量から何 dB 下を無音とみなすか。nil なら固定値を使う
    ///   - fixedThresholdDB: relativeOffsetDB が nil のときに使う絶対値
    static func detect(
        url: URL,
        windowSeconds: Double = 0.02,
        minimumSilence: Double = 0.5,
        relativeOffsetDB: Double? = 16,
        fixedThresholdDB: Double = -38
    ) throws -> Result {
        let levels = try frameLevels(url: url, windowSeconds: windowSeconds)
        guard !levels.isEmpty else {
            return Result(silences: [], averageLoudness: -.infinity, threshold: fixedThresholdDB)
        }

        let average = averageDBFS(levels)
        var threshold = fixedThresholdDB
        if let offset = relativeOffsetDB, average.isFinite {
            threshold = average - offset
        }

        // 閾値を下回る窓が minimumSilence 秒以上続いた範囲を無音とする
        var silences: [Segment] = []
        var runStart: Int?

        for (index, level) in levels.enumerated() {
            if level <= threshold {
                if runStart == nil { runStart = index }
            } else if let start = runStart {
                appendIfLongEnough(&silences, start, index, windowSeconds, minimumSilence)
                runStart = nil
            }
        }
        if let start = runStart {
            appendIfLongEnough(&silences, start, levels.count, windowSeconds, minimumSilence)
        }

        return Result(
            silences: SegmentMath.merge(silences),
            averageLoudness: average,
            threshold: threshold
        )
    }

    private static func appendIfLongEnough(
        _ silences: inout [Segment],
        _ startIndex: Int,
        _ endIndex: Int,
        _ windowSeconds: Double,
        _ minimumSilence: Double
    ) {
        let start = Double(startIndex) * windowSeconds
        let end = Double(endIndex) * windowSeconds
        if end - start >= minimumSilence {
            silences.append(Segment(start, end))
        }
    }

    /// 窓ごとの音量（dBFS）を並べて返す。
    static func frameLevels(url: URL, windowSeconds: Double) throws -> [Double] {
        let file = try AVAudioFile(forReading: url)
        let format = file.processingFormat
        let frameCount = AVAudioFrameCount(format.sampleRate * windowSeconds)
        guard frameCount > 0 else { return [] }

        var levels: [Double] = []
        levels.reserveCapacity(Int(file.length) / Int(frameCount) + 1)

        while file.framePosition < file.length {
            guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount) else {
                break
            }
            try file.read(into: buffer, frameCount: frameCount)
            if buffer.frameLength == 0 { break }
            levels.append(dbfs(of: buffer))
        }
        return levels
    }

    /// バッファ全チャンネルの RMS を dBFS で返す。
    private static func dbfs(of buffer: AVAudioPCMBuffer) -> Double {
        guard let channels = buffer.floatChannelData else { return -.infinity }
        let frames = vDSP_Length(buffer.frameLength)
        guard frames > 0 else { return -.infinity }

        var sumOfSquares: Float = 0
        for channel in 0..<Int(buffer.format.channelCount) {
            var rms: Float = 0
            vDSP_rmsqv(channels[channel], 1, &rms, frames)
            sumOfSquares += rms * rms
        }

        let rms = sqrt(sumOfSquares / Float(buffer.format.channelCount))
        guard rms > 0 else { return -.infinity }
        return Double(20 * log10(rms))
    }

    /// 窓ごとの dBFS からエネルギー平均を求める（単純な平均だと静かな窓に引っ張られる）。
    private static func averageDBFS(_ levels: [Double]) -> Double {
        let powers = levels.filter { $0.isFinite }.map { pow(10, $0 / 10) }
        guard !powers.isEmpty else { return -.infinity }
        let mean = powers.reduce(0, +) / Double(powers.count)
        return 10 * log10(mean)
    }
}

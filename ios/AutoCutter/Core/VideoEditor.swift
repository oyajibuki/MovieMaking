import AVFoundation

/// 「残す区間」に従って映像と音声を切り出し、繋ぎ直して書き出す。
///
/// AVMutableComposition は実際にフレームをコピーせず参照を並べるだけなので、
/// カット自体は一瞬で終わる。時間がかかるのは最後のエンコードのみ。
enum VideoEditor {

    enum Failure: LocalizedError {
        case noTracks
        case nothingToKeep
        case exportFailed(String)

        var errorDescription: String? {
            switch self {
            case .noTracks:
                return "この動画には読み取れる映像・音声がありません。"
            case .nothingToKeep:
                return "残る部分がありません。カットの設定を弱めてください。"
            case .exportFailed(let message):
                return "書き出しに失敗しました: \(message)"
            }
        }
    }

    /// 音声だけを m4a として取り出す（解析用）。
    static func extractAudio(from asset: AVAsset, to url: URL) async throws -> URL {
        guard let session = AVAssetExportSession(
            asset: asset, presetName: AVAssetExportPresetAppleM4A
        ) else {
            throw Failure.exportFailed("音声の取り出しを開始できませんでした")
        }

        try? FileManager.default.removeItem(at: url)
        session.outputURL = url
        session.outputFileType = .m4a
        try await export(session: session)
        return url
    }

    /// 残す区間だけを繋いだ動画（または音声）を書き出す。
    static func export(
        asset: AVAsset,
        keeps: [Segment],
        to url: URL,
        replacementAudio: URL? = nil,
        progress: (@Sendable (Double) -> Void)? = nil
    ) async throws -> URL {
        guard !keeps.isEmpty else { throw Failure.nothingToKeep }

        let composition = AVMutableComposition()
        let videoTracks = try await asset.loadTracks(withMediaType: .video)

        // 声色を変えた場合は、元の音声ではなく差し替え用の音声から切り出す
        let audioSource: AVAsset = replacementAudio.map { AVURLAsset(url: $0) } ?? asset
        let audioTracks = try await audioSource.loadTracks(withMediaType: .audio)
        guard !videoTracks.isEmpty || !audioTracks.isEmpty else { throw Failure.noTracks }

        let videoTrack = videoTracks.first.flatMap { source -> (AVMutableCompositionTrack, AVAssetTrack)? in
            guard let track = composition.addMutableTrack(
                withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid
            ) else { return nil }
            return (track, source)
        }
        let audioTrack = audioTracks.first.flatMap { source -> (AVMutableCompositionTrack, AVAssetTrack)? in
            guard let track = composition.addMutableTrack(
                withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid
            ) else { return nil }
            return (track, source)
        }

        // 残す区間を順に連結する
        var cursor = CMTime.zero
        for keep in keeps {
            let range = CMTimeRange(
                start: CMTime(seconds: keep.start, preferredTimescale: 600),
                duration: CMTime(seconds: keep.duration, preferredTimescale: 600)
            )
            if let (track, source) = videoTrack {
                try track.insertTimeRange(range, of: source, at: cursor)
            }
            if let (track, source) = audioTrack {
                try track.insertTimeRange(range, of: source, at: cursor)
            }
            cursor = CMTimeAdd(cursor, range.duration)
        }

        // 撮影時の向きを引き継ぐ（縦持ちの動画が横倒しにならないように）
        if let (track, source) = videoTrack {
            track.preferredTransform = try await source.load(.preferredTransform)
        }

        let preset = videoTrack == nil
            ? AVAssetExportPresetAppleM4A
            : AVAssetExportPresetHighestQuality
        guard let session = AVAssetExportSession(asset: composition, presetName: preset) else {
            throw Failure.exportFailed("書き出しを開始できませんでした")
        }

        try? FileManager.default.removeItem(at: url)
        session.outputURL = url
        session.outputFileType = videoTrack == nil ? .m4a : .mp4
        session.shouldOptimizeForNetworkUse = true

        try await export(session: session, progress: progress)
        return url
    }

    private static func export(
        session: AVAssetExportSession,
        progress: (@Sendable (Double) -> Void)? = nil
    ) async throws {
        let monitor = progress.map { report in
            Task {
                while !Task.isCancelled {
                    report(Double(session.progress))
                    try? await Task.sleep(nanoseconds: 200_000_000)
                }
            }
        }
        defer { monitor?.cancel() }

        await session.export()

        switch session.status {
        case .completed:
            progress?(1)
        case .cancelled:
            throw Failure.exportFailed("中断されました")
        default:
            throw Failure.exportFailed(session.error?.localizedDescription ?? "原因不明")
        }
    }
}

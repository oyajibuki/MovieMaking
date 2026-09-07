import Photos

/// 書き出した動画を写真アプリに保存する。CapCut などから読み込めるようにするため。
enum PhotoLibrary {

    enum Failure: LocalizedError {
        case notAuthorized
        case saveFailed(String)

        var errorDescription: String? {
            switch self {
            case .notAuthorized:
                return "写真への保存が許可されていません。設定アプリから許可してください。"
            case .saveFailed(let message):
                return "保存に失敗しました: \(message)"
            }
        }
    }

    static func saveVideo(_ url: URL) async throws {
        let status = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard status == .authorized || status == .limited else { throw Failure.notAuthorized }

        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.creationRequestForAssetFromVideo(atFileURL: url)
            }
        } catch {
            throw Failure.saveFailed(error.localizedDescription)
        }
    }
}

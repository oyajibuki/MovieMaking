import CoreTransferable
import SwiftUI

/// 写真ライブラリから選んだ動画を、作業用フォルダにコピーして受け取る。
struct VideoFile: Transferable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(contentType: .movie) { movie in
            SentTransferredFile(movie.url)
        } importing: { received in
            let directory = FileManager.default.temporaryDirectory
                .appendingPathComponent("AutoCutter", isDirectory: true)
            try? FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true
            )

            let destination = directory
                .appendingPathComponent("input_\(UUID().uuidString)")
                .appendingPathExtension(received.file.pathExtension.isEmpty ? "mov" : received.file.pathExtension)

            try? FileManager.default.removeItem(at: destination)
            try FileManager.default.copyItem(at: received.file, to: destination)
            return VideoFile(url: destination)
        }
    }
}

import Foundation
import Speech

/// フィラー（言い淀み）の検出。
///
/// iOS 標準の音声認識を使い、単語ごとのタイムスタンプからフィラーを探す。
/// 日本語の認識結果は「えー」「と、」のように細かく割れることがあるため、
/// Python 版と同じく連続する単語をつなげて照合する（最長一致）。
enum FillerDetector {

    static let defaultWords = [
        "えー", "えーと", "えっと", "えと", "あー", "あのー", "あの",
        "そのー", "まあ", "まー", "なんか", "うーん", "んー", "ええと",
    ]

    struct Word {
        var text: String
        var start: Double
        var end: Double
    }

    struct Result {
        var fillers: [Segment]
        var words: [Word]
        var transcript: String
    }

    enum Failure: LocalizedError {
        case notAuthorized
        case unavailable
        case recognitionFailed(String)

        var errorDescription: String? {
            switch self {
            case .notAuthorized:
                return "音声認識の使用が許可されていません。設定アプリから許可してください。"
            case .unavailable:
                return "この端末では日本語の音声認識を利用できません。"
            case .recognitionFailed(let message):
                return "音声認識に失敗しました: \(message)"
            }
        }
    }

    /// 音声認識の利用許可を求める。
    static func requestAuthorization() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    /// 音声ファイルを認識し、フィラー区間を返す。
    static func detect(
        url: URL,
        locale: Locale = Locale(identifier: "ja-JP"),
        words fillerWords: [String] = defaultWords,
        padding: Double = 0.02
    ) async throws -> Result {
        guard await requestAuthorization() else { throw Failure.notAuthorized }

        guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
            throw Failure.unavailable
        }

        let request = SFSpeechURLRecognitionRequest(url: url)
        request.shouldReportPartialResults = false
        request.addsPunctuation = true
        // 端末内で処理する（通信せず、長さの制限も受けにくい）
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        let transcription = try await recognize(recognizer: recognizer, request: request)

        let words = transcription.segments.map {
            Word(
                text: $0.substring,
                start: $0.timestamp,
                end: $0.timestamp + $0.duration
            )
        }

        return Result(
            fillers: match(words: words, fillerWords: fillerWords, padding: padding),
            words: words,
            transcript: transcription.formattedString
        )
    }

    private static func recognize(
        recognizer: SFSpeechRecognizer,
        request: SFSpeechURLRecognitionRequest
    ) async throws -> SFTranscription {
        try await withCheckedThrowingContinuation { continuation in
            var finished = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !finished else { return }
                if let error {
                    finished = true
                    continuation.resume(throwing: Failure.recognitionFailed(error.localizedDescription))
                } else if let result, result.isFinal {
                    finished = true
                    continuation.resume(returning: result.bestTranscription)
                }
            }
        }
    }

    // MARK: - 照合

    /// 比較用にテキストを正規化する（記号を落とし、長音を揃える）。
    static func normalize(_ text: String) -> String {
        let stripped = text.unicodeScalars.filter { scalar in
            !CharacterSet.whitespacesAndNewlines.contains(scalar)
                && !CharacterSet.punctuationCharacters.contains(scalar)
                && !CharacterSet.symbols.contains(scalar)
                && !"、。，．！？「」『』…・".unicodeScalars.contains(scalar)
        }
        return String(String.UnicodeScalarView(stripped))
            .replacingOccurrences(of: "〜", with: "ー")
            .replacingOccurrences(of: "~", with: "ー")
            .lowercased()
    }

    /// 連続する単語をつなげてフィラーと照合する（最長一致・非重複）。
    static func match(words: [Word], fillerWords: [String], padding: Double) -> [Segment] {
        let targets = Set(fillerWords.map(normalize).filter { !$0.isEmpty })
        guard let maxLength = targets.map(\.count).max(), !words.isEmpty else { return [] }

        let normalized = words.map { normalize($0.text) }
        var cuts: [Segment] = []
        var index = 0

        while index < words.count {
            var joined = ""
            var matchEnd: Int?

            for candidate in index..<words.count {
                joined += normalized[candidate]
                if joined.count > maxLength { break }
                if targets.contains(joined) {
                    matchEnd = candidate + 1   // より長い一致があれば上書きされる
                }
            }

            guard let end = matchEnd else {
                index += 1
                continue
            }

            cuts.append(
                Segment(
                    max(0, words[index].start - padding),
                    words[end - 1].end + padding
                )
            )
            index = end
        }

        return SegmentMath.merge(cuts)
    }
}

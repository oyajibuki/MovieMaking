import Foundation

/// カット後のタイミングに合わせた字幕（SRT）を書き出す。
enum SubtitleWriter {

    struct Line {
        var start: Double
        var end: Double
        var text: String
    }

    /// 字幕を編集後のタイムラインへ貼り直す。
    /// カットにまたがる字幕は残った部分だけを詰め、消えた字幕は落とす。
    static func remap(lines: [Line], keeps: [Segment], minimumDuration: Double = 0.15) -> [Line] {
        let mapper = SegmentMath.timeMapper(keeps: keeps)
        var result: [Line] = []

        for line in lines {
            var pieces: [(Double, Double)] = []
            for keep in keeps {
                let overlapStart = max(line.start, keep.start)
                let overlapEnd = min(line.end, keep.end)
                if overlapEnd > overlapStart,
                   let mappedStart = mapper(overlapStart),
                   let mappedEnd = mapper(overlapEnd) {
                    pieces.append((mappedStart, mappedEnd))
                }
            }
            guard let first = pieces.first, let last = pieces.last else { continue }

            var mapped = line
            mapped.start = first.0
            mapped.end = max(last.1, first.0 + minimumDuration)
            result.append(mapped)
        }

        // 直前の字幕と重ならないように終端を詰める
        for index in result.indices.dropLast() where result[index].end > result[index + 1].start {
            result[index].end = max(result[index].start, result[index + 1].start - 0.01)
        }
        return result
    }

    static func srt(from lines: [Line]) -> String {
        var output = ""
        var number = 1
        for line in lines {
            let text = line.text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { continue }
            output += "\(number)\n\(timestamp(line.start)) --> \(timestamp(line.end))\n\(text)\n\n"
            number += 1
        }
        return output
    }

    static func timestamp(_ seconds: Double) -> String {
        let total = max(0, seconds)
        let hours = Int(total) / 3600
        let minutes = (Int(total) % 3600) / 60
        let secs = Int(total) % 60
        let millis = Int((total - floor(total)) * 1000)
        return String(format: "%02d:%02d:%02d,%03d", hours, minutes, secs, millis)
    }

    /// 単語を、間が空いたところで区切って字幕行にまとめる。
    static func lines(
        from words: [FillerDetector.Word],
        maxCharacters: Int = 24,
        gapThreshold: Double = 0.6
    ) -> [Line] {
        var lines: [Line] = []
        var current: Line?

        for word in words {
            guard var line = current else {
                current = Line(start: word.start, end: word.end, text: word.text)
                continue
            }
            let gap = word.start - line.end
            if gap > gapThreshold || line.text.count + word.text.count > maxCharacters {
                lines.append(line)
                current = Line(start: word.start, end: word.end, text: word.text)
            } else {
                line.end = word.end
                line.text += word.text
                current = line
            }
        }
        if let line = current { lines.append(line) }
        return lines
    }
}

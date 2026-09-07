import Foundation

/// 時間の区間（秒）。カット区間にも残す区間にも使う。
struct Segment: Equatable, Hashable {
    var start: Double
    var end: Double

    var duration: Double { max(0, end - start) }

    init(_ start: Double, _ end: Double) {
        self.start = start
        self.end = end
    }
}

/// 区間の集合演算。Python 版 audio_analyzer.py の移植で、
/// 無音・フィラーの検出結果からカット後のタイムラインを組み立てる。
enum SegmentMath {

    /// 重なった、または gap 秒以内で隣接する区間をまとめ、昇順に整列する。
    static func merge(_ segments: [Segment], gap: Double = 0) -> [Segment] {
        let ordered = segments.filter { $0.end > $0.start }.sorted { $0.start < $1.start }
        guard var current = ordered.first else { return [] }

        var merged: [Segment] = []
        for segment in ordered.dropFirst() {
            if segment.start <= current.end + gap {
                current.end = max(current.end, segment.end)
            } else {
                merged.append(current)
                current = segment
            }
        }
        merged.append(current)
        return merged
    }

    /// カット区間の前後に margin 秒の余白を残す（＝カット区間を内側に縮める）。
    /// ブツ切り感を防ぐための処理。縮めて消える区間は捨てる。
    static func applyMargin(_ cuts: [Segment], margin: Double) -> [Segment] {
        guard margin > 0 else { return merge(cuts) }

        let shrunk = cuts.compactMap { segment -> Segment? in
            let start = segment.start + margin
            let end = segment.end - margin
            return end > start ? Segment(start, end) : nil
        }
        return merge(shrunk)
    }

    /// 全長からカット区間を差し引いて「残す区間」を作る。
    static func keepSegments(
        totalDuration: Double,
        cuts: [Segment],
        minimumKeep: Double = 0.1
    ) -> [Segment] {
        var keeps: [Segment] = []
        var cursor: Double = 0

        for cut in merge(cuts) {
            let start = min(max(cut.start, 0), totalDuration)
            let end = min(max(cut.end, 0), totalDuration)
            if start > cursor {
                keeps.append(Segment(cursor, start))
            }
            cursor = max(cursor, end)
        }
        if cursor < totalDuration {
            keeps.append(Segment(cursor, totalDuration))
        }

        return keeps.filter { $0.duration >= minimumKeep }
    }

    static func totalDuration(_ segments: [Segment]) -> Double {
        segments.reduce(0) { $0 + $1.duration }
    }

    /// 元の時刻を編集後の時刻に移す。カットされた時刻には nil を返す。
    static func timeMapper(keeps: [Segment]) -> (Double) -> Double? {
        var offsets: [(segment: Segment, newStart: Double)] = []
        var elapsed: Double = 0
        for keep in keeps {
            offsets.append((keep, elapsed))
            elapsed += keep.duration
        }

        return { time in
            for entry in offsets where entry.segment.start <= time && time <= entry.segment.end {
                return entry.newStart + (time - entry.segment.start)
            }
            return nil
        }
    }
}

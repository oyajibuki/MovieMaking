import SwiftUI

/// カットされた場所を一目で見せる帯。
/// 数字の一覧より、どこが消えるかを直感的に掴める。
struct TimelineView: View {
    var keeps: [Segment]
    var totalDuration: Double

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                // 背景 = カットされる部分
                RoundedRectangle(cornerRadius: 6)
                    .fill(Theme.cut.opacity(0.45))

                // 残る部分を重ねる
                ForEach(Array(keeps.enumerated()), id: \.offset) { _, keep in
                    let width = geometry.size.width * (keep.duration / max(totalDuration, 0.001))
                    let offset = geometry.size.width * (keep.start / max(totalDuration, 0.001))
                    RoundedRectangle(cornerRadius: 3)
                        .fill(Theme.keep)
                        .frame(width: max(width, 1))
                        .offset(x: offset)
                }
            }
        }
        .frame(height: 28)
    }
}

struct TimelineLegend: View {
    var body: some View {
        HStack(spacing: 16) {
            label(color: Theme.keep, text: "残る")
            label(color: Theme.cut.opacity(0.45), text: "カット")
            Spacer()
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func label(color: Color, text: String) -> some View {
        HStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 3).fill(color).frame(width: 14, height: 14)
            Text(text)
        }
    }
}

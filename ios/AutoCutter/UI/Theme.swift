import SwiftUI

/// 画面全体で使う色と間隔。指で扱いやすいサイズに寄せている。
enum Theme {
    static let accent = Color(red: 0.42, green: 0.36, blue: 0.98)
    static let cut = Color(red: 0.95, green: 0.35, blue: 0.42)
    static let keep = Color(red: 0.30, green: 0.78, blue: 0.55)
    static let card = Color(white: 0.13)
    static let background = Color(white: 0.07)

    /// 指で押しやすい最小の高さ
    static let buttonHeight: CGFloat = 56
    static let corner: CGFloat = 16
}

/// 主要な操作に使う大きなボタン。
struct PrimaryButton: View {
    var title: String
    var systemImage: String
    var isEnabled: Bool = true
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: systemImage)
                    .font(.system(size: 18, weight: .semibold))
                Text(title)
                    .font(.system(size: 18, weight: .semibold))
            }
            .frame(maxWidth: .infinity)
            .frame(height: Theme.buttonHeight)
            .background(isEnabled ? Theme.accent : Color.gray.opacity(0.3))
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
        }
        .disabled(!isEnabled)
    }
}

struct SecondaryButton: View {
    var title: String
    var systemImage: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                Text(title).font(.system(size: 16, weight: .medium))
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .background(Theme.card)
            .foregroundStyle(.white)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
    }
}

func formatDuration(_ seconds: Double) -> String {
    let total = max(0, seconds)
    let minutes = Int(total) / 60
    let secs = total.truncatingRemainder(dividingBy: 60)
    return minutes > 0
        ? String(format: "%d分%04.1f秒", minutes, secs)
        : String(format: "%.1f秒", secs)
}

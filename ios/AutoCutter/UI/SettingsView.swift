import SwiftUI

/// 設定画面。スライダーを並べるより、まず「強さ」を 3 段階から選べるようにする。
struct SettingsView: View {
    @Binding var settings: CutEngine.Settings
    @Environment(\.dismiss) private var dismiss

    /// カットの強さ。数値が小さいほど多く切る
    private let strengths: [(name: String, detail: String, sensitivity: Double)] = [
        ("しっかり切る", "テンポ重視。間が短くなる", 12),
        ("標準", "迷ったらこれ", 16),
        ("控えめ", "自然さ重視。切りすぎを防ぐ", 22),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("カットするもの") {
                    Toggle("無音をカット", isOn: $settings.removeSilence)
                    Toggle("「えー」「あのー」をカット", isOn: $settings.removeFillers)
                }

                Section {
                    ForEach(strengths, id: \.name) { item in
                        Button {
                            settings.sensitivity = item.sensitivity
                        } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.name).foregroundStyle(.primary)
                                    Text(item.detail)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                if settings.sensitivity == item.sensitivity {
                                    Image(systemName: "checkmark")
                                        .foregroundStyle(Theme.accent)
                                }
                            }
                        }
                    }
                } header: {
                    Text("カットの強さ")
                } footer: {
                    Text("録音の音量に合わせて自動で調整されます。小さい声で録った動画でも、話している部分を切りすぎません。")
                }

                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 10) {
                            ForEach(VoiceChanger.presets) { preset in
                                Button {
                                    settings.voicePreset = preset
                                } label: {
                                    VStack(spacing: 6) {
                                        Text(preset.emoji).font(.system(size: 26))
                                        Text(preset.name)
                                            .font(.caption2)
                                            .foregroundStyle(.primary)
                                    }
                                    .frame(width: 78, height: 74)
                                    .background(
                                        settings.voicePreset == preset
                                            ? Theme.accent.opacity(0.35) : Theme.card
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                } header: {
                    Text("声を変える")
                } footer: {
                    Text("身バレを防ぎたいときに使います。話す速さは変わりません。")
                }

                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text("カット前後の余白")
                            Spacer()
                            Text("\(Int(settings.margin * 1000)) ミリ秒")
                                .foregroundStyle(.secondary)
                        }
                        Slider(value: $settings.margin, in: 0...0.3, step: 0.01)
                            .tint(Theme.accent)
                    }
                } footer: {
                    Text("大きくするとブツ切り感が減りますが、カットされる量は少なくなります。")
                }
            }
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完了") { dismiss() }
                }
            }
        }
    }
}

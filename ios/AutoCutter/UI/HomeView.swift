import AVKit
import PhotosUI
import SwiftUI

struct HomeView: View {
    @StateObject private var engine = CutEngine()

    @State private var pickerItem: PhotosPickerItem?
    @State private var videoURL: URL?
    @State private var analysis: CutEngine.Analysis?
    @State private var settings = CutEngine.Settings()

    @State private var phase: Phase = .idle
    @State private var errorMessage: String?
    @State private var exportedURL: URL?
    @State private var showSettings = false
    @State private var showSaved = false

    enum Phase {
        case idle, loading, analyzing, ready, exporting, done
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    if let videoURL {
                        preview(url: videoURL)
                    } else {
                        emptyState
                    }

                    if phase == .analyzing || phase == .exporting {
                        progressCard
                    }

                    if let analysis, phase == .ready || phase == .done || phase == .exporting {
                        resultCard(analysis)
                    }

                    if let exportedURL, phase == .done {
                        exportedCard(url: exportedURL)
                    }

                    actionButtons
                }
                .padding(16)
            }
            .background(Theme.background)
            .navigationTitle("AutoCutter")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: {
                        Image(systemName: "slider.horizontal.3")
                    }
                }
            }
            .sheet(isPresented: $showSettings) {
                SettingsView(settings: $settings)
            }
            .alert("エラー", isPresented: .constant(errorMessage != nil)) {
                Button("OK") { errorMessage = nil }
            } message: {
                Text(errorMessage ?? "")
            }
            .alert("写真に保存しました", isPresented: $showSaved) {
                Button("OK") {}
            } message: {
                Text("CapCut などのアプリから読み込めます。")
            }
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task { await load(item) }
        }
    }

    // MARK: - 画面の部品

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "scissors")
                .font(.system(size: 44))
                .foregroundStyle(Theme.accent)
            Text("動画の間を自動でカット")
                .font(.system(size: 20, weight: .bold))
            Text("無音と「えー」「あのー」を自動で削って、\nCapCut に渡せる状態にします。")
                .font(.system(size: 14))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 44)
        .background(Theme.card)
        .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
    }

    private func preview(url: URL) -> some View {
        VideoPlayer(player: AVPlayer(url: url))
            .frame(height: 220)
            .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
    }

    private var progressCard: some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                Text(engine.statusMessage)
                    .font(.system(size: 15, weight: .medium))
                ProgressView(value: engine.progress)
                    .tint(Theme.accent)
            }
        }
    }

    private func resultCard(_ analysis: CutEngine.Analysis) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("カット結果").font(.system(size: 16, weight: .bold))
                    Spacer()
                    Text("-\(Int(analysis.removedRatio * 100))%")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Theme.keep)
                }

                TimelineView(keeps: analysis.keeps, totalDuration: analysis.originalDuration)
                TimelineLegend()

                HStack(spacing: 0) {
                    stat("元の長さ", formatDuration(analysis.originalDuration))
                    stat("編集後", formatDuration(analysis.newDuration))
                    stat("カット", "\(analysis.cutCount) 箇所")
                }

                if analysis.removedRatio > 0.6 {
                    Label(
                        "6割以上カットされています。設定の「カットの強さ」を弱めてみてください。",
                        systemImage: "exclamationmark.triangle.fill"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }

                if !analysis.transcript.isEmpty {
                    DisclosureGroup("認識された内容") {
                        Text(analysis.transcript)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .padding(.top, 6)
                    }
                    .font(.system(size: 14, weight: .medium))
                }
            }
        }
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(spacing: 4) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.system(size: 15, weight: .semibold))
        }
        .frame(maxWidth: .infinity)
    }

    private func exportedCard(url: URL) -> some View {
        Card {
            VStack(spacing: 12) {
                Label("書き出しました", systemImage: "checkmark.circle.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Theme.keep)
                    .frame(maxWidth: .infinity, alignment: .leading)

                SecondaryButton(title: "写真に保存", systemImage: "square.and.arrow.down") {
                    Task { await saveToPhotos(url) }
                }
                ShareLink(item: url) {
                    HStack(spacing: 8) {
                        Image(systemName: "square.and.arrow.up")
                        Text("他のアプリに送る").font(.system(size: 16, weight: .medium))
                    }
                    .frame(maxWidth: .infinity)
                    .frame(height: 48)
                    .background(Theme.card)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
        }
    }

    private var actionButtons: some View {
        VStack(spacing: 12) {
            PhotosPicker(selection: $pickerItem, matching: .videos) {
                HStack(spacing: 10) {
                    Image(systemName: videoURL == nil ? "photo.badge.plus" : "arrow.triangle.2.circlepath")
                    Text(videoURL == nil ? "動画を選ぶ" : "別の動画を選ぶ")
                        .font(.system(size: 18, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .frame(height: Theme.buttonHeight)
                .background(videoURL == nil ? Theme.accent : Theme.card)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: Theme.corner, style: .continuous))
            }

            if videoURL != nil && analysis == nil {
                PrimaryButton(
                    title: "自動でカットする",
                    systemImage: "wand.and.stars",
                    isEnabled: phase == .idle || phase == .ready
                ) {
                    Task { await runAnalysis() }
                }
            }

            if analysis != nil && phase != .exporting {
                PrimaryButton(title: "書き出す", systemImage: "square.and.arrow.down.fill") {
                    Task { await runExport() }
                }
            }
        }
    }

    // MARK: - 処理

    private func load(_ item: PhotosPickerItem) async {
        phase = .loading
        analysis = nil
        exportedURL = nil

        do {
            guard let movie = try await item.loadTransferable(type: VideoFile.self) else {
                throw NSError(
                    domain: "AutoCutter", code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "動画を読み込めませんでした。"]
                )
            }
            videoURL = movie.url
            phase = .idle
        } catch {
            errorMessage = error.localizedDescription
            phase = .idle
        }
    }

    private func runAnalysis() async {
        guard let videoURL else { return }
        phase = .analyzing
        do {
            analysis = try await engine.analyze(url: videoURL, settings: settings)
            phase = .ready
        } catch {
            errorMessage = error.localizedDescription
            phase = .idle
        }
    }

    private func runExport() async {
        guard let videoURL, let analysis else { return }
        phase = .exporting
        do {
            exportedURL = try await engine.export(
                url: videoURL, analysis: analysis, settings: settings
            )
            phase = .done
        } catch {
            errorMessage = error.localizedDescription
            phase = .ready
        }
    }

    private func saveToPhotos(_ url: URL) async {
        do {
            try await PhotoLibrary.saveVideo(url)
            showSaved = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

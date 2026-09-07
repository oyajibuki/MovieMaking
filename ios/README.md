# AutoCutter for iOS

iPhone で撮った動画の「間」を自動でカットし、CapCut や Filmora に渡すための
下ごしらえをするアプリ。**アップロードせず、端末内だけで完結する。**

## Mac 版との違い

| | Mac 版（Python） | iOS 版（Swift） |
|---|---|---|
| 動画カット | moviepy + ffmpeg（CPU） | AVFoundation（ハードウェア支援） |
| 無音検知 | pydub | AVAudioFile + Accelerate |
| 音声認識 | Whisper | Speech framework（端末内） |
| ピッチ変更 | librosa | AVAudioUnitTimePitch |
| 通信 | サーバーへアップロード | **なし（端末内で完結）** |

カット判定のアルゴリズムは Mac 版と同じものを移植している。
無音の閾値は素材の平均音量から自動で決めるので、小さい声で録った動画でも
話している部分を切りすぎない。

## ビルド

```bash
cd ios
xcodegen generate
xcodebuild -project AutoCutter.xcodeproj -scheme AutoCutter \
  -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build
```

`.xcodeproj` は `project.yml` から生成するため git 管理外。
Xcode で開く場合も `xcodegen generate` を先に実行する。

## 構成

```
AutoCutter/
├── AutoCutterApp.swift
├── Core/
│   ├── Segment.swift          区間の集合演算（Mac 版 audio_analyzer の移植）
│   ├── SilenceDetector.swift  無音検知（音量に応じて閾値を自動調整）
│   ├── FillerDetector.swift   フィラー検知（分割された認識結果にも対応）
│   ├── VideoEditor.swift      カット・結合・書き出し
│   ├── VoiceChanger.swift     声色変換（目標の声の高さで指定）
│   ├── SubtitleWriter.swift   字幕のリマップと SRT 出力
│   ├── CutEngine.swift        解析から書き出しまでの流れ
│   ├── VideoFile.swift        写真ライブラリからの読み込み
│   └── PhotoLibrary.swift     写真アプリへの保存
└── UI/
    ├── HomeView.swift         メイン画面
    ├── SettingsView.swift     設定
    ├── TimelineView.swift     カット箇所の可視化
    └── Theme.swift            配色と共通部品
```

## 動作確認済み

シミュレータ（iPhone 17 Pro / iOS 26.5）で、動画選択 → 自動カット →
書き出し → 写真に保存までを確認。15.2 秒のテスト動画が 8.5 秒（-44%、
無音 3 箇所）になった。

## 未実装 / 制限

- **実機での確認はまだ**（シミュレータのみ）
- フォルマント変換は未移植（現在はピッチのみ。Mac 版には実装済み）
- AI 声質変換（seed-vc）は未対応。Core ML 化が必要
- 字幕（SRT）の書き出し UI は未実装（ロジックは実装済み）
- 共有シートからの起動（Share Extension）は未実装
- App Store 配布には Apple Developer Program（年 99 ドル）が必要

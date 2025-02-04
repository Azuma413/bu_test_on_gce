# Browser Automation with WebRTC Streaming

このプロジェクトは、Google Cloud Engine上の仮想ディスプレイでブラウザを自動操作し、その画面をWebRTCでUnityにリアルタイムストリーミングするシステムです。

## 必要要件

### Python側（GCE）
- Python 3.8以上
- 必要なPythonパッケージ:
  - pyvirtualdisplay
  - mss
  - aiortc
  - aiohttp
  - av
  - python-dotenv
  - browser_use（既存ライブラリ）
  - numpy

### Unity側
- Unity 2020.3以上
- Unity WebRTC パッケージ
- Newtonsoft.Json パッケージ

## セットアップ手順

1. GCE側のセットアップ:
```bash
# 必要なパッケージのインストール
pip install pyvirtualdisplay mss aiortc aiohttp av python-dotenv numpy
pip install browser-use
# 仮想ディスプレイの依存パッケージをインストール（Ubuntu/Debian の場合）
sudo apt-get update
sudo apt-get install -y xvfb
playwright install
```

2. Unity側のセットアップ:
   - Unity Package Manager から WebRTC パッケージをインストール\
https://github.com/Unity-Technologies/com.unity.webrtc/blob/main/Documentation~/install.md

   - プロジェクトに UnityWebRTCClient.cs スクリプトを追加
   - 新しい Scene を作成し、以下の手順で設定:
     1. 空の GameObject を作成し、UnityWebRTCClient スクリプトをアタッチ
     2. UI > Raw Image を作成し、これを UnityWebRTCClient の Display Image にアサイン

## 使用方法

1. GCE側でWebRTCサーバーを起動:
```bash
python webrtc_browser_stream.py
```

2. Unity側:
   - プロジェクトを実行すると、自動的にGCE側のブラウザ画面のストリーミングが開始されます
   - Raw Image コンポーネントに仮想ディスプレイの映像が表示されます

## 実装の詳細

### webrtc_browser_stream.py
- 仮想ディスプレイの作成と管理
- ブラウザの自動操作（browser_useライブラリを使用）
- 画面キャプチャとWebRTCストリーミング
- シグナリングサーバーの実装

### UnityWebRTCClient.cs
- WebRTC接続の確立
- ビデオストリームの受信と表示
- シグナリングの処理

## 注意事項

- GCE上で実行する際は、適切なファイアウォール設定が必要です（ポート8080を開放）
- 環境変数の設定が必要な場合は、.envファイルを使用してください
- Unity WebRTCパッケージのバージョンに注意してください

## エラー対処

1. 接続エラーの場合:
   - GCEのファイアウォール設定を確認
   - ポート8080が利用可能か確認
   - STUN/TURNサーバーの設定を確認\
   [こちらのサイト](https://www.checkmynat.com/)でNATの種類を調べることができる．\
   Symmetric NATでなければ，おそらくTURNサーバは必要ない．

2. 画面キャプチャエラーの場合:
   - 仮想ディスプレイ（Xvfb）が正常に起動しているか確認
   - 画面解像度設定（1280x720）が適切か確認

3. ブラウザ操作エラーの場合:
   - ChromeのパスとバージョンがGCE環境に適合しているか確認
   - browser_useライブラリの設定を確認

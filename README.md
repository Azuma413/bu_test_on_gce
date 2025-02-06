# Browser Automation with WebRTC Streaming

このプロジェクトは、Google Cloud Engine上の仮想ディスプレイでブラウザを自動操作し、その画面をWebRTCでUnityにリアルタイムストリーミングするシステムです。

## フォルダ構造

```
bu_test_on_gce/
├── cert/                # SSL証明書関連
│   └── generate_cert.py # 証明書生成スクリプト
├── webrtc_test.py      # メインのPythonサーバー実装
├── WebRTCClient.cs     # Unityクライアント実装
├── .env_dumy           # 環境変数テンプレート
.
.
.
```

## 必要要件
## セットアップ手順

1. GCE側のセットアップ:
```bash
# 仮想ディスプレイの依存パッケージをインストール（Ubuntu/Debian の場合）
sudo apt update
sudo apt install xvfb git fonts-dejavu xdotool -y
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/Azuma413/bu_test_on_gce.git
```
ライブラリのインストール
```bash
uv sync
```
Chromeのインストール
```bash
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install ./google-chrome-stable_current_amd64.deb
```

2. Unity側のセットアップ:
   - Unity Package Manager から WebRTC パッケージをインストール\
https://github.com/Unity-Technologies/com.unity.webrtc/blob/main/Documentation~/install.md

   - プロジェクトにWebRTCClient.cs スクリプトを追加
   - GameObjectにWebRTCClient スクリプトをアタッチ
   - UI > Raw Image を作成し、これを UnityWebRTCClient の Display Image にアサイン

3. SSL証明書の生成:
```bash
cd cert
python generate_cert.py
```

## 使用方法
1. GCE側でWebRTCサーバーを起動:
```bash
xvfb-run uv run webrtc_test.py
```
xvfb-runは仮想ディスプレイ用

2. Unity側:
   - プロジェクトを実行すると、Raw Image コンポーネントに仮想ディスプレイの映像が表示される

## 実装の詳細

### webrtc_test.py
- 仮想ディスプレイの作成と管理
- ブラウザの自動操作（browser_useライブラリとGPT-4を使用）
- 画面キャプチャ（1280x825）とWebRTCストリーミング
- SSL対応シグナリングサーバーの実装（ポート8443）

### WebRTCClient.cs
- WebRTC接続の確立
- ビデオストリームの受信と表示
- シグナリングの処理

## 注意事項

- GCE上で実行する際は、適切なファイアウォール設定が必要（ポート8443を開放）
- .envファイルにOpenAI APIキーを設定する必要あり
- SSL証明書の生成が必要

# ONVIF Profile T Simulator

これはPythonで書かれたシンプルなONVIF Profile T対応のシミュレーターです。
物理的なカメラデバイスがなくても、VMS（ビデオ管理システム）などのONVIFクライアントのテストができるように、Profile Tの必須機能をエミュレートします。

SOAPコマンドの送受信を簡単にテストできる、Webベースのテストインターフェースも内蔵しています。

## 主な機能

- **デバイス発見**: WS-Discoveryによるデバイスの発見に応答します。
- **SOAPサービス**: 以下のProfile T必須サービスをシミュレートします。
  - **Device**: `GetCapabilities`, `GetDeviceInformation`
  - **Media**: `GetProfiles`, `GetStreamUri`
  - **PTZ**: `GetNodes`, `GetStatus`, `AbsoluteMove`, `ContinuousMove`, `Stop`
  - **Imaging**: `GetImagingSettings`, `SetImagingSettings`
  - **Events**: `CreatePullPointSubscription`, `PullMessages` （30秒ごとのモーション検知イベントを模擬）
- **外部RTSPストリーム連携**: 任意の外部RTSPサーバーのストリームURLをクライアントに提供します。
- **WebテストUI**: `http://<IP>:8080/` でアクセスできるテストページから、各種ONVIFコマンドを送信し、その応答を確認できます。
- **設定の外部化**: デバイスのメーカー名やモデル名などの情報は `device_info.json` ファイルで簡単に変更できます。

## 必要なもの

- Python 3.x
- 外部で動作しているRTSPストリーム（実際のカメラ、VLC、または専用のRTSPサーバーなど）

## インストール

必要なPythonパッケージをインストールします。

```bash
pip install -r requirements.txt
```

## 使い方

### 1. RTSPサーバーの準備

まず、シミュレーターがクライアントに提供するためのRTSPストリームを、ネットワーク上で利用可能な状態にしておきます。

### 2. シミュレーターの起動

ターミナルで以下のコマンドを実行します。引数として、外部RTSPサーバーの完全なURLを指定してください。

IPアドレスは自動的に検出されますが、`--ip`オプションで明示的に指定することも可能です。

```bash
# 基本的な起動方法 (IPアドレスは自動検出)
python onvif_profile_t_simulator.py <FULL_RTSP_URL>

# 実行例:
python onvif_profile_t_simulator.py rtsp://localhost:8554/stream_test
```

オプションで、SOAPサービスのポートやデバイス情報ファイルを変更することもできます。

```bash
python onvif_profile_t_simulator.py rtsp://... --soap-port 8000 --device-info my_camera.json
```

### 3. (任意) HTTPS用の自己署名証明書の生成
  HTTPSを有効にしてシミュレーターを起動する場合、SSL証明書が必要です。以下のコマンドでテスト用の自己署名証明書 (cert.pem, key.pem) を生成できます。 + +bash +openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365 

### 4. テストページの利用

Webブラウザで `http://<YOUR_IP_ADDRESS>:8080` にアクセスすると、テストページが表示されます。
このページから各ONVIFコマンドを送信し、リクエストとレスポンスの内容をリアルタイムで確認できます。

## 設定

シミュレーターが応答するメーカー名やモデル名などのデバイス情報は、`device_info.json` ファイルを編集することで簡単に変更できます。

```json
{
    "Manufacturer": "My Camera Corp.",
    "Model": "SuperCam-3000",
    "FirmwareVersion": "2.5.1",
    "HardwareId": "rev-b-2024"
}
```

## プロジェクト構成

```
.
├── onvif_profile_t_simulator.py  # メインのシミュレータープログラム
├── templates/
│   └── index.html                # WebテストページのHTMLテンプレート
├── device_info.json              # 設定可能なデバイス情報ファイル
├── requirements.txt              # 依存パッケージリスト
└── .gitignore                    # Gitの追跡対象外ファイルリスト
```
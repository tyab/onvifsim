# ONVIF Profile T Simulator & Test Client

これはPythonで書かれたシンプルなONVIF Profile T対応のシミュレーターです。
物理的なカメラデバイスがなくても、VMS（ビデオ管理システム）などのONVIFクライアントのテストができるように、Profile Tの必須機能をエミュレートします。

## 主な機能

- **デバイス発見**: WS-Discoveryによるデバイスの発見に応答します。
- **SOAPサービス**: 以下のProfile T必須サービスをシミュレートします。
  - **Device**: `GetCapabilities`, `GetDeviceInformation` など
  - **Media**: `GetProfiles`, `GetStreamUri` など
  - **PTZ**: `AbsoluteMove`, `ContinuousMove`, `Stop`, `GetStatus` など
  - **Imaging**: `GetImagingSettings`, `SetImagingSettings` など
  - **Events**: `CreatePullPointSubscription`, `PullMessages` （モーション検知イベントを模擬）
- **外部RTSPストリーム連携**: 任意の外部RTSPサーバーのストリームURLをクライアントに提供します。
- **WebテストUI**: `http://<IP>:8080/` でアクセスできるテストページから、シミュレーターまたは実機のカメラに対して各種ONVIFコマンドを送信し、その応答を確認できます。
- **CORSプロキシ**: テストUIから実機のカメラへ接続する際に発生するブラウザのセキュリティ制限（CORS）を回避するためのプロキシサーバー (`proxy.py`) を同梱しています。

## 動作要件

- Python 3.7以上

## インストール

シミュレーターとプロキシサーバーに必要なPythonパッケージをインストールします。

```bash
pip3 install -r requirements.txt
pip3 install Flask requests Flask-Cors
```

## 使い方

### 1. ONVIFシミュレーター & Webテストクライアントの起動

シミュレーター (`onvif_profile_t_simulator.py`) を実行すると、Webテストページが `http://<IPアドレス>:8080` で利用可能になります。

```bash
python3 onvif_profile_t_simulator.py
```

PCに複数のネットワーク接続がある場合は、`--ip`オプションで使用するIPアドレスを明示的に指定してください。

```bash
# 例: 192.168.1.30 のネットワークインターフェースを使用する場合
python3 onvif_profile_t_simulator.py --ip 192.168.1.30
```

### 2. 高度な使い方 (Unity連携)

Unityと連携して仮想PTZカメラを構築する手順については、[Unity/README.md](Unity/README.md)を参照してください。

### 3. プロキシサーバーの起動 (実機カメラ接続時)

テストクライアントから実機の監視カメラに接続する場合、ブラウザのセキュリティポリシー (CORS) により直接通信ができません。この問題を回避するため、リクエストを中継するプロキシサーバー (proxy.py) を起動する必要があります。

```bash
# プロキシサーバーを起動 (通常はポート8081で起動) 
python3 proxy.py
```

### 4. Webテストページ

Webブラウザで `http://<YOUR_IP_ADDRESS>:8080` にアクセスすると、テストページが表示されます。
このページから各ONVIFコマンドを送信し、リクエストとレスポンスの内容をリアルタイムで確認できます。

## コマンドラインオプション

```
usage: onvif_profile_t_simulator.py [-h] [--rtsp-url RTSP_URL] [--ip IP] [--device-info DEVICE_INFO] [--soap-port SOAP_PORT] [--https] [--enable-ptz-forwarding] [--ptz-forwarding-address PTZ_FORWARDING_ADDRESS]

optional arguments:
  -h, --help                    show this help message and exit
  --rtsp-url RTSP_URL           外部RTSPサーバーのURL。指定しない場合、ストリームURIは空になります。
  --ip IP                       シミュレーターをバインドするサーバーのIPアドレス (未指定の場合は自動検出)
  --device-info DEVICE_INFO     デバイス情報JSONファイルのパス (default: device_info.json)
  --soap-port SOAP_PORT         SOAPサービス用のポート番号 (デフォルト: 8080)
  --https                       HTTPSを有効にする (cert.pemとkey.pemが必要)
  --enable-ptz-forwarding       PTZコマンドをUDPで転送する機能を有効にする
  --ptz-forwarding-address PTZ_FORWARDING_ADDRESS
                                PTZコマンドの転送先アドレス (IP:PORT) (default: 127.0.0.1:50001)
```

## プロジェクト構成

```
.
├── onvif_profile_t_simulator.py  # メインのシミュレータープログラム
├── templates/
│   └── index.html                # WebテストページのHTMLテンプレート
├── proxy.py                      # 実機接続用の中継プロキシ
├── device_info.json              # 設定可能なデバイス情報ファイル
├── requirements.txt              # 依存パッケージリスト
└── .gitignore                    # Gitの追跡対象外ファイルリスト
```
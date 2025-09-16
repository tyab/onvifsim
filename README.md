# ONVIF Profile T Simulator (with Unity Integration)

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
- **WebテストUI**: `http://<IP>:8080/` でアクセスできるテストページから、各種ONVIFコマンドを送信し、その応答を確認できます。
- **Unity連携**: Unityと連携し、仮想PTZカメラを構築できます。詳細は [Unity/README.md](Unity/README.md) を参照してください。

## 動作要件

- Python 3.7以上

## インストール

必要なPythonパッケージをインストールします。

```bash
pip install -r requirements.txt
```

## 使い方

### 基本的な使い方 (スタンドアロン)

シミュレーターを単体で起動します。RTSPストリームのURLはオプションです。

```bash
# RTSPストリームを指定して起動
python onvif_profile_t_simulator.py --rtsp-url rtsp://127.0.0.1:8554/mystream

# RTSPストリームなしで起動（PTZやイベント機能のテスト用）
python onvif_profile_t_simulator.py
```

### 高度な使い方 (Unity連携)

Unityと連携して仮想PTZカメラを構築する手順については、[Unity/README.md](Unity/README.md)を参照してください。

### Webテストページ

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
├── device_info.json              # 設定可能なデバイス情報ファイル
├── requirements.txt              # 依存パッケージリスト
└── .gitignore                    # Gitの追跡対象外ファイルリスト
```
# ONVIF Profile T Simulator

これは、ONVIF Profile Tの主要な機能をシミュレートするPython製のサーバーです。
VMS（ビデオ管理システム）やONVIFクライアントの開発・テスト用に、物理的なカメラなしでONVIFデバイスの動作を模倣することを目的としています。

さらに、Unityなどの3Dエンジンと連携し、仮想空間内のカメラをONVIF経由でPTZ操作する高度なシミュレーションにも対応しています。

## 主な機能

*   **WS-Discovery**: ネットワーク上でONVIFデバイスとして探索可能。
*   **Device Service**: `GetCapabilities`, `GetDeviceInformation` などの基本的なデバイス情報を提供。
*   **Media Service**: H.265エンコーディングプロファイルとRTSPストリームURIを提供 (`GetProfiles`, `GetStreamUri`)。
*   **PTZ Service**:
    *   `AbsoluteMove`: 指定した座標への移動。
    *   `ContinuousMove`: 連続的なパン・チルト・ズーム操作。
    *   `Stop`: 移動の停止。
    *   `GetStatus`: 現在のPTZ位置情報の提供。
*   **Imaging Service**: 明るさ、コントラスト、彩度の設定・取得 (`GetImagingSettings`, `SetImagingSettings`)。
*   **Event Service**: `CreatePullPointSubscription` と `PullMessages` をサポートし、モーション検知イベントを定期的に発行。
*   **Unity連携**:
    *   PTZコマンドをUDPでUnityに転送。
    *   Unity内の仮想カメラから現在位置のフィードバックを受信し、`GetStatus` に反映。

## 動作要件

*   Python 3.7以上
*   Flask
*   ws-discovery
*   (オプション) Unity 2019.4 LTS 以降
*   (オプション) FFmpeg

## インストール

必要なPythonパッケージをインストールします。

```bash
pip install Flask ws-discovery
```

## 基本的な使い方

シミュレーターは、外部で実行されているRTSPサーバーのURLを引数として受け取ります。
テスト用に、VLCやFFmpegなどでRTSPストリームを配信してください。

```bash
# 例: VLCでデスクトップをストリーミングし、そのURLをシミュレーターに渡す
python onvif_profile_t_simulator.py rtsp://127.0.0.1:8554/mystream
```

シミュレーターが起動すると、ONVIFクライアントからデバイスとして検出できるようになります。

## Unity連携による仮想PTZカメラの構築

このシミュレーターの最も強力な機能は、Unityと連携して仮想PTZカメラを構築することです。

### アーキテクチャ

3つのコンポーネントが連携して動作します。

1.  **Unity**: 3Dシーンと仮想カメラを管理します。シミュレーターから送られてくるPTZコマンドでカメラを動かし、その映像を画面にレンダリングします。
2.  **FFmpeg**: Unityのゲームウィンドウをリアルタイムでキャプチャし、H.264/H.265にエンコードしてRTSPストリームとして配信します。
3.  **ONVIFシミュレーター (このリポジトリ)**: ONVIFクライアントと他の2つのコンポーネントを仲介します。
    *   ONVIFクライアントにFFmpegが配信するRTSPストリームのURLを教えます。
    *   ONVIFクライアントからのPTZコマンドを解釈し、UDPでUnityに送信します。
    *   Unityから現在のカメラ位置をUDPで受信し、`GetStatus` レスポンスに反映させます。

### セットアップ手順

#### 1. Unityプロジェクトの準備

1.  Unityで新しい3Dプロジェクトを作成します。
2.  シーン内にカメラを配置します。
3.  `PTZController.cs` という名前でC#スクリプトを作成し、リポジトリ内の `Unity/PTZController.cs` の内容をコピー＆ペーストします。
4.  作成した `PTZController.cs` スクリプトを、シーン内のカメラオブジェクトにアタッチします。
5.  カメラを選択し、InspectorウィンドウでPTZの可動範囲や速度などを好みに合わせて調整します。

#### 2. FFmpegによる映像配信の開始

Unityエディタでシーンを再生するか、ビルドしたアプリケーションを実行します。その後、ターミナルで以下のFFmpegコマンドを実行し、Unityの画面をキャプチャしてRTSP配信を開始します。

**macOSの場合:**

```bash
# デスクトップ画面(インデックス1)をキャプチャし、ハードウェアエンコードして配信
ffmpeg -re -f avfoundation -framerate 30 -i "1" -vsync cfr -r 30 -c:v hevc_videotoolbox -b:v 4000k -pix_fmt yuv420p -f rtsp rtsp://127.0.0.1:8554/stream_test
```
> **Note:** `ffmpeg -f avfoundation -list_devices true -i ""` を実行して、キャプチャ対象の画面インデックスを確認してください。

**Windowsの場合:**

```bash
# "Unity"という名前のウィンドウをキャプチャし、ハードウェアエンコードして配信
ffmpeg -re -f gdigrab -framerate 30 -i window=Unity -c:v hevc_nvenc -b:v 4000k -pix_fmt yuv420p -f rtsp rtsp://127.0.0.1:8554/stream_test
```
> **Note:** `hevc_nvenc` はNVIDIA GPU用です。AMDの場合は `hevc_amf`、Intelの場合は `hevc_qsv` を使用してください。

#### 3. ONVIFシミュレーターの起動

最後に、別のターミナルでONVIFシミュレーターを起動します。このとき、`--enable-ptz-forwarding` オプションを必ず指定してください。

```bash
python onvif_profile_t_simulator.py rtsp://127.0.0.1:8554/stream_test --enable-ptz-forwarding
```

これで、ONVIFクライアントから接続すると、Unityの仮想カメラをPTZ操作できるようになります。

## コマンドラインオプション

```
usage: onvif_profile_t_simulator.py [-h] [--ip IP] [--device-info DEVICE_INFO] [--soap-port SOAP_PORT] [--https] [--enable-ptz-forwarding] [--ptz-forwarding-address PTZ_FORWARDING_ADDRESS] rtsp_url

positional arguments:
  rtsp_url                      外部RTSPサーバーの完全なURL (例: rtsp://127.0.0.1:8554/mystream)

optional arguments:
  -h, --help                    show this help message and exit
  --ip IP                       シミュレーターをバインドするサーバーのIPアドレス (未指定の場合は自動検出)
  --device-info DEVICE_INFO     デバイス情報JSONファイルのパス (default: device_info.json)
  --soap-port SOAP_PORT         SOAPサービス用のポート番号 (デフォルト: 8080)
  --https                       HTTPSを有効にする (cert.pemとkey.pemが必要)
  --enable-ptz-forwarding       PTZコマンドをUDPで転送する機能を有効にする
  --ptz-forwarding-address PTZ_FORWARDING_ADDRESS
                                PTZコマンドの転送先アドレス (IP:PORT) (default: 127.0.0.1:50001)
```

### Unity連携時の通信ポート

`--enable-ptz-forwarding` を有効にすると、以下のポートがUDP通信に使用されます。

*   **PTZコマンド転送 (Python -> Unity)**:
    *   デフォルト: `50001`
    *   `--ptz-forwarding-address` で変更可能。
*   **PTZ位置フィードバック (Unity -> Python)**:
    *   固定: `50002`
    *   Unity側の `PTZController.cs` の `feedbackPort` で設定します。

ファイアウォールなどで通信がブロックされないように注意してください。

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

---

**ws-discovery**

このプロジェクトは、ws-discovery ライブラリを利用しています。
Copyright (c) 2014, Christoffer T. Timm
Licensed under the MIT license.
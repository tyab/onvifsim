# Unity連携ガイド

このドキュメントでは、ONVIFシミュレーターとUnityを連携させ、仮想PTZカメラを構築する手順について説明します。

## 動作要件

- Unity 2019.4 LTS 以降
- mediamtx (旧 rtsp-simple-server)
- FFmpeg

## アーキテクチャ

4つのコンポーネントが連携して動作します。

1.  **Unity**: 3Dシーンと仮想カメラを管理します。シミュレーターから送られてくるPTZコマンドでカメラを動かし、その映像を画面にレンダリングします。
2.  **mediamtx (RTSPサーバー)**: FFmpegから送られてくる映像ストリームを受け取り、RTSPプロトコルでクライアントに配信します。
3.  **FFmpeg (エンコーダー/ストリーマー)**: Unityのゲームウィンドウをリアルタイムでキャプチャし、H.264/H.265にエンコードして`mediamtx`に送信します。
4.  **ONVIFシミュレーター (このリポジトリ)**: ONVIFクライアントと他のコンポーネントを仲介します。
    -   ONVIFクライアントに`mediamtx`が配信するRTSPストリームのURLを教えます。
    -   ONVIFクライアントからのPTZコマンドを解釈し、UDPでUnityに送信します。
    -   Unityから現在のカメラ位置をUDPで受信し、`GetStatus` レスポンスに反映させます。

## セットアップ手順

### 1. RTSPサーバーの準備 (mediamtx)

1.  mediamtxのリリースから、お使いのOS用の実行ファイルをダウンロードします。
2.  ターミナルで `mediamtx` を起動します。設定はデフォルトのままで問題ありません。

### 2. Unityプロジェクトの準備

1.  Unityで新しい3Dプロジェクトを作成します。
2.  シーン内にカメラを配置します。
3.  このディレクトリにある `PTZController.cs` スクリプトを、シーン内のカメラオブジェクトにアタッチします。
4.  カメラを選択し、InspectorウィンドウでPTZの可動範囲や速度などを好みに合わせて調整します。

### 3. 映像のRTSP配信 (FFmpeg)

1.  Unityエディタでシーンを再生するか、ビルドしたアプリケーションを実行します。
2.  別のターミナルで以下のFFmpegコマンドを実行し、Unityの画面をキャプチャして`mediamtx`にストリームを送信します。

**macOSの場合:**
```bash
# デスクトップ画面(インデックス1)をキャプチャし、ハードウェアエンコードしてmediamtxに送信
ffmpeg -re -f avfoundation -framerate 30 -i "1" -vsync cfr -r 30 -c:v hevc_videotoolbox -b:v 4000k -pix_fmt yuv420p -f rtsp rtsp://127.0.0.1:8554/stream_test
```
> **Note:** `ffmpeg -f avfoundation -list_devices true -i ""` を実行して、キャプチャ対象の画面インデックスを確認してください。

**Windowsの場合:**
```bash
# "Unity"という名前のウィンドウをキャプチャし、ハードウェアエンコードしてmediamtxに送信
ffmpeg -re -f gdigrab -framerate 30 -i window=Unity -c:v hevc_nvenc -b:v 4000k -pix_fmt yuv420p -f rtsp rtsp://127.0.0.1:8554/stream_test
```
> **Note:** `hevc_nvenc` はNVIDIA GPU用です。AMDの場合は `hevc_amf`、Intelの場合は `hevc_qsv` を使用してください。

### 4. ONVIFシミュレーターの起動

最後に、さらに別のターミナルでONVIFシミュレーターを起動します。このとき、`--enable-ptz-forwarding` オプションと、`mediamtx` が配信するRTSPストリームのURLを必ず指定してください。

```bash
python onvif_profile_t_simulator.py --rtsp-url rtsp://127.0.0.1:8554/stream_test --enable-ptz-forwarding
```

これで、ONVIFクライアントから接続すると、Unityの仮想カメラをPTZ操作できるようになります。

## Unity連携時の通信ポート

`--enable-ptz-forwarding` を有効にすると、以下のポートがUDP通信に使用されます。ファイアウォールなどで通信がブロックされないように注意してください。

- **PTZコマンド転送 (Python -> Unity)**:
  - デフォルト: `50001`
  - シミュレーター起動時に `--ptz-forwarding-address` で変更可能。
- **PTZ位置フィードバック (Unity -> Python)**:
  - デフォルト: `50002`
  - Unity側の `PTZController.cs` の `feedbackPort` で設定します。
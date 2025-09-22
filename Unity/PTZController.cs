// PTZController.cs
using UnityEngine;
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Collections.Concurrent; // ConcurrentQueueのために追加
using System.Threading;

/// <summary>
/// ONVIFシミュレーターから送信されるPTZコマンドをUDPで受信し、
/// このコンポーネントがアタッチされたカメラを制御します。
/// また、現在のカメラの状態をシミュレーターにフィードバックします。
/// </summary>
public class PTZController : MonoBehaviour
{
    // --- Inspectorで設定可能な項目 ---
    [Header("Network Settings")]
    [Tooltip("待機するUDPポート番号")]
    public int listenPort = 50001;

    [Header("Feedback Settings")]
    [Tooltip("PTZ位置のフィードバックを有効にするか")]
    public bool enableFeedback = true;
    [Tooltip("フィードバック送信先のIPアドレス")]
    public string feedbackAddress = "127.0.0.1";
    [Tooltip("フィードバック送信先のポート番号")]
    public int feedbackPort = 50002;
    [Tooltip("フィードバックの送信間隔（秒）")]
    public float feedbackInterval = 0.2f;

    [Header("PTZ Control Ranges")]
    [Tooltip("パン（水平回転）の可動範囲（度）")]
    public Vector2 panRange = new Vector2(-180f, 180f);

    [Tooltip("パンを連続回転させるか")]
    public bool endlessPan = true;

    [Tooltip("チルト（垂直回転）の可動範囲（度）")]
    public Vector2 tiltRange = new Vector2(-90f, 20f);

    [Header("Zoom Settings")]
    [Tooltip("最も広角な状態での水平視野角（Horizontal FOV）")]
    public float wideHorizontalFov = 60f;

    [Tooltip("最大光学ズーム倍率。1.0以上の値を設定してください。")]
    public float maxOpticalZoom = 12f;

    [Header("Continuous Move Speed")]
    [Tooltip("パンの連続移動速度（度/秒）")]
    public float panSpeedMultiplier = 90f;

    [Tooltip("チルトの連続移動速度（度/秒）")]
    public float tiltSpeedMultiplier = 45f;

    [Tooltip("ズームの連続移動速度（FoV/秒）")]
    public float zoomSpeedMultiplier = 30f;

    [Header("Absolute Move Speed")]
    [Tooltip("指定位置への移動（AbsoluteMove）時のパン速度（度/秒）。")]
    public float absolutePanSpeed = 360f;
    [Tooltip("指定位置への移動（AbsoluteMove）時のチルト速度（度/秒）。")]
    public float absoluteTiltSpeed = 120f;
    [Tooltip("指定位置への移動（AbsoluteMove）時のズーム速度（FoV/秒）。")]
    public float absoluteZoomSpeed = 55f;

    [Header("Movement Smoothing")]
    [Tooltip("連続移動（ContinuousMove）時のカメラの追従速度。値が大きいほど速く動きます。")]
    public float continuousSmoothingFactor = 10f;

    // --- 内部変数 ---
    private Thread receiveThread;
    private UdpClient client;
    private Camera controlledCamera;

    // PTZ状態変数
    private Vector3 targetEulerAngles;
    private Vector3 currentEulerAngles; // 実際にカメラに適用される、平滑化された角度
    private Vector2 zoomRange; // wideHorizontalFovとmaxOpticalZoomから計算される内部的なズーム範囲
    private volatile float targetFieldOfView;
    private Vector3 continuousVelocity; // (pan, tilt, zoom) の速度
    private readonly object ptzStateLock = new object();
    private volatile bool isRunning;

    private ConcurrentQueue<string> messageQueue = new ConcurrentQueue<string>(); // 受信メッセージキュー
    // フィードバック用
    private UdpClient feedbackClient;
    private IPEndPoint feedbackEndPoint;
    private float timeSinceLastFeedback = 0f;

    /// <summary>
    /// ONVIFからのPTZコマンドをデシリアライズするためのクラス
    /// </summary>
    [Serializable]
    private class PtzMessage
    {
        public string type;
        public float pan;
        public float tilt;
        public float zoom;
        public float pan_speed;
        public float tilt_speed;
        public float zoom_speed;
    }

    /// <summary>
    /// PTZ状態フィードバック用のクラス
    /// </summary>
    [Serializable]
    private class PtzStatusMessage
    {
        public float pan;
        public float tilt;
        public float zoom;
    }

    void Start()
    {
        controlledCamera = GetComponent<Camera>();
        if (controlledCamera == null)
        {
            Debug.LogError("PTZControllerスクリプトは、Cameraコンポーネントを持つGameObjectにアタッチしてください。");
            this.enabled = false;
            return;
        }

        // Inspectorで設定された値から内部的なズーム範囲を計算
        if (maxOpticalZoom < 1.0f)
        {
            Debug.LogWarning("最大光学ズーム倍率(maxOpticalZoom)は1.0以上である必要があります。1.0に設定します。", this);
            maxOpticalZoom = 1.0f;
        }
        zoomRange = new Vector2(wideHorizontalFov, wideHorizontalFov / maxOpticalZoom);
        Debug.Log($"ズーム範囲を計算しました: 広角端 HFOV={zoomRange.x}°, 望遠端 HFOV={zoomRange.y:F2}° ({maxOpticalZoom}x)", this);

        // 現在のカメラの回転を正規化して初期値として設定
        currentEulerAngles = transform.eulerAngles;
        if (currentEulerAngles.x > 180f) currentEulerAngles.x -= 360f;
        if (currentEulerAngles.y > 180f) currentEulerAngles.y -= 360f;
        if (currentEulerAngles.z > 180f) currentEulerAngles.z -= 360f;

        lock (ptzStateLock)
        {
            targetEulerAngles = currentEulerAngles;
            continuousVelocity = Vector3.zero;
        }

        targetFieldOfView = zoomRange.x; // 目標値を広角端の水平FOVに設定
        controlledCamera.fieldOfView = Camera.HorizontalToVerticalFieldOfView(targetFieldOfView, controlledCamera.aspect);

        // UDP受信スレッドを開始
        isRunning = true;
        receiveThread = new Thread(new ThreadStart(ReceiveData));
        receiveThread.IsBackground = true;
        receiveThread.Start();

        Debug.Log($"PTZ UDPリスナーをポート {listenPort} で開始しました。");

        // フィードバック用のクライアントを初期化
        if (enableFeedback)
        {
            feedbackClient = new UdpClient();
            feedbackEndPoint = new IPEndPoint(IPAddress.Parse(feedbackAddress), feedbackPort);
            Debug.Log($"PTZフィードバックを {feedbackAddress}:{feedbackPort} に送信します。");
        }
    }

    void Update()
    {
        Vector3 localContinuousVelocity;
        lock (ptzStateLock)
        {
            localContinuousVelocity = continuousVelocity;
        }

        // --- 連続移動 (Continuous Move) の処理 ---
        if (localContinuousVelocity.sqrMagnitude > 0.001f)
        {
            // 連続移動の場合、目標角度(targetEulerAngles)を毎フレーム更新する。
            // カメラの実際の角度(currentEulerAngles)は、この目標に対してSlerpで追従する。
            
            // Unityのオイラー角ではYがパン、Xがチルト（しかも向きが逆）
            float deltaPan = localContinuousVelocity.x * panSpeedMultiplier * Time.deltaTime;
            float deltaTilt = -localContinuousVelocity.y * tiltSpeedMultiplier * Time.deltaTime;

            lock (ptzStateLock)
            {
                if (endlessPan)
                {
                    targetEulerAngles.y += deltaPan;
                }
                else
                {
                    targetEulerAngles.y = Mathf.Clamp(targetEulerAngles.y + deltaPan, panRange.x, panRange.y);
                }

                targetEulerAngles.x = Mathf.Clamp(targetEulerAngles.x + deltaTilt, tiltRange.x, tiltRange.y);
            }
            
            float currentFov = targetFieldOfView;
            float newFov = currentFov - localContinuousVelocity.z * zoomSpeedMultiplier * Time.deltaTime;
            // zoomRangeは(広角, 望遠)なので、Clampでは(望遠, 広角)の順に指定する
            targetFieldOfView = Mathf.Clamp(newFov, zoomRange.y, zoomRange.x);
        }

        Vector3 localTargetEulerAngles;
        lock (ptzStateLock)
        {
            localTargetEulerAngles = targetEulerAngles;
        }

        // --- カメラの回転とズームを適用 ---
        // 常にSlerpを使用して目標角度へ滑らかに追従させることで、連続移動と絶対位置移動の間の挙動を統一する
        Quaternion targetRotation = Quaternion.Euler(localTargetEulerAngles);
        // 連続移動中はcontinuousSmoothingFactorで、それ以外はabsolutePan/TiltSpeedに合わせた速度で追従させる
        float smoothing = (localContinuousVelocity.sqrMagnitude > 0.001f) ? continuousSmoothingFactor : absolutePanSpeed / 45f; // 速度係数を調整
        transform.rotation = Quaternion.Slerp(transform.rotation, targetRotation, Time.deltaTime * smoothing);
        
        // ズームも同様に滑らかに追従させる
        float finalTargetVFOV = Camera.HorizontalToVerticalFieldOfView(targetFieldOfView, controlledCamera.aspect);
        // 連続移動中はcontinuousSmoothingFactorで、それ以外はabsoluteZoomSpeedに合わせた速度で追従させる
        float zoomSmoothing = (localContinuousVelocity.sqrMagnitude > 0.001f) ? continuousSmoothingFactor : absoluteZoomSpeed / 10f; // 速度係数を調整
        controlledCamera.fieldOfView = Mathf.Lerp(controlledCamera.fieldOfView, finalTargetVFOV, Time.deltaTime * zoomSmoothing);
        
        // 定期的に現在位置をフィードバック
        if (enableFeedback)
        {
            timeSinceLastFeedback += Time.deltaTime;
            if (timeSinceLastFeedback >= feedbackInterval)
            {
                SendFeedback();
                timeSinceLastFeedback = 0f;
            }
        }
    }

    void LateUpdate() // Updateの後に実行されるLateUpdateで処理することで、Updateでのカメラ移動が完了した後にコマンドを適用できる
    {
        // キューに溜まったメッセージをメインスレッドで処理
        while (messageQueue.TryDequeue(out string jsonMessage))
        {
            ProcessPtzMessage(jsonMessage);
        }
    }
    private void SendFeedback()
    {
        if (feedbackClient == null) return;

        try
        {
            Vector3 currentEulerAngles = transform.eulerAngles; // 0-360度の範囲で返ってくる

            // パンの角度を -180 ～ 180 の範囲に正規化する
            float wrappedPan = currentEulerAngles.y;
            if (wrappedPan > 180f)
            {
                wrappedPan -= 360f;
            }

            // チルトの角度も -180 ～ 180 の範囲に正規化する
            float wrappedTilt = currentEulerAngles.x;
            if (wrappedTilt > 180f)
            {
                wrappedTilt -= 360f;
            }

            // 現在のUnityの値をONVIFの正規化座標に逆変換
            var status = new PtzStatusMessage
            {
                // Pan: [panRange.x, panRange.y] -> [-1, 1]
                pan = Mathf.InverseLerp(panRange.x, panRange.y, wrappedPan) * 2f - 1f,
                // Tilt: [tiltRange.x, tiltRange.y] -> [-1, 1]
                tilt = Mathf.InverseLerp(tiltRange.x, tiltRange.y, wrappedTilt) * 2f - 1f,
                // Zoom: [zoomRange.x, zoomRange.y] -> [0, 1]
                zoom = GetCurrentZoomNormalized()
            };

            string json = JsonUtility.ToJson(status);
            byte[] data = Encoding.UTF8.GetBytes(json);
            feedbackClient.Send(data, data.Length, feedbackEndPoint);
        }
        catch (Exception e)
        {
            Debug.LogError($"PTZフィードバックの送信に失敗: {e.Message}");
        }
    }

    private float GetCurrentZoomNormalized()
    {
        // 現在の垂直FOVを水平FOVに変換して比較
        float currentFov = Camera.VerticalToHorizontalFieldOfView(controlledCamera.fieldOfView, controlledCamera.aspect);
        // zoomRangeは(広角, 望遠)の水平FOVなので、InverseLerpで正規化する
        return Mathf.InverseLerp(zoomRange.x, zoomRange.y, currentFov);
    }

    private void ReceiveData()
    {
        client = new UdpClient(listenPort);
        while (isRunning)
        {
            try
            {
                IPEndPoint anyIP = new IPEndPoint(IPAddress.Any, 0);
                byte[] data = client.Receive(ref anyIP);
                string text = Encoding.UTF8.GetString(data);
                
                messageQueue.Enqueue(text); // メッセージをキューに追加
            }
            catch (ThreadAbortException)
            {
                // スレッド停止時に発生する例外なので無視
                break;
            }
            catch (Exception err)
            {
                Debug.LogError(err.ToString());
            }
        }
    }

    private void ProcessPtzMessage(string json)
    {
        try
        {
            PtzMessage msg = JsonUtility.FromJson<PtzMessage>(json);
            if (msg == null) return;

            switch (msg.type)
            {
                case "absolute":
                    // ONVIFの正規化座標をUnityの角度/FoVに変換
                    lock (ptzStateLock)
                    {
                        // Pan: [-1, 1] -> [panRange.x, panRange.y]
                        targetEulerAngles.y = Mathf.Lerp(panRange.x, panRange.y, (msg.pan + 1f) / 2f);
                        // Tilt: [-1, 1] -> [tiltRange.x, tiltRange.y] (ONVIFの-1が下、1が上。UnityのEulerXは値が小さいほど上)
                        targetEulerAngles.x = Mathf.Lerp(tiltRange.y, tiltRange.x, (msg.tilt + 1f) / 2f); // ONVIFの-1(下)をtiltRange.y(例:20)に、1(上)をtiltRange.x(例:-90)にマッピング
                        // 連続移動を停止
                        continuousVelocity = Vector3.zero;
                    }
                    // 絶対位置移動の際は、現在のカメラの角度も目標値に追従させるため更新する
                    currentEulerAngles.y = Mathf.MoveTowardsAngle(currentEulerAngles.y, targetEulerAngles.y, 0);
                    currentEulerAngles.x = Mathf.MoveTowardsAngle(currentEulerAngles.x, targetEulerAngles.x, 0);

                    // Zoom: [0, 1] -> [zoomRange.x, zoomRange.y]
                    targetFieldOfView = Mathf.Lerp(zoomRange.x, zoomRange.y, msg.zoom); // 目標値を水平FOVで設定
                    break;

                case "continuous":
                    lock (ptzStateLock)
                    {
                        // 連続移動を開始する前に、現在のカメラの実際の角度で目標値をリセットする
                        // これにより、AbsoluteMove後のSlerpの遅延による位置の飛びを防ぐ
                        Vector3 currentEuler = transform.eulerAngles;

                        // transform.eulerAngles は 0-360 の範囲で値を返すため、
                        // スクリプト内部で使っている角度範囲 (例: -180～180) に変換する。
                        // これをしないと、マイナス角度のチルトがクランプによって不正な値にリセットされてしまう。
                        if (currentEuler.x > 180f) currentEuler.x -= 360f;
                        if (currentEuler.y > 180f) currentEuler.y -= 360f;
                        // Z軸は使用していないが、念のため正規化
                        if (currentEuler.z > 180f) currentEuler.z -= 360f;

                        targetEulerAngles = currentEuler;
                        currentEulerAngles = currentEuler; // 連続移動開始時に、平滑化用の角度もリセット
                        continuousVelocity = new Vector3(msg.pan_speed, msg.tilt_speed, msg.zoom_speed);
                    }
                    // Zoomも同様に現在の値でリセットする。現在の垂直FOVを水平FOVに変換して目標値とする。
                    targetFieldOfView = Camera.VerticalToHorizontalFieldOfView(controlledCamera.fieldOfView, controlledCamera.aspect);
                    break;

                case "stop":
                    lock (ptzStateLock) { continuousVelocity = Vector3.zero; }
                    break;
            }
        }
        catch (Exception e)
        {
            Debug.LogError($"PTZメッセージの処理に失敗: {e.Message}\nJSON: {json}");
        }
    }

    // アプリケーション終了時にスレッドをクリーンアップ
    void OnApplicationQuit()
    {
        StopThread();
    }

    void OnDestroy()
    {
        StopThread();
    }

    private void StopThread()
    {
        isRunning = false;
        if (client != null)
        {
            // UdpClient.Receive()はブロッキングするため、Close()で強制的に例外を発生させてスレッドを終了させる
            client.Close();
            client = null;
        }

        if (feedbackClient != null)
        {
            feedbackClient.Close();
            feedbackClient = null;
        }

        if (receiveThread != null && receiveThread.IsAlive)
        {
            receiveThread.Join(); // スレッドが完全に終了するのを待つ
            receiveThread = null;
        }
    }
}

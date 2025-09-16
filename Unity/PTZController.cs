// PTZController.cs
using UnityEngine;
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
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

    [Tooltip("ズームの可動範囲（カメラのField of View）")]
    public Vector2 zoomRange = new Vector2(60f, 5f);

    [Header("Continuous Move Speed")]
    [Tooltip("パンの連続移動速度（度/秒）")]
    public float panSpeedMultiplier = 90f;

    [Tooltip("チルトの連続移動速度（度/秒）")]
    public float tiltSpeedMultiplier = 45f;

    [Tooltip("ズームの連続移動速度（FoV/秒）")]
    public float zoomSpeedMultiplier = 30f;

    [Header("Movement Smoothing")]
    [Tooltip("カメラが目標位置に追従する速度。値が大きいほど速く動きます。")]
    public float smoothingFactor = 10f;

    // --- 内部変数 ---
    private Thread receiveThread;
    private UdpClient client;
    private Camera controlledCamera;

    // PTZ状態変数
    private Vector3 targetEulerAngles;
    private volatile float targetFieldOfView;
    private Vector3 continuousVelocity; // (pan, tilt, zoom) の速度
    private readonly object ptzStateLock = new object();
    private volatile bool isRunning;

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

        // 現在のカメラの状態を初期値として設定
        lock (ptzStateLock)
        {
            targetEulerAngles = transform.eulerAngles;
            continuousVelocity = Vector3.zero;
        }
        targetFieldOfView = controlledCamera.fieldOfView;

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

        // 連続移動が指示されている場合、速度に応じて目標値を更新
        if (localContinuousVelocity.sqrMagnitude > 0.001f)
        {
            // 速度と時間から移動量を計算
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
            float newFov = targetFieldOfView - localContinuousVelocity.z * zoomSpeedMultiplier * Time.deltaTime;
            targetFieldOfView = Mathf.Clamp(newFov, zoomRange.y, zoomRange.x); // FoVは値が小さいほどズームインなのでMin/Maxが逆
        }

        Vector3 localTargetEulerAngles;
        lock (ptzStateLock)
        {
            localTargetEulerAngles = targetEulerAngles;
        }
        // 現在の値から目標値へ滑らかにカメラを動かす (Slerp)
        Quaternion targetRotation = Quaternion.Euler(localTargetEulerAngles);
        transform.rotation = Quaternion.Slerp(transform.rotation, targetRotation, Time.deltaTime * smoothingFactor);
        controlledCamera.fieldOfView = Mathf.Lerp(controlledCamera.fieldOfView, targetFieldOfView, Time.deltaTime * smoothingFactor);

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

    private void SendFeedback()
    {
        if (feedbackClient == null) return;

        try
        {
            // ★★★ 修正点: フィードバックも現在の実際の角度を基準にする ★★★
            Vector3 currentEulerAngles = transform.eulerAngles; // 0-360度の範囲で返ってくる

            // パンの角度を -180 ～ 180 の範囲に正規化する
            float wrappedPan = currentEulerAngles.y;
            if (wrappedPan > 180f)
            {
                wrappedPan -= 360f;
            }

            // 現在のUnityの値をONVIFの正規化座標に逆変換
            var status = new PtzStatusMessage
            {
                // Pan: [panRange.x, panRange.y] -> [-1, 1]
                // endlessPanが有効な場合、panRangeは事実上[-180, 180]として扱う
                pan = Mathf.InverseLerp(panRange.x, panRange.y, wrappedPan) * 2f - 1f,
                // Tilt: [tiltRange.y, tiltRange.x] -> [-1, 1]
                tilt = Mathf.InverseLerp(tiltRange.y, tiltRange.x, currentEulerAngles.x) * 2f - 1f,
                // Zoom: [zoomRange.x, zoomRange.y] -> [0, 1]
                zoom = Mathf.InverseLerp(zoomRange.x, zoomRange.y, controlledCamera.fieldOfView)
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

                // メインスレッドで処理させる場合は以下のようなキューイング機構を推奨
                // UnityMainThreadDispatcher.Instance().Enqueue(() => ProcessPtzMessage(text));
                ProcessPtzMessage(text);
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
                        // Tilt: [-1, 1] -> [tiltRange.y, tiltRange.x] (ONVIFとUnityで向きが逆)
                        targetEulerAngles.x = Mathf.Lerp(tiltRange.y, tiltRange.x, (msg.tilt + 1f) / 2f);
                        // 連続移動を停止
                        continuousVelocity = Vector3.zero;
                    }
                    // Zoom: [0, 1] -> [zoomRange.x, zoomRange.y]
                    targetFieldOfView = Mathf.Lerp(zoomRange.x, zoomRange.y, msg.zoom);
                    break;

                case "continuous":
                    lock (ptzStateLock)
                    {
                        // 連続移動を開始する前に、現在のカメラの実際の角度で目標値をリセットする
                        // これにより、AbsoluteMove後のSlerpの遅延による位置の飛びを防ぐ
                        targetEulerAngles = transform.eulerAngles;
                        continuousVelocity = new Vector3(msg.pan_speed, msg.tilt_speed, msg.zoom_speed);
                    }
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

from flask import Flask, request, Response
import requests
from flask_cors import CORS
import logging

app = Flask(__name__)
# すべてのオリジンからのリクエストを許可
CORS(app)

@app.route('/proxy/<path:camera_path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy(camera_path):
    # ログ出力を有効化
    logging.basicConfig(level=logging.INFO)
    
    # リクエストのボディを取得
    request_data = request.get_data()

    # クエリパラメータからターゲットカメラの情報を取得
    target_ip = request.args.get('target_ip')
    target_port = request.args.get('target_port')

    if not target_ip or not target_port:
        return "Target IP and Port must be provided as query parameters.", 400

    # カメラへのURLを構築
    target_url = f"http://{target_ip}:{target_port}/{camera_path}"
    logging.info(f"--- Proxying request to: {target_url} ---")

    try:
        # --- ヘッダーのホワイトリスト化 ---
        # ブラウザからのヘッダーは破棄し、ONVIFに必要なヘッダーのみを再構築する。
        # これにより、カメラ側の厳格なヘッダーパーサーに起因する問題を回避する。
        headers = {
            'Content-Type': request.headers.get('Content-Type'),
            'SOAPAction': request.headers.get('SOAPAction')
        }
        # SOAPActionがない場合はヘッダーから削除
        if not headers['SOAPAction']:
            del headers['SOAPAction']

        logging.info(f"Request Headers: {headers}")
        # リクエストボディが大きすぎない場合のみログに出力
        if len(request_data) < 5000:
            logging.info(f"Request Body: {request_data.decode('utf-8', errors='ignore')}")
        
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request_data,
            timeout=10, # タイムアウトを設定
            verify=False
        )

        logging.info(f"--- Received response from camera with status: {resp.status_code} ---")
        # レスポンスボディもログに出力
        response_text = resp.text
        if len(response_text) < 5000:
             logging.info(f"Response Body: {response_text}")

        # カメラからの応答ヘッダーをコピー
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(name, value) for (name, value) in resp.raw.headers.items()
                           if name.lower() not in excluded_headers]

        # カメラからの応答をクライアントに返す
        return Response(resp.content, resp.status_code, response_headers) # resp.content を使う

    except requests.exceptions.RequestException as e:
        # エラーの詳細をログに出力
        logging.error(f"!!! Proxy request to {target_url} failed !!!")
        logging.error(f"Error Type: {type(e)}")
        logging.error(f"Error Details: {e}")
        return f"Proxy error: Could not connect to the camera at {target_url}. Reason: {e}", 502

if __name__ == '__main__':
    # 0.0.0.0でホストし、外部からアクセス可能にする
    # シミュレーターとは別のポート（例: 8081）で実行
    app.run(host='0.0.0.0', port=8081, debug=True)

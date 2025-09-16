# onvif_profile_t_simulator.py
import argparse
import logging
import threading
import uuid
from xml.etree import ElementTree as ET
from datetime import datetime, timedelta
import time
import socket

from flask import Flask, request, Response, render_template
from wsdiscovery.publishing import ThreadedWSPublishing as WSPublishing
from wsdiscovery import QName, Scope

# 基本的なロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
)

def get_host_ip():
    """
    実行マシンのプライベートIPアドレスを自動検出する。
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 接続するわけではないので、IPは到達不能でも問題ない
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        if s:
            s.close()
    return ip

class OnvifSoapService:
    """
    ONVIF SOAPリクエストを処理するFlaskベースのサービス。
    """
    def __init__(self, server_ip, soap_port, rtsp_url, device_info, device_uuid, protocol="http"):
        self.app = Flask(__name__)
        self.server_ip = server_ip
        self.soap_port = soap_port
        self.rtsp_url = rtsp_url
        self.device_info = device_info
        self.device_uuid = device_uuid
        self.protocol = protocol
        
        # ONVIFエンティティのトークンを定義
        self.video_source_token = "VideoSource_1"
        self.video_encoder_token = "VideoEncoder_H265_1"
        self.profile_token = "Profile_T_1"
        self.profile_name = "ProfileT_H265"
        self.ptz_node_token = "PTZNode_1"
        self.ptz_configuration_token = "PTZConfiguration_1"

        # PTZの現在位置を保持する状態
        self.ptz_position = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.ptz_velocity = {'x': 0.0, 'y': 0.0, 'z': 0.0} # For ContinuousMove
        self.ptz_move_thread = None
        self.ptz_stop_event = threading.Event()
        self.ptz_lock = threading.Lock()

        # Imaging state
        self.imaging_settings = {'brightness': 50.0, 'contrast': 50.0, 'saturation': 50.0}
        self.imaging_lock = threading.Lock()

        # Eventing state
        self.events_queue = []
        self.events_lock = threading.Lock()
        # Start a thread to generate dummy motion events
        self.motion_event_thread = threading.Thread(target=self._generate_motion_events, daemon=True)
        self.motion_event_thread.start()

        # ルートを登録
        self.app.add_url_rule("/onvif/device_service", "device_service", self.device_service, methods=["POST"])
        self.app.add_url_rule("/onvif/media_service", "media_service", self.media_service, methods=["POST"])
        self.app.add_url_rule("/onvif/ptz_service", "ptz_service", self.ptz_service, methods=["POST"])
        self.app.add_url_rule("/", "index", self.index, methods=["GET"])
        self.app.add_url_rule("/onvif/imaging_service", "imaging_service", self.imaging_service, methods=["POST"])
        self.app.add_url_rule("/onvif/events_service", "events_service", self.events_service, methods=["POST"])
        self.app.add_url_rule("/onvif/events/pullpoint", "pull_messages", self.pull_messages, methods=["POST"])

    def run(self):
        """Flask Webサーバーを実行する。"""
        service_url = f"{self.protocol}://{self.server_ip}:{self.soap_port}"
        logging.info(f"SOAPサービスを {service_url} で開始します")

        ssl_context = None
        if self.protocol == "https":
            try:
                # 自己署名証明書を使用
                ssl_context = ('cert.pem', 'key.pem')
                # 念のためファイルの存在を確認
                with open(ssl_context[0]) as f: pass
                with open(ssl_context[1]) as f: pass
            except FileNotFoundError:
                logging.error("HTTPSを有効にするには、'cert.pem'と'key.pem'が必要です。")
                logging.error("openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365 を実行して生成してください。")
                return

        # ネットワーク上の他のマシンからアクセスできるように '0.0.0.0' でホスト
        self.app.run(host='0.0.0.0', port=self.soap_port, ssl_context=ssl_context)

    def index(self):
        """ONVIF操作をテストするためのシンプルなHTMLページを返す。"""
        # テンプレートに変数を渡してレンダリングする
        return render_template(
            'index.html', protocol=self.protocol, host=f"{self.server_ip}:{self.soap_port}",
            profile_token=self.profile_token, rtsp_url=self.rtsp_url, video_source_token=self.video_source_token
        )

    def _generate_motion_events(self):
        """定期的にモーション検知イベントを生成する。"""
        while True:
            # 30秒ごとにイベントを生成
            time.sleep(30)
            with self.events_lock:
                event_time = datetime.utcnow()
                # キューが大きくなりすぎないように制御
                if len(self.events_queue) > 50:
                    self.events_queue.pop(0)
                self.events_queue.append({'topic': 'tns1:VideoSource/MotionAlarm', 'time': event_time, 'state': True})
                logging.info("モーション検知イベントを生成しました (state=true)")

    def _parse_soap_action(self, data):
        """SOAPリクエストを解析し、アクション名を抽出する。"""
        try:
            root = ET.fromstring(data)
            # SOAP Body要素を探す (名前空間を無視して末尾が'Body'であるものを探す)
            body = None
            for element in root:
                if element.tag.endswith('Body'):
                    body = element
                    break

            if body is None or len(body) == 0:
                logging.warning("SOAPリクエスト内にBody要素またはアクションが見つかりません。")
                return None

            # Bodyの最初の子要素がアクションとなる
            action_element = body[0]
            
            # タグ名から名前空間を除去してアクション名を取得 (例: {http://...}GetCapabilities -> GetCapabilities)
            return action_element.tag.split('}', 1)[-1]
        except Exception as e:
            logging.error(f"SOAPアクションの解析に失敗しました: {e}")
            return None

    def _generate_soap_response(self, body_content):
        """コンテンツをSOAPエンベロープでラップして応答を生成する。"""
        response_template = f"""
<soap-env:Envelope
    xmlns:soap-env="http://www.w3.org/2003/05/soap-envelope"
    xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
    xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
    xmlns:tt="http://www.onvif.org/ver10/schema"
    xmlns:tns1="http://www.onvif.org/ver10/topics"
    xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
    xmlns:tev="http://www.onvif.org/ver10/events/wsdl"
    xmlns:timg="http://www.onvif.org/ver20/imaging/wsdl">
    <soap-env:Header></soap-env:Header>
    <soap-env:Body>
        {body_content}
    </soap-env:Body>
</soap-env:Envelope>
"""
        return Response(response_template, mimetype="application/soap+xml")

    def device_service(self):
        """device_serviceエンドポイントへのリクエストを処理する。"""
        action = self._parse_soap_action(request.data)
        logging.info(f"Device serviceがアクションを受信: {action}")

        if action == "GetCapabilities":
            body = f"""
<tds:GetCapabilitiesResponse>
    <tds:Capabilities>
        <tt:Media>
            <tt:XAddr>{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/media_service</tt:XAddr>
            <tt:StreamingCapabilities>
                <tt:RTPMulticast>false</tt:RTPMulticast>
                <tt:RTP_TCP>true</tt:RTP_TCP>
                <tt:RTP_RTSP_TCP>true</tt:RTP_RTSP_TCP>
            </tt:StreamingCapabilities>
        </tt:Media>
        <tt:Events>
            <tt:XAddr>{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/events_service</tt:XAddr>
            <tt:WSSubscriptionPolicySupport>true</tt:WSSubscriptionPolicySupport>
            <tt:WSPullPointSupport>true</tt:WSPullPointSupport>
        </tt:Events>
        <tt:Imaging>
            <tt:XAddr>{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/imaging_service</tt:XAddr>
        </tt:Imaging>
        <tt:PTZ>
            <tt:XAddr>{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/ptz_service</tt:XAddr>
        </tt:Media>
    </tds:Capabilities>
</tds:GetCapabilitiesResponse>
"""
            return self._generate_soap_response(body)

        if action == "GetDeviceInformation":
            body = f"""
<tds:GetDeviceInformationResponse>
    <tds:Manufacturer>{self.device_info.get('Manufacturer', 'Unknown')}</tds:Manufacturer>
    <tds:Model>{self.device_info.get('Model', 'Unknown')}</tds:Model>
    <tds:FirmwareVersion>{self.device_info.get('FirmwareVersion', '0.0.0')}</tds:FirmwareVersion>
    <tds:SerialNumber>{self.device_uuid}</tds:SerialNumber>
    <tds:HardwareId>{self.device_info.get('HardwareId', 'Unknown')}</tds:HardwareId>
</tds:GetDeviceInformationResponse>
"""
            return self._generate_soap_response(body)
        
        logging.warning(f"未処理のDevice serviceアクション: {action}")
        return "Not Implemented", 501

    def media_service(self):
        """media_serviceエンドポイントへのリクエストを処理する。"""
        action = self._parse_soap_action(request.data)
        logging.info(f"Media serviceがアクションを受信: {action}")

        if action == "GetProfiles":
            body = f"""
<trt:GetProfilesResponse>
    <trt:Profiles token="{self.profile_token}" fixed="true">
        <tt:Name>{self.profile_name}</tt:Name>
        <tt:VideoSourceConfiguration token="{self.video_source_token}">
            <tt:Name>VideoSourceConfig</tt:Name>
            <tt:UseCount>1</tt:UseCount>
            <tt:SourceToken>{self.video_source_token}</tt:SourceToken>
            <tt:Bounds x="0" y="0" width="1920" height="1080"/>
        </tt:VideoSourceConfiguration>
        <tt:VideoEncoderConfiguration token="{self.video_encoder_token}">
            <tt:Name>VideoEncoder_H265</tt:Name>
            <tt:UseCount>1</tt:UseCount>
            <tt:Encoding>H265</tt:Encoding>
            <tt:Resolution>
                <tt:Width>1920</tt:Width>
                <tt:Height>1080</tt:Height>
            </tt:Resolution>
            <tt:Quality>5</tt:Quality>
            <tt:RateControl>
                <tt:FrameRateLimit>30</tt:FrameRateLimit>
                <tt:EncodingInterval>1</tt:EncodingInterval>
                <tt:BitrateLimit>4096</tt:BitrateLimit>
            </tt:RateControl>
            <tt:Multicast>
                <tt:Address>
                    <tt:Type>IPv4</tt:Type>
                    <tt:IPv4Address>0.0.0.0</tt:IPv4Address>
                </tt:Address>
                <tt:Port>0</tt:Port>
                <tt:TTL>0</tt:TTL>
                <tt:AutoStart>false</tt:AutoStart>
            </tt:Multicast>
            <tt:SessionTimeout>PT60S</tt:SessionTimeout>
        </tt:VideoEncoderConfiguration>
        <tt:PTZConfiguration token="{self.ptz_configuration_token}">
            <tt:Name>PTZConfig-1</tt:Name>
            <tt:UseCount>1</tt:UseCount>
            <tt:NodeToken>{self.ptz_node_token}</tt:NodeToken>
        </tt:PTZConfiguration>
    </trt:Profiles>
</trt:GetProfilesResponse>
"""
            return self._generate_soap_response(body)

        if action == "GetStreamUri":
            body = f"""
<trt:GetStreamUriResponse>
    <trt:MediaUri>
        <tt:Uri>{self.rtsp_url}</tt:Uri>
        <tt:InvalidAfterConnect>false</tt:InvalidAfterConnect>
        <tt:InvalidAfterReboot>false</tt:InvalidAfterReboot>
        <tt:Timeout>PT60S</tt:Timeout>
    </trt:MediaUri>
</trt:GetStreamUriResponse>
"""
            return self._generate_soap_response(body)
            
        if action == "GetVideoEncoderConfigurations":
            body = f"""
<trt:GetVideoEncoderConfigurationsResponse>
    <trt:Configurations token="{self.video_encoder_token}">
        <tt:Name>VideoEncoder_H265</tt:Name>
        <tt:UseCount>1</tt:UseCount>
        <tt:Encoding>H265</tt:Encoding>
        <tt:Resolution>
            <tt:Width>1920</tt:Width>
            <tt:Height>1080</tt:Height>
        </tt:Resolution>
        <tt:Quality>5</tt:Quality>
        <tt:SessionTimeout>PT60S</tt:SessionTimeout>
    </trt:Configurations>
</trt:GetVideoEncoderConfigurationsResponse>
"""
            return self._generate_soap_response(body)

        logging.warning(f"未処理のMedia serviceアクション: {action}")
        return "Not Implemented", 501

    def _ptz_continuous_move_loop(self):
        """PTZの連続移動をシミュレートするループ。"""
        logging.info(f"PTZ continuous move thread started with velocity: {self.ptz_velocity}")
        while not self.ptz_stop_event.is_set():
            with self.ptz_lock:
                # 座標を更新 (範囲チェックも行う)
                self.ptz_position['x'] = max(-1.0, min(1.0, self.ptz_position['x'] + self.ptz_velocity['x'] * 0.1))
                self.ptz_position['y'] = max(-1.0, min(1.0, self.ptz_position['y'] + self.ptz_velocity['y'] * 0.1))
                self.ptz_position['z'] = max(0.0, min(1.0, self.ptz_position['z'] + self.ptz_velocity['z'] * 0.1))
            time.sleep(0.1)
        logging.info("PTZ continuous move thread stopped.")
        # 状態をリセット
        self.ptz_velocity = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.ptz_move_thread = None

    def ptz_service(self):
        """ptz_serviceエンドポイントへのリクエストを処理する。"""
        action = self._parse_soap_action(request.data)
        logging.info(f"PTZ serviceがアクションを受信: {action}")

        if action == "GetNodes":
            body = f"""
<tptz:GetNodesResponse>
    <tptz:PTZNode token="{self.ptz_node_token}">
        <tt:Name>PTZNode-1</tt:Name>
        <tt:SupportedPTZSpaces>
            <tt:AbsolutePanTiltPositionSpace>
                <tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace</tt:URI>
                <tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange> <!-- Pan: 360 endless -->
                <tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange> <!-- Tilt: -90 to +20 degrees -->
            </tt:AbsolutePanTiltPositionSpace>
            <tt:AbsoluteZoomPositionSpace>
                <tt:URI>http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace</tt:URI>
                <tt:XRange><tt:Min>0.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange> <!-- Zoom: 31x optical -->
            </tt:AbsoluteZoomPositionSpace>
        </tt:SupportedPTZSpaces>
        <tt:MaximumNumberOfPresets>10</tt:MaximumNumberOfPresets>
        <tt:HomeSupported>true</tt:HomeSupported>
    </tptz:PTZNode>
</tptz:GetNodesResponse>
"""
            return self._generate_soap_response(body)

        if action == "GetConfigurations":
            body = f"""
<tptz:GetConfigurationsResponse>
    <tptz:PTZConfiguration token="{self.ptz_configuration_token}">
        <tt:Name>PTZConfig-1</tt:Name>
        <tt:UseCount>1</tt:UseCount>
        <tt:NodeToken>{self.ptz_node_token}</tt:NodeToken>
    </tptz:PTZConfiguration>
</tptz:GetConfigurationsResponse>
"""
            return self._generate_soap_response(body)

        if action == "AbsoluteMove":
            # 連続移動中であれば停止する
            if self.ptz_move_thread is not None:
                self.ptz_stop_event.set()
                self.ptz_move_thread.join()

            try:
                # XMLをパースして座標を取得
                root = ET.fromstring(request.data)
                ns = {
                    'tt': 'http://www.onvif.org/ver10/schema'
                }
                pan_tilt_el = root.find('.//tt:PanTilt', ns)
                zoom_el = root.find('.//tt:Zoom', ns)

                with self.ptz_lock:
                    if pan_tilt_el is not None:
                        self.ptz_position['x'] = float(pan_tilt_el.attrib['x'])
                        self.ptz_position['y'] = float(pan_tilt_el.attrib['y'])
                    if zoom_el is not None:
                        self.ptz_position['z'] = float(zoom_el.attrib['x'])
                    
                    logging.info(f"PTZ AbsoluteMove received. New position: {self.ptz_position}")

            except Exception as e:
                logging.error(f"AbsoluteMoveのパースに失敗: {e}")
                # エラーが発生しても、ONVIF仕様に従い成功応答を返すことが多い

            return self._generate_soap_response("<tptz:AbsoluteMoveResponse/>")

        if action == "ContinuousMove":
            # 既存のスレッドがあれば停止
            if self.ptz_move_thread is not None:
                self.ptz_stop_event.set()
                self.ptz_move_thread.join()

            try:
                root = ET.fromstring(request.data)
                ns = {'tt': 'http://www.onvif.org/ver10/schema'}
                velocity_el = root.find('.//tt:PanTilt', ns)
                zoom_el = root.find('.//tt:Zoom', ns)
                with self.ptz_lock:
                    if velocity_el is not None:
                        self.ptz_velocity['x'] = float(velocity_el.attrib.get('x', 0.0))
                        self.ptz_velocity['y'] = float(velocity_el.attrib.get('y', 0.0))
                    if zoom_el is not None:
                        self.ptz_velocity['z'] = float(zoom_el.attrib.get('x', 0.0))
                
                # 新しい移動スレッドを開始
                self.ptz_stop_event.clear()
                self.ptz_move_thread = threading.Thread(target=self._ptz_continuous_move_loop, daemon=True)
                self.ptz_move_thread.start()

            except Exception as e:
                logging.error(f"ContinuousMoveのパースに失敗: {e}")

            return self._generate_soap_response("<tptz:ContinuousMoveResponse/>")

        if action == "Stop":
            logging.info("PTZ Stop command received.")
            if self.ptz_move_thread is not None:
                self.ptz_stop_event.set()
                self.ptz_move_thread.join() # スレッドの終了を待つ
            return self._generate_soap_response("<tptz:StopResponse/>")

        if action == "GetStatus":
            with self.ptz_lock:
                pos = self.ptz_position
                # 連続移動中かどうかを判断
                is_moving = self.ptz_move_thread is not None and self.ptz_move_thread.is_alive()
                move_status = "MOVING" if is_moving else "IDLE"

            body = f"""
<tptz:GetStatusResponse>
    <tptz:PTZStatus>
        <tt:Position>
            <tt:PanTilt x="{pos['x']}" y="{pos['y']}" space="http://www.onvif.org/ver10/tptz/PanTiltSpaces/PositionGenericSpace"/>
            <tt:Zoom x="{pos['z']}" space="http://www.onvif.org/ver10/tptz/ZoomSpaces/PositionGenericSpace"/>
        </tt:Position>
        <tt:MoveStatus>{move_status}</tt:MoveStatus>
        <tt:UtcTime>{datetime.utcnow().isoformat()}Z</tt:UtcTime>
    </tptz:PTZStatus>
</tptz:GetStatusResponse>
"""
            return self._generate_soap_response(body)

        logging.warning(f"未処理のPTZ serviceアクション: {action}")
        return "Not Implemented", 501

    def imaging_service(self):
        """imaging_serviceエンドポイントへのリクエストを処理する。"""
        action = self._parse_soap_action(request.data)
        logging.info(f"Imaging serviceがアクションを受信: {action}")

        if action == "GetImagingSettings":
            with self.imaging_lock:
                settings = self.imaging_settings
            body = f"""
<timg:GetImagingSettingsResponse>
    <timg:ImagingSettings>
        <tt:Brightness>{settings['brightness']}</tt:Brightness>
        <tt:Contrast>{settings['contrast']}</tt:Contrast>
        <tt:Saturation>{settings['saturation']}</tt:Saturation>
    </timg:ImagingSettings>
</timg:GetImagingSettingsResponse>
"""
            return self._generate_soap_response(body)

        if action == "SetImagingSettings":
            try:
                root = ET.fromstring(request.data)
                ns = {'tt': 'http://www.onvif.org/ver10/schema'}
                with self.imaging_lock:
                    brightness_el = root.find('.//tt:Brightness', ns)
                    if brightness_el is not None: self.imaging_settings['brightness'] = float(brightness_el.text)
                    
                    contrast_el = root.find('.//tt:Contrast', ns)
                    if contrast_el is not None: self.imaging_settings['contrast'] = float(contrast_el.text)

                    saturation_el = root.find('.//tt:Saturation', ns)
                    if saturation_el is not None: self.imaging_settings['saturation'] = float(saturation_el.text)
                logging.info(f"SetImagingSettings received. New settings: {self.imaging_settings}")
            except Exception as e:
                logging.error(f"SetImagingSettingsのパースに失敗: {e}")
            
            return self._generate_soap_response('<timg:SetImagingSettingsResponse/>')

        logging.warning(f"未処理のImaging serviceアクション: {action}")
        return "Not Implemented", 501

    def events_service(self):
        """events_serviceエンドポイントへのリクエストを処理する。"""
        action = self._parse_soap_action(request.data)
        logging.info(f"Events serviceがアクションを受信: {action}")

        if action == "CreatePullPointSubscription":
            # 簡単な実装として、常に同じPullPoint URLを返す
            pull_point_url = f"{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/events/pullpoint"
            current_time = datetime.utcnow()
            termination_time = current_time + timedelta(minutes=10)
            body = f"""
<tev:CreatePullPointSubscriptionResponse>
    <tev:SubscriptionReference>
        <wsa:Address>{pull_point_url}</wsa:Address>
    </tev:SubscriptionReference>
    <wsnt:CurrentTime>{current_time.isoformat()}Z</wsnt:CurrentTime>
    <wsnt:TerminationTime>{termination_time.isoformat()}Z</wsnt:TerminationTime>
</tev:CreatePullPointSubscriptionResponse>
"""
            return self._generate_soap_response(body)

        logging.warning(f"未処理のEvents serviceアクション: {action}")
        return "Not Implemented", 501

    def pull_messages(self):
        """PullPointからのPullMessagesリクエストを処理する。"""
        with self.events_lock:
            events_to_send = self.events_queue.copy()
            self.events_queue.clear() # キューをクリア
        
        notifications = ""
        for event in events_to_send:
            notifications += f"""
<wsnt:NotificationMessage>
    <wsnt:Topic Dialect="http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet">{event['topic']}</wsnt:Topic>
    <wsnt:Message><tt:Message UtcTime="{event['time'].isoformat()}Z"><tt:Data><tt:SimpleItem Name="State" Value="{str(event['state']).lower()}"/></tt:Data></tt:Message></wsnt:Message>
</wsnt:NotificationMessage>
"""
        body = f"""
<tev:PullMessagesResponse>
    <tev:CurrentTime>{datetime.utcnow().isoformat()}Z</tev:CurrentTime>
    <tev:TerminationTime>{(datetime.utcnow() + timedelta(minutes=10)).isoformat()}Z</tev:TerminationTime>
    {notifications}
</tev:PullMessagesResponse>
"""
        return self._generate_soap_response(body)

class OnvifSimulator:
    """
    ONVIF Profile Tシミュレーターのメインクラス。
    WS-DiscoveryとSOAPコンポーネントを管理する。
    """
    def __init__(self, server_ip, soap_port, rtsp_url, device_info_path, protocol="http"):
        self.server_ip = server_ip
        self.soap_port = soap_port
        self.rtsp_url = rtsp_url
        self.device_uuid = uuid.uuid4()
        self.protocol = protocol

        device_info = self._load_device_info(device_info_path)

        # 必要なモジュールをインポート
        self.wsp = None # WS-Publishingインスタンスを保持
        self.soap_service = OnvifSoapService(server_ip, soap_port, rtsp_url, device_info, self.device_uuid, self.protocol)

    def _setup_ws_discovery(self):
        """WS-Discoveryサービスをセットアップし、公開を開始する。"""
        xaddrs = [f"{self.protocol}://{self.server_ip}:{self.soap_port}/onvif/device_service"]
        scopes = [
            Scope("onvif://www.onvif.org/Profile/T"),
            Scope("onvif://www.onvif.org/name/GeminiSimulator"),
            Scope("onvif://www.onvif.org/hardware/Simulator-v2"),
        ]
        # ONVIF仕様では、TypeはQNameで指定することが推奨される
        # dn:NetworkVideoTransmitter
        types = [QName("dn", "http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter")]
        
        # Publishingサービスをインスタンス化して開始
        self.wsp = WSPublishing()
        self.wsp.start()

        # サービスを公開
        self.wsp.publishService(types=types, scopes=scopes, xAddrs=xaddrs)
        
        logging.info(f"WS-Discoveryサービスが {xaddrs[0]} を公開中")

    def _load_device_info(self, path):
        """デバイス情報ファイルを読み込む。"""
        try:
            with open(path, 'r') as f:
                import json
                return json.load(f)
        except Exception as e:
            logging.error(f"デバイス情報ファイル ({path}) の読み込みに失敗しました: {e}")
            return {}

    def run(self):
        """シミュレーターの全コンポーネントを起動する。"""
        try:
            # WS-Discoveryサービスをセットアップして起動
            self._setup_ws_discovery()

            # SOAPサービスをメインスレッドで実行
            # Ctrl+CでFlaskサーバーが停止すると、プログラム全体が終了する
            logging.info("シミュレーターを開始します。停止するには Ctrl+C を押してください。")
            self.soap_service.run()

        except KeyboardInterrupt:
            logging.info("シャットダウン要求を受信しました。")
        finally:
            if self.wsp:
                self.wsp.stop()
                logging.info("WS-Discoveryサービスを停止しました。")
            logging.info("シミュレーターが停止しました。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ONVIF Profile T Simulator")
    parser.add_argument("rtsp_url", type=str, help="外部RTSPサーバーの完全なURL (例: rtsp://127.0.0.1:8554/mystream)")
    parser.add_argument("--ip", type=str, help="シミュレーターをバインドするサーバーのIPアドレス (未指定の場合は自動検出)")
    parser.add_argument("--device-info", type=str, default="device_info.json", help="デバイス情報JSONファイルのパス")
    parser.add_argument("--soap-port", type=int, default=8080, help="SOAPサービス用のポート番号 (デフォルト: 8080)")
    parser.add_argument("--https", action="store_true", help="HTTPSを有効にする (cert.pemとkey.pemが必要)")
    args = parser.parse_args()

    server_ip = args.ip
    if not server_ip:
        server_ip = get_host_ip()
        logging.info(f"IPアドレスが指定されなかったため、自動検出しました: {server_ip}")
    else:
        logging.info(f"指定されたIPアドレスを使用します: {server_ip}")

    protocol = "https" if args.https else "http"

    simulator = OnvifSimulator(
        server_ip=server_ip,
        soap_port=args.soap_port,
        rtsp_url=args.rtsp_url,
        device_info_path=args.device_info,
        protocol=protocol
    )
    simulator.run()

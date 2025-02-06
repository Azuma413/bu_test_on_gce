"""
WebRTCを使用したブラウザ画面共有サーバー

このモジュールは、WebRTCを利用してブラウザの画面をキャプチャし、
クライアントにストリーミングするサーバーを実装します。
"""
import asyncio
import json
import os
import ssl
import time
import mss
import numpy as np
import av
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig, BrowserContextConfig
from dotenv import load_dotenv
from fractions import Fraction
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

ROOT = os.path.dirname(__file__)

class BrowserController:
    """ブラウザの制御を管理するクラス"""
    def __init__(self):
        self.browser = None
        
    def create_browser(self) -> Browser:
        """ブラウザインスタンスを作成する"""
        return Browser(
            config=BrowserConfig(
                headless=False,
                chrome_instance_path="/usr/bin/google-chrome",
                # new_context_config=BrowserContextConfig(
                #     browser_window_size=lambda: {"width": 1280, "height": 720},  # Set explicit window size
                # )
            )
        )

    async def set_window_position_and_size(self, x: int, y: int, width: int, height: int):
        """Chromeウィンドウの位置とサイズを設定する

        Args:
            x: ウィンドウのX座標
            y: ウィンドウのY座標
            width: ウィンドウの幅
            height: ウィンドウの高さ
        """
        window_ids = os.popen("xdotool search --onlyvisible --name 'Chrome'").read().strip().split('\n')
        if not window_ids:
            return False
        
        window_id = window_ids[-1]
        os.system(f'xdotool windowsize {window_id} {width} {height}')
        os.system(f'xdotool windowmove {window_id} {x} {y}')
        return True

    async def start_browser(self):
        """ブラウザを起動し、初期設定を行う"""
        self.browser = self.create_browser()
        model = ChatOpenAI(model='gpt-4o')
        agent = Agent(
            task="Navigate to about:blank",
            llm=model,
            controller=Controller(),
            browser=self.browser,
        )
        await agent.run()
        await asyncio.sleep(1)
        return await self.set_window_position_and_size(0, 0, 1280, 720)
            
    def cleanup(self):
        """Clean up browser resources."""
        if self.browser:
            self.browser.quit()

class ScreenCaptureTrack(MediaStreamTrack):
    """画面キャプチャ用のMediaTrackクラス"""
    kind = "video"

    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        monitors = self.sct.monitors
        
        # プライマリモニターまたは利用可能な唯一のモニターを選択
        self._monitor = monitors[1] if len(monitors) > 1 else monitors[0]
            
        # キャプチャ範囲を1280x720に設定
        self._monitor = {
            "left": self._monitor["left"],
            "top": self._monitor["top"],
            "width": 1280,
            "height": 720
        }
        
        self._timestamp = 0
        self._frame_rate = 30

    async def next_timestamp(self):
        """タイムスタンプを生成"""
        pts = self._timestamp
        self._timestamp += 1
        return pts, Fraction(1, self._frame_rate)

    async def recv(self):
        """Capture screen and return a video frame."""
        try:
            screen = self.sct.grab(self._monitor) # RGBA 32bit
            # 画像フォーマットの変換
            img = np.array(screen)
            img = img[:, :, [2, 1, 0, 3]]  # RGBA -> BGRA
            frame = av.VideoFrame.from_ndarray(img, format="bgra")
            pts, time_base = await self.next_timestamp()
            frame.pts = pts
            frame.time_base = time_base
            return frame
            
        except Exception as e:
            print(f"Error capturing frame: {e}")
            raise

async def index(request):
    content = open(os.path.join(ROOT, "index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)

async def javascript(request):
    content = open(os.path.join(ROOT, "client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)

import uuid

# Dictionary to store peer connections with their IDs
pcs = {}

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    # Generate unique ID for this connection
    connection_id = str(uuid.uuid4())
    pc = RTCPeerConnection()
    pcs[connection_id] = pc

    # 接続状態の監視
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # ICE接続状態の監視
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        pass

    # Add screen capture track with optimized settings
    video = ScreenCaptureTrack()
    sender = pc.addTrack(video)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
            "connectionId": connection_id
        }),
    )

def parse_candidate(candidate_str):
    # candidate:1920441499 1 tcp 1518283007 240d:1e:126:8605:3beb:aee7:7c31:ac39 51846 typ host tcptype passive ...
    parts = candidate_str.split()
    if not parts[0].startswith("candidate:"):
        return None
    
    foundation = parts[0].split(":")[1]
    component = int(parts[1])
    protocol = parts[2]
    priority = int(parts[3])
    ip = parts[4]
    port = int(parts[5])
    
    # find type
    try:
        type_index = parts.index("typ")
        candidate_type = parts[type_index + 1]
    except ValueError:
        candidate_type = "host"  # default type
    
    return {
        "foundation": foundation,
        "component": component,
        "protocol": protocol,
        "priority": priority,
        "ip": ip,
        "port": port,
        "type": candidate_type,
    }

async def handle_candidate(request):
    """ICE candidateの処理を行う"""
    params = await request.json()
    connection_id = params.get("connectionId")
    
    if not connection_id or connection_id not in pcs:
        return web.Response(status=400, text="Invalid connection ID")
        
    pc = pcs[connection_id]
    candidate_str = params["candidate"]
    sdp_mid = params.get("sdpMid")
    sdp_mline_index = params.get("sdpMLineIndex", 0)

    parsed = parse_candidate(candidate_str)
    if parsed is None:
        return web.Response(status=400, text="Invalid candidate string")

    candidate = RTCIceCandidate(
        foundation=parsed["foundation"],
        component=parsed["component"],
        protocol=parsed["protocol"],
        priority=parsed["priority"],
        ip=parsed["ip"],
        port=parsed["port"],
        type=parsed["type"],
        sdpMid=sdp_mid,
        sdpMLineIndex=sdp_mline_index,
    )

    await pc.addIceCandidate(candidate)
    return web.Response(text="OK")

async def on_shutdown(app):
    """アプリケーションのシャットダウン時の処理"""
    # WebRTC接続のクリーンアップ
    coros = [pc.close() for pc in pcs.values()]
    await asyncio.gather(*coros)
    pcs.clear()
    
    # ブラウザのクリーンアップ
    if hasattr(app, 'browser_controller'):
        app['browser_controller'].cleanup()

async def main():
    """WebRTCサーバーのメインエントリーポイント"""
    ssl_context = ssl.SSLContext()
    ssl_context.load_cert_chain("./cert/server.crt", "./cert/server.key")

    # アプリケーションの設定
    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    app.router.add_post("/candidate", handle_candidate)
    
    # ブラウザコントローラーの初期化と起動
    browser_controller = BrowserController()
    app['browser_controller'] = browser_controller
    if not await browser_controller.start_browser():
        return
    
    # サーバーの起動
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8443, ssl_context=ssl_context)
    await site.start()
    
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()

import asyncio
import json
import os
import ssl
import time
import mss
import numpy as np
import av
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig, BrowserContextConfig
from dotenv import load_dotenv
from fractions import Fraction
from langchain_openai import ChatOpenAI

# Load environment variables
load_dotenv()

ROOT = os.path.dirname(__file__)

class BrowserController:
    def __init__(self):
        self.browser = None
        
    def create_browser(self) -> Browser:
        """Create browser instance."""
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
        """Set Chrome window position and size.
        
        Args:
            x: Window x position
            y: Window y position
            width: Window width
            height: Window height
        """
        try:
            # 可視状態のChromeウィンドウを探す（一番最近のウィンドウを使用）
            window_ids = os.popen("xdotool search --onlyvisible --name 'Chrome'").read().strip().split('\n')
            if not window_ids:
                print("Chrome window not found")
                return False
            
            # 最後に作成されたウィンドウ（最新のウィンドウ）を使用
            window_id = window_ids[-1]
                
            # ウィンドウのサイズと位置を設定
            os.system(f'xdotool windowsize {window_id} {width} {height}')
            os.system(f'xdotool windowmove {window_id} {x} {y}')
            return True
        except Exception as e:
            print(f"Error setting window position and size: {e}")
            return False

    async def start_browser(self):
        """Start browser and navigate to a page."""
        try:
            self.browser = self.create_browser()
            model = ChatOpenAI(model='gpt-4o')
            agent = Agent(
                task="Navigate to about:blank",  # Start with blank page
                llm=model,
                controller=Controller(),
                browser=self.browser,
            )
            await agent.run()
            # Wait for the page to be fully loaded
            await asyncio.sleep(1)
            # Set window position and size to 640x720 at (0,0)
            await self.set_window_position_and_size(0, 0, 640, 720)
            return True
        except Exception as e:
            print(f"Error starting browser: {e}")
            return False
            
    def cleanup(self):
        """Clean up browser resources."""
        if self.browser:
            self.browser.quit()

class ScreenCaptureTrack(MediaStreamTrack):
    """Media track for capturing the virtual display screen."""
    kind = "video"

    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        # Get all monitors
        monitors = self.sct.monitors
        print("Available monitors:", monitors)  # デバッグ用：全モニター情報を表示
        
        # モニターの選択ロジック改善
        if len(monitors) > 1:
            # モニター1（プライマリモニター）を使用
            self._monitor = monitors[1]
            print("Selected primary monitor:", self._monitor)
        else:
            # 単一モニターの場合
            self._monitor = monitors[0]
            print("Using single monitor:", self._monitor)
            
        # キャプチャ範囲を1280x720に制限
        self._monitor = {
            "left": self._monitor["left"],
            "top": self._monitor["top"],
            "width": 1280,
            "height": 720
        }
        
        # フレームレートとタイムスタンプの管理用
        self._timestamp = 0
        self._frame_rate = 30
        print("Final capture area:", self._monitor)  # デバッグ用：最終的なキャプチャ範囲

    async def next_timestamp(self):
        """タイムスタンプを生成"""
        pts = self._timestamp
        self._timestamp += 1
        return pts, Fraction(1, self._frame_rate)

    async def recv(self):
        """Capture screen and return a video frame."""
        try:
            screen = self.sct.grab(self._monitor)
            # Print frame dimensions for debugging
            if hasattr(self, '_last_print_time') and time.time() - self._last_print_time < 5:
                pass  # Only print every 5 seconds
            else:
                print(f"Captured frame size: {screen.width}x{screen.height}")
                print(f"RGB values at center: {screen.pixel(screen.width//2, screen.height//2)}")
                self._last_print_time = time.time()

            # Convert to format suitable for av
            img = np.array(screen)
            # Convert BGRA to RGB
            img = img[:, :, :3]  # BGRA to BGR by selecting first 3 channels
            img = img[:, :, ::-1]  # BGR to RGB by reversing the color channels
            
            # Create video frame
            frame = av.VideoFrame.from_ndarray(img, format="rgb24")
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

pcs = set()

async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    # Connection state monitoring
    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # ICE connection state monitoring
    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print("ICE connection state is %s" % pc.iceConnectionState)

    # Data channel for optional messaging
    @pc.on("datachannel")
    def on_datachannel(channel):
        @channel.on("message")
        def on_message(message):
            print("Received message:", message)

    # Add screen capture track with optimized settings
    video = ScreenCaptureTrack()
    sender = pc.addTrack(video)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        ),
    )

async def on_shutdown(app):
    print("Cleaning up connections and resources...")
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    
    # cleanup browser if it exists
    if hasattr(app, 'browser_controller'):
        app['browser_controller'].cleanup()
    print("Cleanup completed")

async def main():
    import logging
    logging.basicConfig(level=logging.INFO)

    ssl_context = ssl.SSLContext()
    ssl_context.load_cert_chain("./server.crt", "./server.key")

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    
    print("Server running on https://34.133.108.164:8443")
    # Initialize browser controller
    browser_controller = BrowserController()
    app['browser_controller'] = browser_controller
    
    # Start browser in background
    success = await browser_controller.start_browser()
    if not success:
        print("Failed to start browser, exiting...")
        return
    
    # Run the application
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=8443, ssl_context=ssl_context)
    await site.start()
    
    # Keep the server running
    try:
        await asyncio.Event().wait()  # run forever
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()

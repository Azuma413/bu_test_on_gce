import asyncio
import json
import os
import ssl
import mss
import numpy as np
import av
from browser_use import BrowserCore
from fractions import Fraction
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription

ROOT = os.path.dirname(__file__)

class BrowserController:
    """Browser control using browser_use library."""
    def __init__(self):
        self.browser = BrowserCore()
        self.browser.browser_init()
        
    async def start_browser(self):
        """Start browser and navigate to a page."""
        try:
            # ブラウザを起動して特定のURLに移動
            self.browser.browser_access("https://www.google.com")
            print("Browser started successfully")
            # ブラウザの初期設定
            self.browser.wait_browser_complete()
            return True
        except Exception as e:
            print(f"Error starting browser: {e}")
            return False

    def navigate_to(self, url):
        """Navigate to specified URL."""
        try:
            self.browser.browser_access(url)
            self.browser.wait_browser_complete()
            print(f"Navigated to {url}")
            return True
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
            return False

    def click_element(self, selector):
        """Click element matching selector."""
        try:
            self.browser.browser_click(selector)
            self.browser.wait_browser_complete()
            print(f"Clicked element: {selector}")
            return True
        except Exception as e:
            print(f"Error clicking element {selector}: {e}")
            return False

    def enter_text(self, selector, text):
        """Enter text into element matching selector."""
        try:
            self.browser.browser_send_keys(selector, text)
            print(f"Entered text into {selector}")
            return True
        except Exception as e:
            print(f"Error entering text into {selector}: {e}")
            return False
            
    def cleanup(self):
        """Clean up browser resources."""
        try:
            self.browser.browser_close()
            print("Browser closed successfully")
        except Exception as e:
            print(f"Error closing browser: {e}")

class ScreenCaptureTrack(MediaStreamTrack):
    """Media track for capturing the virtual display screen."""
    kind = "video"

    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        self._monitor = {"top": 0, "left": 0, "width": 1280, "height": 720}
        # フレームレートとタイムスタンプの管理用
        self._timestamp = 0
        self._frame_rate = 30

    async def next_timestamp(self):
        """タイムスタンプを生成"""
        pts = self._timestamp
        self._timestamp += 1
        return pts, Fraction(1, self._frame_rate)

    async def recv(self):
        """Capture screen and return a video frame."""
        screen = self.sct.grab(self._monitor)
        # Convert to format suitable for av
        img = np.array(screen)
        # Convert BGRA to BGR by selecting first 3 channels
        img = img[:, :, :3]
        # Create video frame
        frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame

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

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # Add screen capture track
    video = ScreenCaptureTrack()
    pc.addTrack(video)

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
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    
    # cleanup browser if it exists
    if hasattr(app, 'browser_controller'):
        app['browser_controller'].cleanup()

async def main():
    parser = argparse.ArgumentParser(description="WebRTC screen capture demo with browser control")
    parser.add_argument("--cert-file", default="./server.crt", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", default="./server.key", help="SSL key file (for HTTPS)")
    parser.add_argument("--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port for HTTP server (default: 8080)")
    parser.add_argument("--verbose", "-v", action="count")

    args = parser.parse_args()

    import logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    ssl_context = ssl.SSLContext()
    ssl_context.load_cert_chain(args.cert_file, args.key_file)

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", offer)
    
    print("Server running on https://34.133.108.164:8080")
    # Initialize browser controller
    browser_controller = BrowserController()
    app['browser_controller'] = browser_controller
    
    # Start browser in background
    success = await browser_controller.start_browser()
    if not success:
        print("Failed to start browser, exiting...")
        return
    
    # Run the application
    return await web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)

if __name__ == "__main__":
    import argparse
    asyncio.run(main())

import asyncio
import json
import os
import ssl
import mss
import numpy as np
import av
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
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
            )
        )

    async def start_browser(self):
        """Start browser and navigate to a page."""
        try:
            self.browser = self.create_browser()
            model = ChatOpenAI(model='gpt-4o')
            agent = Agent(
                task="Navigate to https://www.google.com",
                llm=model,
                controller=Controller(),
                browser=self.browser,
            )
            await agent.run()
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
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=args.host, port=args.port, ssl_context=ssl_context)
    await site.start()
    
    # Keep the server running
    try:
        await asyncio.Event().wait()  # run forever
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    import argparse
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()

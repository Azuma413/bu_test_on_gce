import asyncio
import json
from typing import Optional
import av
import mss
import numpy as np
from aiohttp import web
from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer
from browser_use import Agent, Controller
from browser_use.browser.browser import Browser, BrowserConfig
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pyvirtualdisplay import Display

# Load environment variables
load_dotenv()

class ScreenCaptureTrack(MediaStreamTrack):
    """Media track for capturing the virtual display screen."""
    kind = "video"

    def __init__(self):
        super().__init__()
        self.sct = mss.mss()
        self._monitor = {"top": 0, "left": 0, "width": 1280, "height": 720}

    async def recv(self):
        """Capture screen and return a video frame."""
        screen = self.sct.grab(self._monitor)
        # Convert to format suitable for av
        img = np.array(screen)
        # Create video frame
        frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame

class WebRTCServer:
    def __init__(self):
        self.pcs = set()
        self.display = None
        self.browser = None

    async def create_virtual_display(self):
        """Create and start virtual display."""
        self.display = Display(visible=0, size=(1280, 720))
        self.display.start()

    def create_browser(self) -> Browser:
        """Create browser instance."""
        return Browser(
            config=BrowserConfig(
                headless=False,
                chrome_instance_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            )
        )

    async def initialize_browser_agent(self, task: str):
        """Initialize and run browser agent with specified task."""
        self.browser = self.create_browser()
        model = ChatOpenAI(model='gpt-4')
        agent = Agent(
            task=task,
            llm=model,
            controller=Controller(),
            browser=self.browser,
        )
        await agent.run()

    async def offer(self, request):
        """Handle WebRTC offer from client."""
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

        # Configure WebRTC with STUN server
        configuration = RTCConfiguration(
            iceServers=[
                {"urls": ["stun:stun.l.google.com:19302"]}
            ]
        )
        pc = RTCPeerConnection(configuration=configuration)
        self.pcs.add(pc)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        # Create screen capture track
        video = ScreenCaptureTrack()
        pc.addTrack(video)

        # Handle the offer
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            })
        )

    async def cleanup(self):
        """Cleanup resources."""
        # Close peer connections
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()

        # Close browser if open
        if self.browser:
            self.browser.quit()

        # Stop virtual display
        if self.display:
            self.display.stop()

async def main():
    # Create WebRTC server instance
    server = WebRTCServer()
    
    # Start virtual display
    await server.create_virtual_display()

    # Setup web application
    app = web.Application()
    app.router.add_post("/offer", server.offer)
    
    # Add cleanup on shutdown
    app.on_shutdown.append(lambda _: server.cleanup())

    # Initialize browser with a sample task
    await server.initialize_browser_agent("Navigate to https://www.google.com")

    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("Server running on http://localhost:8080")
    
    try:
        # Keep the server running
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

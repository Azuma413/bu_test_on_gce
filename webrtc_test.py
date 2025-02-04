import asyncio
import json
import ssl
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
        self.browser = None

    def create_browser(self) -> Browser:
        """Create browser instance."""
        return Browser(
            config=BrowserConfig(
                headless=False,
                # chrome_instance_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            )
        )

    async def initialize_browser_agent(self, task: str):
        """Initialize and run browser agent with specified task."""
        self.browser = self.create_browser()
        model = ChatOpenAI(model='gpt-4o')
        agent = Agent(
            task=task,
            llm=model,
            controller=Controller(),
            browser=self.browser,
        )
        await agent.run()

    async def offer(self, request):
        """Handle WebRTC offer from client."""
        try:
            params = await request.json()
            offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
            print(f"Received offer with type: {params['type']}")

            # Configure WebRTC with STUN and TURN servers
            configuration = RTCConfiguration(
                iceServers=[
                    {"urls": ["stun:stun.l.google.com:19302"]},
                    {
                        "urls": [
                            "turn:34.133.108.164:3478?transport=udp",
                            "turn:34.133.108.164:3478?transport=tcp"
                        ],
                        "username": "webrtc",
                        "credential": "webrtc"
                    }
                ],
                iceCandidatePoolSize=10,
                bundlePolicy="max-bundle",
                rtcpMuxPolicy="require"
            )
            pc = RTCPeerConnection(configuration=configuration)
            self.pcs.add(pc)

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                print(f"Connection state changed to: {pc.connectionState}")
                if pc.connectionState == "failed":
                    print("Connection failed - ICE connectivity check failed")
                    await pc.close()
                    self.pcs.discard(pc)
                elif pc.connectionState == "connected":
                    print("Connection established successfully")
                elif pc.connectionState == "disconnected":
                    print("Connection disconnected")

            @pc.on("iceconnectionstatechange")
            async def on_iceconnectionstatechange():
                print(f"ICE connection state changed to: {pc.iceConnectionState}")

            @pc.on("icegatheringstatechange")
            async def on_icegatheringstatechange():
                print(f"ICE gathering state changed to: {pc.iceGatheringState}")

            # Create screen capture track
            video = ScreenCaptureTrack()
            pc.addTrack(video)

            # Handle the offer
            await pc.setRemoteDescription(offer)
            print("Remote description set successfully")
            
            answer = await pc.createAnswer()
            print("Answer created successfully")
            
            await pc.setLocalDescription(answer)
            print("Local description set successfully")

            return web.Response(
                content_type="application/json",
                text=json.dumps({
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type
                })
            )
        except Exception as e:
            print(f"Error in offer handler: {str(e)}")
            return web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"error": str(e)})
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

async def main():
    # Create WebRTC server instance
    server = WebRTCServer()

    # Setup web application
    app = web.Application()
    
    # Setup CORS with more permissive settings
    # Setup CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type',
                'Access-Control-Max-Age': '3600',
            }
            return web.Response(headers=headers)
            
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    app.middlewares.append(cors_middleware)
    
    # Setup routes
    app.router.add_post("/offer", server.offer)
    
    # Add a basic handler for the root path
    async def index(request):
        return web.Response(text="WebRTC Server Running", content_type="text/plain")
    
    app.router.add_get("/", index)

    # Add cleanup on shutdown
    app.on_shutdown.append(lambda _: server.cleanup())

    # Initialize browser with a sample task
    await server.initialize_browser_agent("Navigate to https://www.google.com")

    # Start the server with SSL
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain('server.crt', 'server.key')
    ssl_context.verify_mode = ssl.CERT_NONE  # Allow self-signed certificates
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8443, ssl_context=ssl_context)
    await site.start()

    print(f"Server running on https://34.133.108.164:8443")
    print("WebRTC configuration initialized with STUN and TURN servers")

    try:
        # Keep the server running
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

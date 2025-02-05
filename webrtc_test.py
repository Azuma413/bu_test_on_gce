import asyncio
import json
import ssl
import time
from typing import Optional
import av
import mss
import numpy as np
import cv2
from aiohttp import web
from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpCodecParameters, RTCIceCandidate
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
        self._last_frame_time = 0
        self._frame_interval = 1/30  # 30 FPS

    async def recv(self):
        """Capture screen and return a video frame."""
        # フレームレート制御
        current_time = time.time()
        if current_time - self._last_frame_time < self._frame_interval:
            await asyncio.sleep(self._frame_interval - (current_time - self._last_frame_time))
        
        screen = self.sct.grab(self._monitor)
        img = np.array(screen)
        
        # BGRAからRGBに変換（Unity側はRGBを期待している）
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGB)
        
        # フレーム生成時にRGBフォーマットを明示的に指定
        frame = av.VideoFrame.from_ndarray(img, format='rgb24')
        frame.width = 1280
        frame.height = 720
        
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        self._last_frame_time = time.time()
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
            print(f"Received offer params: {json.dumps(params, indent=2)}")
            print(f"Parsing SDP offer content: {params['sdp'][:100]}...")  # Show first 100 chars
            
            try:
                offer = RTCSessionDescription(
                    sdp=params["sdp"],
                    type=params["type"].lower()  # Ensure type is lowercase
                )
                print(f"Created RTCSessionDescription successfully")
                print(f"Offer type: {offer.type}, SDP length: {len(offer.sdp)}")
            except Exception as e:
                print(f"Error creating RTCSessionDescription: {str(e)}")
                print(f"Received params type: {type(params['type'])}")
                print(f"Received params sdp type: {type(params['sdp'])}")
                raise

            # Configure WebRTC
            pc = RTCPeerConnection()
            print("Created RTCPeerConnection successfully")
            self.pcs.add(pc)
            print("Added peer connection to set")

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                print(f"Connection state changed to: {pc.connectionState}")
                if pc.connectionState == "failed":
                    await pc.close()
                    self.pcs.discard(pc)

            # Create screen capture track without forcing specific codec
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
        except Exception as e:
            print(f"Error in offer handler: {str(e)}")
            return web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"error": str(e)})
            )

    async def candidate(self, request):
        """Handle incoming ICE candidates."""
        try:
            params = await request.json()
            # Nullチェックを追加
            sdp_mline_index = params.get("sdpMLineIndex")
            if sdp_mline_index is None:
                sdp_mline_index = 0  # デフォルト値を設定
                
            # Get candidate data
            candidate_str = params["candidate"]
            if not candidate_str.startswith("candidate:"):
                candidate_str = "candidate:" + candidate_str

            print(f"Received ICE candidate string: {candidate_str}")
            print(f"sdpMid: {params.get('sdpMid', '')}")
            print(f"sdpMLineIndex: {sdp_mline_index}")

            # Create RTCIceCandidate ensuring proper format
            candidate = RTCIceCandidate(
                sdpMid=params.get("sdpMid", ""),
                sdpMLineIndex=sdp_mline_index,
                candidate=candidate_str
            )
            print(f"Created ICE candidate with: {candidate_str}")
            
            # Find the associated peer connection
            # In this simple example, we assume only one connection
            if len(self.pcs) > 0:
                pc = next(iter(self.pcs))
                await pc.addIceCandidate(candidate)
                print("Added ICE candidate successfully")
            else:
                print("No active peer connection to add ICE candidate to")
            
            return web.Response(
                content_type="application/json",
                text=json.dumps({"status": "ok"})
            )
        except Exception as e:
            print(f"Error handling ICE candidate: {str(e)}")
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
    
    # Setup CORS middleware
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "3600"
            }
            return web.Response(headers=headers)
        response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    app.middlewares.append(cors_middleware)
    
    # Setup routes
    app.router.add_post("/offer", server.offer)
    app.router.add_post("/candidate", server.candidate)  # Add route for ICE candidates
    
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

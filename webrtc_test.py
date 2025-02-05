import asyncio
import json
import os
import ssl
import mss
import numpy as np
import av
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription

ROOT = os.path.dirname(__file__)

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

async def index(request):
    """Serve index.html"""
    content = open(os.path.join(ROOT, "static/index.html"), "r").read()
    return web.Response(content_type="text/html", text=content)

async def javascript(request):
    """Serve client.js"""
    content = open(os.path.join(ROOT, "static/client.js"), "r").read()
    return web.Response(content_type="application/javascript", text=content)

class WebRTCServer:
    def __init__(self):
        self.pcs = set()

    async def offer(self, request):
        """Handle WebRTC offer from client."""
        try:
            params = await request.json()
            offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
            print(f"Received offer with type: {params['type']}")

            # Configure WebRTC with STUN server
            pc = RTCPeerConnection(
                configuration={
                    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
                }
            )
            self.pcs.add(pc)

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                print(f"Connection state is {pc.connectionState}")
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
        except Exception as e:
            print(f"Error in offer handler: {str(e)}")
            return web.Response(
                status=500,
                content_type="application/json",
                text=json.dumps({"error": str(e)})
            )

    async def cleanup(self):
        """Cleanup resources."""
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()

async def on_shutdown(app):
    """Cleanup when shutting down."""
    server = app["server"]
    await server.cleanup()

async def main():
    # Create WebRTC server instance
    server = WebRTCServer()

    # Setup web application
    app = web.Application()
    app["server"] = server

    # Setup routes
    app.router.add_get("/", index)
    app.router.add_get("/client.js", javascript)
    app.router.add_post("/offer", server.offer)

    # Add cleanup on shutdown
    app.on_shutdown.append(on_shutdown)

    # SSL configuration
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain('server.crt', 'server.key')
    
    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8443, ssl_context=ssl_context)
    await site.start()

    print(f"Server running on https://34.133.108.164:8443")
    print("WebRTC server is ready")

    try:
        # Keep the server running
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

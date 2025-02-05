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
        # フレームレートとタイムスタンプの管理用
        self._timestamp = 0
        self._frame_rate = 30
        self._time_base = 1 / self._frame_rate

    async def next_timestamp(self):
        """タイムスタンプを生成"""
        pts = self._timestamp
        self._timestamp += 1
        return pts, self._time_base

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

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="WebRTC screen capture demo")
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
    web.run_app(app, host=args.host, port=args.port, ssl_context=ssl_context)

import os, uuid, httpx, uvicorn, moment
from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone

app = FastAPI()

# --- DATA FROM YOUR INDEX.JS ---
GENRES = {
    "Kids": ["Kids", "Children & Family", "Cartoons", "Ages 2-4"],
    "News": ["News + Opinion", "General News"],
    "Sports": ["Sports", "Sports Highlights"],
    # ... (I will include all your mappings in the final repo)
}

STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "9.19.0-7a6c115631d945c4f7327de3e03b7c474b692657"

async def get_v4_auth():
    """The Bypass Handshake you need for 2026."""
    device_id = str(uuid.uuid1())
    sid = str(uuid.uuid4())
    async with httpx.AsyncClient() as client:
        boot_url = f"https://boot.pluto.tv/v4/start"
        params = {
            "appName": "web", "appVersion": APP_VERSION,
            "deviceType": "web", "deviceID": device_id,
            "sid": sid, "include": "session"
        }
        # Note: If user provides PLUTO_USERNAME in HF Secrets, we add it here
        res = await client.get(boot_url, params=params)
        return res.json().get("sessionToken"), device_id, sid

@app.get("/playlist.m3u")
async def playlist():
    """Generates the M3U8 using your custom formatting."""
    async with httpx.AsyncClient() as client:
        # Fetching channels from the v2 API as your script did
        resp = await client.get("https://api.pluto.tv/v2/channels")
        channels = resp.json()

    m3u = ["#EXTM3U"]
    for ch in channels:
        if not ch.get("isStitched"): continue
        
        # Your custom formatting logic
        cid = ch["_id"]
        name = ch["name"]
        logo = ch["colorLogoPNG"]["path"]
        group = ch["category"]
        
        # Point the URL to our local bypass endpoint
        stream_url = f"/play/{cid}.m3u8"
        
        m3u.append(f'#EXTINF:0 channel-id="{ch["slug"]}" tvg-logo="{logo}" group-title="{group}", {name}')
        m3u.append(stream_url)
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    """The real-time bypass redirect."""
    token, dev_id, sid = await get_v4_auth()
    # Your specific stitcher URL structure
    final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/master.m3u8?jwt={token}&deviceId={dev_id}&sid={sid}&masterJWTPassthrough=true"
    return RedirectResponse(url=final_url)

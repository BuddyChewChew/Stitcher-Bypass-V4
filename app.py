import os, uuid, httpx, uvicorn, xml.etree.ElementTree as ET
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4-ProLogger")

STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "5.12.3"
CHANNELS_API = "https://api.pluto.tv/v2/channels"

async def get_v4_auth():
    """V4 Handshake with detailed logging for debugging."""
    device_id = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    print(f"[DEBUG] Starting Handshake: Device={device_id[:8]} SID={sid[:8]}")
    
    username = os.getenv("PLUTO_USERNAME")
    password = os.getenv("PLUTO_PASSWORD")

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            # 1. Boot Handshake
            boot_url = "https://boot.pluto.tv/v4/start"
            params = {
                "appName": "web", "appVersion": APP_VERSION,
                "deviceType": "web", "deviceMake": "chrome",
                "deviceID": device_id, "sid": sid,
                "clientTime": datetime.now(timezone.utc).isoformat(),
            }
            if username and password:
                params["username"], params["password"] = username, password

            boot_res = await client.get(boot_url, params=params)
            jwt = boot_res.json().get("sessionToken")
            print(f"[DEBUG] JWT Obtained: {jwt[:15]}...")
            
            # 2. Session Activation
            try:
                act_url = f"https://api.pluto.tv/v3/session.json?sid={sid}&deviceId={device_id}"
                act_res = await client.get(act_url, headers={"Authorization": f"Bearer {jwt}"})
                print(f"[DEBUG] Session Activation Status: {act_res.status_code}")
            except Exception as ae:
                print(f"[DEBUG] Activation Warning: {ae}")

            return jwt, device_id, sid
        except Exception as e:
            print(f"[ERROR] Handshake Failed: {e}")
            return None, device_id, sid

@app.get("/")
async def root():
    return {"status": "online", "logs": "Check terminal for live output"}

@app.get("/playlist.m3u")
async def playlist(request: Request):
    print("[INFO] M3U Playlist requested")
    base_url = str(request.base_url).rstrip("/")
    if "hf.space" in base_url and not base_url.startswith("https"):
        base_url = base_url.replace("http", "https")
        
    async with httpx.AsyncClient() as client:
        resp = await client.get(CHANNELS_API)
        channels = resp.json()

    m3u = [f'#EXTM3U x-tvg-url="{base_url}/epg.xml"']
    for ch in channels:
        if not ch.get("isStitched"): continue
        cid = ch["_id"]
        m3u.append(f'#EXTINF:0 channel-id="{cid}" tvg-id="{cid}" group-title="{ch.get("category", "Pluto")}", {ch["name"]}')
        m3u.append(f"{base_url}/play/{cid}.m3u8")
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    print(f"[INFO] Playing Channel: {cid}")
    token, dev_id, sid = await get_v4_auth()
    
    final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
    params = {
        "jwt": token if token else "",
        "deviceId": dev_id,
        "sid": sid,
        "appName": "web",
        "appVersion": APP_VERSION,
        "deviceType": "web"
    }
    target = f"{final_url}?{httpx.QueryParams(params)}"
    print(f"[DEBUG] Redirecting to Pluto Stitcher...")
    return RedirectResponse(url=target, status_code=302)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)

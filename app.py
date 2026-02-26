import os, uuid, httpx, uvicorn
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4")

STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "9.19.0-7a6c115631d945c4f7327de3e03b7c474b692657"

async def get_v4_auth():
    """Performs the full V4 Handshake including Session Activation."""
    device_id = str(uuid.uuid1())
    sid = str(uuid.uuid4())
    client_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    
    username = os.getenv("PLUTO_USERNAME")
    password = os.getenv("PLUTO_PASSWORD")

    async with httpx.AsyncClient(timeout=10.0) as client:
        boot_url = "https://boot.pluto.tv/v4/start"
        params = {
            "appName": "web",
            "appVersion": APP_VERSION,
            "deviceType": "web",
            "deviceMake": "firefox",
            "deviceID": device_id,
            "sid": sid,
            "clientTime": client_time,
            "include": "session",
        }
        
        if username and password:
            params["username"] = username
            params["password"] = password

        boot_res = await client.get(boot_url, params=params)
        data = boot_res.json()
        jwt = data.get("sessionToken")

        # Session Activation (Prevents 'Device Not Supported' 403 Errors)
        act_url = f"https://api.pluto.tv/v3/session.json?sid={sid}&deviceId={device_id}"
        await client.get(act_url, headers={"Authorization": f"Bearer {jwt}"})

        return jwt, device_id, sid

@app.get("/")
async def root():
    return {"status": "online", "message": "Stitcher-Bypass-V4 Proxy is active."}

@app.get("/playlist.m3u")
async def playlist(request: Request):
    """Generates the M3U8 with dynamic URLs."""
    base_url = str(request.base_url).rstrip("/")
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.pluto.tv/v2/channels")
        channels = resp.json()

    m3u = ["#EXTM3U"]
    for ch in channels:
        if not ch.get("isStitched"): continue
        cid = ch["_id"]
        name = ch["name"]
        logo = ch.get("colorLogoPNG", {}).get("path", "")
        group = ch.get("category", "Pluto TV")
        stream_url = f"{base_url}/play/{cid}.m3u8"
        
        m3u.append(f'#EXTINF:0 channel-id="{ch.get("slug")}" tvg-logo="{logo}" group-title="{group}", {name}')
        m3u.append(stream_url)
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    """The real-time bypass redirect."""
    try:
        token, dev_id, sid = await get_v4_auth()
        final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
        query = {
            "jwt": token, "deviceId": dev_id, "sid": sid,
            "appName": "web", "appVersion": APP_VERSION, "deviceType": "web"
        }
        return RedirectResponse(url=f"{final_url}?{httpx.QueryParams(query)}")
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)

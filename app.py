import os, uuid, httpx, uvicorn, xml.etree.ElementTree as ET
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4-UltraSafe")

# Constants
STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "5.12.3"
CHANNELS_API = "https://api.pluto.tv/v2/channels"

async def get_v4_auth():
    """Handshake that works for both Guests and Users."""
    device_id = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    client_time = datetime.now(timezone.utc).isoformat()
    
    # These will be None if you didn't set them (which is fine!)
    username = os.getenv("PLUTO_USERNAME")
    password = os.getenv("PLUTO_PASSWORD")

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            # 1. Boot Handshake (Requesting a Guest or User Token)
            boot_url = "https://boot.pluto.tv/v4/start"
            params = {
                "appName": "web", "appVersion": APP_VERSION,
                "deviceType": "web", "deviceMake": "chrome",
                "deviceID": device_id, "sid": sid,
                "clientTime": client_time,
            }
            if username and password:
                params["username"], params["password"] = username, password

            boot_res = await client.get(boot_url, params=params)
            boot_data = boot_res.json()
            jwt = boot_data.get("sessionToken")
            
            # 2. Session Activation (Optional but helpful)
            # We wrap this in its own try/except so if it fails, the app doesn't 500.
            try:
                act_url = f"https://api.pluto.tv/v3/session.json?sid={sid}&deviceId={device_id}"
                await client.get(act_url, headers={"Authorization": f"Bearer {jwt}"}, timeout=5.0)
            except:
                print("Session activation failed, proceeding anyway...")

            return jwt, device_id, sid
        except Exception as e:
            print(f"Handshake Error: {e}")
            return None, device_id, sid

@app.get("/")
async def root():
    return {"status": "online", "info": "Add /playlist.m3u to TiviMate"}

@app.get("/playlist.m3u")
async def playlist(request: Request):
    base_url = str(request.base_url).rstrip("/")
    if "hf.space" in base_url and not base_url.startswith("https"):
        base_url = base_url.replace("http", "https")
        
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(CHANNELS_API)
            channels = resp.json()

        m3u = [f'#EXTM3U x-tvg-url="{base_url}/epg.xml"']
        for ch in channels:
            if not ch.get("isStitched"): continue
            cid = ch["_id"]
            logo = ch.get("colorLogoPNG", {}).get("path", "")
            m3u.append(f'#EXTINF:0 channel-id="{cid}" tvg-id="{cid}" tvg-logo="{logo}" group-title="{ch.get("category", "Pluto TV")}", {ch["name"]}')
            m3u.append(f"{base_url}/play/{cid}.m3u8")
        
        return Response(content="\n".join(m3u), media_type="application/x-mpegURL")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    # This will now always return SOMETHING instead of a 500 error
    token, dev_id, sid = await get_v4_auth()
    
    final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
    params = {
        "jwt": token if token else "", # Use empty string if guest token failed
        "deviceId": dev_id,
        "sid": sid,
        "appName": "web",
        "appVersion": APP_VERSION,
        "deviceType": "web",
        "masterJWTPassthrough": "true"
    }
    # 302 redirect is most compatible with TiviMate
    return RedirectResponse(url=f"{final_url}?{httpx.QueryParams(params)}", status_code=302)

if __name__ == "__main__":
    # DO NOT CHANGE THE PORT. Hugging Face requires 7860.
    uvicorn.run(app, host="0.0.0.0", port=7860)

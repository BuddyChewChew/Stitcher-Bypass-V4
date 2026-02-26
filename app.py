import os, uuid, httpx, uvicorn, xml.etree.ElementTree as ET
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4-Fixed")

# Constants
STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "5.12.3"
CHANNELS_API = "https://api.pluto.tv/v2/channels"

async def get_v4_auth():
    """Robust V4 Handshake with crash protection."""
    device_id = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    print(f"[DEBUG] Handshake attempt: Device={device_id[:8]}")
    
    username = os.getenv("PLUTO_USERNAME")
    password = os.getenv("PLUTO_PASSWORD")

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            boot_url = "https://boot.pluto.tv/v4/start"
            params = {
                "appName": "web", "appVersion": APP_VERSION,
                "deviceType": "web", "deviceMake": "chrome",
                "deviceID": device_id, "sid": sid,
                "clientTime": datetime.now(timezone.utc).isoformat(),
            }
            if username and password:
                params["username"], params["password"] = username, password

            resp = await client.get(boot_url, params=params)
            
            # Fix for 'NoneType' error: check if response is valid JSON
            if resp.status_code == 200:
                data = resp.json()
                jwt = data.get("sessionToken", "")
                print(f"[DEBUG] Handshake successful. Token found.")
                return jwt, device_id, sid
            else:
                print(f"[WARNING] Pluto returned status {resp.status_code}. Using fallback.")
                return "", device_id, sid
        except Exception as e:
            print(f"[ERROR] Handshake failed: {e}")
            return "", device_id, sid

@app.get("/")
async def root():
    return {"status": "online", "playlist": "/playlist.m3u", "epg": "/epg.xml"}

@app.get("/playlist.m3u")
async def playlist(request: Request):
    print("[INFO] M3U Requested")
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
        grp = ch.get("category", "Pluto TV")
        logo = ch.get("colorLogoPNG", {}).get("path", "")
        m3u.append(f'#EXTINF:0 channel-id="{cid}" tvg-id="{cid}" tvg-logo="{logo}" group-title="{grp}", {ch["name"]}')
        m3u.append(f"{base_url}/play/{cid}.m3u8")
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/epg.xml")
async def epg():
    """Fixed EPG endpoint (was returning 404 in logs)"""
    print("[INFO] EPG Requested")
    async with httpx.AsyncClient() as client:
        resp = await client.get(CHANNELS_API)
        channels = resp.json()
    
    root = ET.Element("tv")
    for ch in channels:
        if not ch.get("isStitched"): continue
        chan_el = ET.SubElement(root, "channel", id=ch["_id"])
        ET.SubElement(chan_el, "display-name").text = ch["name"]
        
        for prog in ch.get("timelines", []):
            try:
                start = datetime.fromisoformat(prog["start"].replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S +0000")
                stop = datetime.fromisoformat(prog["stop"].replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S +0000")
                prog_el = ET.SubElement(root, "programme", start=start, stop=stop, channel=ch["_id"])
                ET.SubElement(prog_el, "title").text = prog.get("title", "No Title")
                ET.SubElement(prog_el, "desc").text = prog.get("description", "")
            except: continue
            
    return Response(content=ET.tostring(root, encoding="utf-8", xml_declaration=True), media_type="application/xml")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    print(f"[INFO] Playing: {cid}")
    token, dev_id, sid = await get_v4_auth()
    
    # Construct Pluto Stitcher URL
    final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
    params = {
        "appName": "web",
        "appVersion": APP_VERSION,
        "deviceType": "web",
        "deviceId": dev_id,
        "sid": sid,
        "masterJWTPassthrough": "true"
    }
    if token:
        params["jwt"] = token

    return RedirectResponse(url=f"{final_url}?{httpx.QueryParams(params)}", status_code=302)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)

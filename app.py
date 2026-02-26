import os, uuid, httpx, uvicorn, xml.etree.ElementTree as ET
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse, JSONResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4-Debug")

STITCHER_HOST = "cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv"
APP_VERSION = "5.12.3"
CHANNELS_API = "https://api.pluto.tv/v2/channels"

async def get_v4_auth():
    """Enhanced V4 Handshake with session activation."""
    device_id = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    client_time = datetime.now(timezone.utc).isoformat()
    
    username = os.getenv("PLUTO_USERNAME")
    password = os.getenv("PLUTO_PASSWORD")

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # 1. Boot Handshake
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
        boot_res.raise_for_status()
        jwt = boot_res.json().get("sessionToken")
        
        # 2. Session Activation
        act_url = f"https://api.pluto.tv/v3/session.json?sid={sid}&deviceId={device_id}"
        headers = {"Authorization": f"Bearer {jwt}", "Origin": "https://pluto.tv"}
        await client.get(act_url, headers=headers)
        
        return jwt, device_id, sid

@app.get("/")
async def root():
    return {"status": "online", "message": "Visit /debug/{channel_id} to test stream access."}

@app.get("/debug/{cid}")
async def debug_stream(cid: str):
    """
    Test endpoint: Instead of redirecting your browser, the SERVER 
    attempts to fetch the playlist and reports what Pluto says.
    """
    try:
        token, dev_id, sid = await get_v4_auth()
        url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
        params = {
            "jwt": token, "deviceId": dev_id, "sid": sid,
            "appName": "web", "appVersion": APP_VERSION, "deviceType": "web"
        }
        
        async with httpx.AsyncClient() as client:
            # We try to 'peek' at the stream Pluto sends back
            resp = await client.get(url, params=params)
            
            return JSONResponse({
                "target_url": str(resp.url),
                "pluto_response_code": resp.status_code,
                "pluto_headers": dict(resp.headers),
                "hint": "If status is 403 or 460, Pluto is blocking the Hugging Face IP."
            })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/playlist.m3u")
async def playlist(request: Request):
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
        logo = ch.get("colorLogoPNG", {}).get("path", "")
        m3u.append(f'#EXTINF:0 channel-id="{cid}" tvg-id="{cid}" tvg-logo="{logo}" group-title="{ch.get("category", "Pluto TV")}", {ch["name"]}')
        m3u.append(f"{base_url}/play/{cid}.m3u8")
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/epg.xml")
async def get_epg():
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
            except: continue
    return Response(content=ET.tostring(root, encoding="utf-8", xml_declaration=True), media_type="application/xml")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    try:
        token, dev_id, sid = await get_v4_auth()
        final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
        params = {
            "jwt": token, "deviceId": dev_id, "sid": sid,
            "appName": "web", "appVersion": APP_VERSION, "deviceType": "web",
            "clientTime": datetime.now(timezone.utc).isoformat(),
            "masterJWTPassthrough": "true"
        }
        return RedirectResponse(url=f"{final_url}?{httpx.QueryParams(params)}", status_code=302)
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)

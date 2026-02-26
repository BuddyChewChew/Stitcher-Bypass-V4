import os, uuid, httpx, uvicorn, xml.etree.ElementTree as ET
from fastapi import FastAPI, Response, Request
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone

app = FastAPI(title="Stitcher-Bypass-V4")

# Config Constants
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
        # 1. Boot Handshake
        boot_url = "https://boot.pluto.tv/v4/start"
        params = {
            "appName": "web", "appVersion": APP_VERSION,
            "deviceType": "web", "deviceMake": "firefox",
            "deviceID": device_id, "sid": sid,
            "clientTime": client_time, "include": "session",
        }
        if username and password:
            params["username"], params["password"] = username, password

        boot_res = await client.get(boot_url, params=params)
        jwt = boot_res.json().get("sessionToken")
        
        # 2. Session Activation (Crucial for 2026 Bypass)
        act_url = f"https://api.pluto.tv/v3/session.json?sid={sid}&deviceId={device_id}"
        await client.get(act_url, headers={"Authorization": f"Bearer {jwt}"})
        
        return jwt, device_id, sid

@app.get("/")
async def root():
    return {
        "status": "online", 
        "playlist": "/playlist.m3u", 
        "epg": "/epg.xml",
        "note": "Add /playlist.m3u to your player for auto-EPG loading."
    }

@app.get("/playlist.m3u")
async def playlist(request: Request):
    """Generates M3U8 with x-tvg-url header for one-link setup."""
    base_url = str(request.base_url).rstrip("/")
    epg_url = f"{base_url}/epg.xml"
    
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.pluto.tv/v2/channels")
        channels = resp.json()

    # The header tells the player to automatically fetch the EPG from our endpoint
    m3u = [f'#EXTM3U x-tvg-url="{epg_url}"']
    
    for ch in channels:
        if not ch.get("isStitched"): continue
        cid = ch["_id"]
        logo = ch.get("colorLogoPNG", {}).get("path", "")
        group = ch.get("category", "Pluto TV")
        
        m3u.append(f'#EXTINF:0 channel-id="{cid}" tvg-id="{cid}" tvg-logo="{logo}" group-title="{group}", {ch["name"]}')
        m3u.append(f"{base_url}/play/{cid}.m3u8")
    
    return Response(content="\n".join(m3u), media_type="application/x-mpegURL")

@app.get("/epg.xml")
async def get_epg():
    """Generates a professional XMLTV guide."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.pluto.tv/v2/channels")
        channels = resp.json()
        
    root = ET.Element("tv")
    
    for ch in channels:
        if not ch.get("isStitched"): continue
        cid = ch["_id"]
        
        # Channel metadata
        chan_el = ET.SubElement(root, "channel", id=cid)
        ET.SubElement(chan_el, "display-name").text = ch["name"]
        if "colorLogoPNG" in ch:
            ET.SubElement(chan_el, "icon", src=ch["colorLogoPNG"]["path"])

        # Programming timelines
        for prog in ch.get("timelines", []):
            try:
                # Convert Pluto time to XMLTV format (YYYYMMDDHHMMSS +0000)
                start = datetime.fromisoformat(prog["start"].replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S +0000")
                stop = datetime.fromisoformat(prog["stop"].replace("Z", "+00:00")).strftime("%Y%m%d%H%M%S +0000")
                
                prog_el = ET.SubElement(root, "programme", start=start, stop=stop, channel=cid)
                ET.SubElement(prog_el, "title").text = prog.get("title", "No Title")
                
                desc = prog.get("episode", {}).get("description", "No Description")
                ET.SubElement(prog_el, "desc").text = desc
                
                # Add category based on series type
                if "episode" in prog and "series" in prog["episode"]:
                    cat = prog["episode"]["series"].get("type", "TV")
                    ET.SubElement(prog_el, "category").text = cat
            except:
                continue

    xml_data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return Response(content=xml_data, media_type="application/xml")

@app.get("/play/{cid}.m3u8")
async def play(cid: str):
    """Dynamic redirect to Pluto's stitcher with authenticated V4 JWT."""
    try:
        token, dev_id, sid = await get_v4_auth()
        final_url = f"https://{STITCHER_HOST}/v2/stitch/hls/channel/{cid}/playlist.m3u8"
        query = {
            "jwt": token, "deviceId": dev_id, "sid": sid,
            "appName": "web", "appVersion": APP_VERSION, "deviceType": "web",
            "masterJWTPassthrough": "true"
        }
        return RedirectResponse(url=f"{final_url}?{httpx.QueryParams(query)}")
    except Exception as e:
        return Response(content=f"Stream Error: {str(e)}", status_code=500)

if __name__ == "__main__":
    # Hugging Face default port
    uvicorn.run(app, host="0.0.0.0", port=7860)

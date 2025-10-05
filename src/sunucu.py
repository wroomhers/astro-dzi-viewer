# -*- coding: utf-8 -*-
# sunucu.py — FastAPI + ZMQ SUB + ROI tile server (Python 3.8 uyumlu)

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
import asyncio, contextlib
from typing import Optional

import zmq
import zmq.asyncio
import cv2
import numpy as np

app = FastAPI(title="ZMQ ROI Tile Server")

# ZMQ ayarlari
ZMQ_ENDPOINT = "tcp://127.0.0.1:5555"  # producer burada PUB.bind yapacak
ZMQ_TOPIC = b"img"                      # topic (gecici olarak b"" da kullanilabilir)

# Bellekte en son JPEG ve versiyon
_latest_bytes: Optional[bytes] = None
_latest_version: int = 0
_lock = asyncio.Lock()

# Decode cache (ayni versiyonu tekrar tekrar decode etmeyelim)
_decoded_img: Optional[np.ndarray] = None
_decoded_ver: int = -1

# Yeni kare geldiginde MJPEG icin tetikleme
_frame_event = asyncio.Event()


async def sub_loop():
    global _latest_bytes, _latest_version
    ctx = zmq.asyncio.Context.instance()
    sub = ctx.socket(zmq.SUB)
    # Kuyruk birikmesin, her zaman en yeni kalsin
    sub.setsockopt(zmq.CONFLATE, 1)
    # Tum topic'leri al: sub.setsockopt(zmq.SUBSCRIBE, b"")
    sub.setsockopt(zmq.SUBSCRIBE, ZMQ_TOPIC)
    sub.connect(ZMQ_ENDPOINT)
    print("[SUB] connecting to", ZMQ_ENDPOINT)

    try:
        while True:
            parts = await sub.recv_multipart()
            if len(parts) == 2:
                topic, payload = parts
            else:
                payload = parts[-1]

            async with _lock:
                _latest_bytes = payload
                _latest_version += 1
                # decode cache'i gecersiz kil
                global _decoded_img, _decoded_ver
                _decoded_img = None
                _decoded_ver = -1
                _frame_event.set()
    except asyncio.CancelledError:
        pass
    finally:
        sub.close(0)


@app.on_event("startup")
async def on_startup():
    print("[APP] startup: launching SUB loop")
    app.state.sub_task = asyncio.create_task(sub_loop())


@app.on_event("shutdown")
async def on_shutdown():
    app.state.sub_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.sub_task


@app.get("/health")
def health():
    has_img = _latest_bytes is not None
    return {"ok": True, "has_image": has_img, "version": _latest_version}


def _get_decoded_image():
    """En son JPEG'i decode et ve cache'le."""
    global _decoded_img, _decoded_ver
    data = _latest_bytes
    ver = _latest_version
    if data is None:
        return None, ver
    if _decoded_img is not None and _decoded_ver == ver:
        return _decoded_img, ver
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None, ver
    _decoded_img = img
    _decoded_ver = ver
    return img, ver


@app.get("/image")
async def get_image(if_none_match: Optional[str] = None):
    """Tam son kareyi JPEG olarak dondur (debug/tespit icin)."""
    # JPEG'i dogrudan dondur; cache header'lari ile
    async with _lock:
        if _latest_bytes is None:
            return PlainTextResponse("No image yet", status_code=404)
        etag = 'W/"{}"'.format(_latest_version)
        data = _latest_bytes

    if if_none_match and if_none_match.strip() == etag:
        resp = Response(status_code=304)
        resp.headers["ETag"] = etag
        return resp

    resp = Response(content=data, media_type="image/jpeg")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/tile")
def tile(x: int, y: int, w: int, h: int, out_w: int, out_h: int):
    """
    Goruntunun [x,y,w,h] ROI'sini al, out_w x out_h boyutuna olce ve JPEG dondur.
    Tum parametreler piksel cinsinden; resim koordinatlarinda (sol-ust 0,0).
    """
    img, ver = _get_decoded_image()
    if img is None:
        return PlainTextResponse("No image yet", status_code=404)

    H, W = img.shape[:2]
    if w <= 0 or h <= 0 or out_w <= 0 or out_h <= 0:
        return PlainTextResponse("invalid sizes", status_code=400)

    # ROI sinirlari
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = min(w, W - x)
    h = min(h, H - y)
    if w <= 0 or h <= 0:
        return PlainTextResponse("empty roi", status_code=400)

    roi = img[y:y+h, x:x+w]
    resized = cv2.resize(roi, (out_w, out_h), interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    if not ok:
        return PlainTextResponse("encode error", status_code=500)

    etag = 'W/"{}-{}-{}-{}-{}-{}-{}"'.format(ver, x, y, w, h, out_w, out_h)
    resp = Response(content=enc.tobytes(), media_type="image/jpeg")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def mjpeg_generator():
    """Istege bagli: MJPEG stream (/video)."""
    boundary = b"--frame"
    last_ver = -1
    while True:
        await _frame_event.wait()
        async with _lock:
            data = _latest_bytes
            ver = _latest_version
            _frame_event.clear()
        if data is None or ver == last_ver:
            continue
        last_ver = ver
        head = (
            boundary + b"\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Cache-Control: no-cache\r\n\r\n"
        )
        yield head + data + b"\r\n"


@app.get("/video")
def video():
    return StreamingResponse(mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pan/Zoom Viewer</title>
  <style>
    html,body{height:100%;margin:0;background:#111;color:#eee;font-family:system-ui,Arial}
    #toolbar{position:fixed;top:8px;left:8px;z-index:10;background:#222;padding:8px 10px;border-radius:10px;border:1px solid #333}
    #toolbar input{width:120px;background:#111;color:#eee;border:1px solid #333;border-radius:6px;padding:4px}
    #canvas{width:100vw;height:100vh;display:block;image-rendering: crisp-edges;}
    button{background:#2d6cdf;color:#fff;border:none;border-radius:8px;padding:6px 10px;margin-left:6px;cursor:pointer}
    a{color:#9dc1ff}
  </style>
</head>
<body>
  <div id="toolbar">
    Zoom: <input id="zoom" type="number" value="1.0" step="0.1" min="0.1">
    <button id="fit">Fit</button>
    <a href="/video" target="_blank">MJPEG</a>
    <span id="info"></span>
  </div>
  <canvas id="canvas"></canvas>
<script>
(function(){
  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');
  const zoomInp = document.getElementById('zoom');
  const fitBtn = document.getElementById('fit');
  const info = document.getElementById('info');

  function resizeCanvas(){
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(canvas.clientWidth * dpr);
    canvas.height = Math.floor(canvas.clientHeight * dpr);
    ctx.setTransform(1,0,0,1,0,0);
    ctx.scale(dpr, dpr);
  }
  function ensureClientSize(){
    canvas.style.width = "100vw";
    canvas.style.height = "100vh";
    resizeCanvas();
  }
  ensureClientSize();
  window.addEventListener('resize', ()=>{ ensureClientSize(); requestDraw(); });

  let imgW = 4096, imgH = 4096; // baslangic tahmini; ilk /image ile dogrulanacak
  let scale = 1.0;
  let originX = 0, originY = 0;
  let redrawScheduled = false;

  async function detectImageSize(){
    try {
      const r = await fetch('/image', {cache:'no-cache'});
      if (r.ok) {
        const b = await r.blob();
        const bmp = await createImageBitmap(b);
        imgW = bmp.width; imgH = bmp.height;
        bmp.close();
      }
    } catch(e){}
  }
  detectImageSize();

  function screenToWorld(px, py){
    return {x: originX + px/scale, y: originY + py/scale};
  }
  function clampView(){
    const viewW = canvas.clientWidth / scale;
    const viewH = canvas.clientHeight / scale;
    originX = Math.max(0, Math.min(originX, Math.max(0, imgW - viewW)));
    originY = Math.max(0, Math.min(originY, Math.max(0, imgH - viewH)));
  }
  function fitView(){
    const sx = canvas.clientWidth  / (imgW || 1);
    const sy = canvas.clientHeight / (imgH || 1);
    scale = Math.max(0.1, Math.min(sx, sy));
    originX = 0; originY = 0;
    zoomInp.value = scale.toFixed(2);
    requestDraw();
  }
  fitBtn.onclick = fitView;
  zoomInp.onchange = ()=>{
    const val = parseFloat(zoomInp.value || "1");
    const center = screenToWorld(canvas.clientWidth/2, canvas.clientHeight/2);
    scale = Math.max(0.1, Math.min(val, 100));
    originX = center.x - (canvas.clientWidth/2)/scale;
    originY = center.y - (canvas.clientHeight/2)/scale;
    clampView();
    requestDraw();
  };

  // Pan (drag)
  let dragging=false, lastX=0, lastY=0;
  canvas.addEventListener('mousedown', (e)=>{
    dragging=true; lastX=e.clientX; lastY=e.clientY;
  });
  window.addEventListener('mouseup', ()=> dragging=false);
  window.addEventListener('mousemove', (e)=>{
    if(!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    originX -= dx/scale;
    originY -= dy/scale;
    clampView();
    requestDraw();
  });

  // Wheel zoom (cursor merkezli)
  canvas.addEventListener('wheel', (e)=>{
    e.preventDefault();
    const factor = (Math.sign(e.deltaY) > 0) ? 0.9 : 1.1;
    const mx = e.clientX, my = e.clientY;
    const before = screenToWorld(mx, my);
    scale = Math.max(0.1, Math.min(scale*factor, 100));
    const after = screenToWorld(mx, my);
    originX += (before.x - after.x);
    originY += (before.y - after.y);
    zoomInp.value = scale.toFixed(2);
    clampView();
    requestDraw();
  }, {passive:false});

  async function draw(){
    redrawScheduled = false;
    ctx.fillStyle = "#000";
    ctx.fillRect(0,0,canvas.clientWidth,canvas.clientHeight);

    const w = Math.max(1, Math.round(canvas.clientWidth  / scale));
    const h = Math.max(1, Math.round(canvas.clientHeight / scale));
    const x = Math.max(0, Math.round(originX));
    const y = Math.max(0, Math.round(originY));

    const url = `/tile?x=${x}&y=${y}&w=${w}&h=${h}&out_w=${canvas.clientWidth}&out_h=${canvas.clientHeight}&t=${Date.now()}`;
    try{
      const r = await fetch(url, {cache:"no-cache"});
      if(!r.ok){ info.textContent = "no tile"; return; }
      const blob = await r.blob();
      const bmp = await createImageBitmap(blob);
      ctx.drawImage(bmp, 0, 0, canvas.clientWidth, canvas.clientHeight);
      bmp.close();
      info.textContent = `x:${x} y:${y} w:${w} h:${h} scale:${scale.toFixed(2)}`;
    }catch(e){
      info.textContent = "fetch error";
    }
  }
  function requestDraw(){
    if(!redrawScheduled){
      redrawScheduled = true;
      window.requestAnimationFrame(draw);
    }
  }
  // ilk cizim
  requestDraw();
})();
</script>
</body>
</html>
    """
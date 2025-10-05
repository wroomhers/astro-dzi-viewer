#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hq_viewer.py
TIFF/IMG -> Deep Zoom (DZI) + OpenSeadragon viewer
+ Dinamik karşılaştırma sayfası (1 veya 2 görselde çalışır)
+ Overlay'de katmanları bağımsız pan/zoom/scale (kilit kapalıyken)
+ Yan yana modda senkronizasyon aç/kapat
+ viewer.html içinde annotation (bounding box + yıldız bilgileri) ekleme/görüntüleme/kaydetme
   - Çizim modunda pan/zoom jestleri devre dışı (event’ler çalışır, kutu çizilir)
"""

import argparse
import math
import os
import sys
import json
import shutil
import subprocess
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote
from threading import Thread

# ------------------------
# HTML: Tekli viewer (+Annotations)
# ------------------------
def write_viewer_html(out_dir, dzi_base_name):
    html_tpl = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>DZI Viewer + Annotations</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { --bg:#0f0f10; --fg:#e7e7ea; --muted:#9aa0a6; --accent:#3da9ff; --danger:#ff5b5b; }
    html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
    #openseadragon{position:absolute;inset:64px 0 0 0;background:#111}
    .toolbar{
      position:fixed;top:0;left:0;right:0;height:64px;display:flex;gap:.5rem;align-items:center;
      padding:.5rem .75rem;background:#000c;backdrop-filter:saturate(120%) blur(6px);border-bottom:1px solid #222;z-index:50
    }
    .btn{padding:.45rem .7rem;border:1px solid #333;background:#1a1a1a;color:var(--fg);border-radius:.5rem;cursor:pointer}
    .btn.primary{outline:2px solid var(--accent)}
    .btn.danger{border-color:#442222;background:#1a0f0f}
    .btn:disabled{opacity:.5;cursor:not-allowed}
    .chip{display:inline-flex;align-items:center;gap:.4rem;border:1px solid #333;background:#171717;padding:.35rem .6rem;border-radius:.5rem}
    .form{
      position:fixed;right:20px;top:72px;width:360px;background:#0f141a;border:1px solid #223041;border-radius:.75rem;box-shadow:0 10px 30px rgba(0,0,0,.35);z-index:60;display:none
    }
    .form header{padding:.6rem .75rem;border-bottom:1px solid #243043;font-weight:600}
    .form .body{padding:.6rem .75rem;display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
    .form .body label{font-size:.85rem;color:var(--muted)}
    .form .body input,.form .body textarea,.form .body select{
      width:100%;border:1px solid #2b2f36;background:#0b0e12;color:var(--fg);border-radius:.5rem;padding:.45rem .55rem
    }
    .form .body textarea{grid-column:1/-1;min-height:84px;resize:vertical}
    .form footer{display:flex;gap:.5rem;justify-content:flex-end;padding:.6rem .75rem;border-top:1px solid #243043}
    .hint { position:fixed; bottom:.5rem; left:.75rem; font-size:.85rem; opacity:.75; background:#0008; padding:.35rem .55rem; border-radius:.4rem; z-index:70}
    /* Box overlay görünümleri */
    .anno-box{
      position:absolute;border:2px solid rgba(61,169,255,.95);background:rgba(61,169,255,.12);box-shadow:0 0 0 1px rgba(0,0,0,.35) inset;
      pointer-events:auto;
    }
    .anno-box.active{border-color:#ffd166;background:rgba(255,209,102,.15)}
    .ghost{border-style:dashed;opacity:.8}
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/openseadragon.min.js" crossorigin="anonymous"></script>
</head>
<body>
  <div class="toolbar">
    <button id="btnDraw" class="btn">Çizim Modu</button>
    <button id="btnCancel" class="btn" disabled>İptal</button>
    <span class="chip"><input type="checkbox" id="chkShow" checked/> Kutuları göster</span>
    <span class="chip"><input type="checkbox" id="chkLabels" checked/> Etiketleri göster</span>
    <span style="margin-left:auto;color:#9aa0a6">Görüntü: <b id="imgName">__DZI_BASE__</b></span>
  </div>

  <div id="openseadragon"></div>

  <div class="form" id="form">
    <header>Yıldız Bilgileri</header>
    <div class="body">
      <div style="grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:.5rem">
        <div><label>Ad/Katalog</label><input id="f_name" placeholder="Örn: Betelgeuse / HIP..." /></div>
        <div><label>Tür</label>
          <select id="f_type">
            <option value="Star">Star</option>
            <option value="Galaxy">Galaxy</option>
            <option value="Nebula">Nebula</option>
            <option value="Cluster">Cluster</option>
            <option value="Other">Other</option>
          </select>
        </div>
      </div>
      <div><label>Görünür kadir (mag)</label><input id="f_mag" type="number" step="0.01" placeholder="Örn: 0.42" /></div>
      <div><label>Renk/B-V</label><input id="f_bv" placeholder="opsiyonel" /></div>
      <label style="grid-column:1/-1">Notlar</label>
      <textarea id="f_notes" placeholder="Kaynak, tarih, gözlem notu vb."></textarea>
    </div>
    <footer>
      <button class="btn danger" id="btnDelete">Sil</button>
      <button class="btn" id="btnClose">Kapat</button>
      <button class="btn primary" id="btnSave">Kaydet</button>
    </footer>
  </div>

  <div class="hint">
    Çizim Modu: basılı tutup sürükle. Bırakınca form açılır. Mevcut kutuya tıklayınca düzenlersin. Kaydet/Sil sonrası otomatik yazılır.
  </div>

  <script>
    // ------- Başlangıç değişkenleri -------
    const DZI_BASE = "__DZI_BASE__";
    const DZI_FILE = "__DZI_BASE__.dzi";
    const API_GET  = "/api/annotations/" + encodeURIComponent(DZI_BASE);
    const API_POST = API_GET;
    document.getElementById('imgName').textContent = DZI_BASE;

    // ------- OSD init -------
    const viewer = OpenSeadragon({
      id: "openseadragon",
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
      showNavigator: true,
      animationTime: 0.8,
      blendTime: 0.2,
      maxZoomPixelRatio: 15.5,
      visibilityRatio: 1.0,
      constrainDuringPan: true,
      minZoomLevel: 0.5
    });
    viewer.open(DZI_FILE);

    // ------- Annotation state -------
    let annotations = { image: DZI_BASE, boxes: [] }; // [{id,x,y,w,h,name,type,mag,bv,notes,created}]
    let drawMode = false;
    let drawing = null; // {start:Point(img), rect, ghostEl}
    let activeId = null;
    const btnDraw = document.getElementById('btnDraw');
    const btnCancel = document.getElementById('btnCancel');

    // Form refs
    const form = document.getElementById('form');
    const f_name = document.getElementById('f_name');
    const f_type = document.getElementById('f_type');
    const f_mag  = document.getElementById('f_mag');
    const f_bv   = document.getElementById('f_bv');
    const f_notes= document.getElementById('f_notes');
    const btnSave = document.getElementById('btnSave');
    const btnDelete = document.getElementById('btnDelete');
    const btnClose  = document.getElementById('btnClose');

    // ------- Yardımcılar -------
    function uuid(){ return (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)) }
    function imgPtFromEvent(e){
      const webPt = e.position; // web pixels
      const vpPt = viewer.viewport.pointFromPixel(webPt, true);
      const imgPt = viewer.viewport.viewportToImageCoordinates(vpPt);
      return imgPt;
    }
    function rectToBounds(r){
      const topLeft = viewer.viewport.imageToViewportCoordinates(new OpenSeadragon.Point(r.x, r.y));
      const botRight= viewer.viewport.imageToViewportCoordinates(new OpenSeadragon.Point(r.x + r.w, r.y + r.h));
      return new OpenSeadragon.Rect(topLeft.x, topLeft.y, botRight.x - topLeft.x, botRight.y - topLeft.y);
    }
    function boundsToCss(bounds){
      const topLeftPx = viewer.viewport.pixelFromPoint(new OpenSeadragon.Point(bounds.x, bounds.y), true);
      const botRightPx= viewer.viewport.pixelFromPoint(new OpenSeadragon.Point(bounds.x + bounds.width, bounds.y + bounds.height), true);
      return {
        left: topLeftPx.x, top: topLeftPx.y,
        width: botRightPx.x - topLeftPx.x, height: botRightPx.y - topLeftPx.y
      };
    }

    // Ekrana kutu çizimi (DOM overlay)
    const overlayLayer = document.createElement('div');
    overlayLayer.style.position = 'absolute';
    overlayLayer.style.inset = '0';
    overlayLayer.style.pointerEvents = 'none'; // çizimde engel olmasın
    viewer.addHandler('open', () => {
      viewer.canvas.parentElement.appendChild(overlayLayer);
      refreshAllOverlays();
    });

    function makeBoxEl(id, ghost=false){
      const el = document.createElement('div');
      el.className = 'anno-box' + (ghost ? ' ghost' : '');
      el.dataset.id = id || '';
      overlayLayer.appendChild(el);
      return el;
    }
    function placeElFromRect(el, r){
      const b = rectToBounds(r);
      const css = boundsToCss(b);
      el.style.left = css.left + 'px';
      el.style.top  = css.top  + 'px';
      el.style.width= css.width+ 'px';
      el.style.height=css.height+'px';
      el.style.display = (document.getElementById('chkShow').checked ? 'block' : 'none');
    }
    function refreshAllOverlays(){
      overlayLayer.querySelectorAll('.anno-box:not(.ghost)').forEach(n => n.remove());
      (annotations.boxes || []).forEach(r => {
        const el = makeBoxEl(r.id, false);
        placeElFromRect(el, r);
        if (r.id === activeId) el.classList.add('active');
        if (document.getElementById('chkLabels').checked) {
          const lbl = document.createElement('div');
          lbl.style.position='absolute'; lbl.style.left='0'; lbl.style.top='-1.35rem';
          lbl.style.fontSize='12px'; lbl.style.padding='2px 6px';
          lbl.style.background='rgba(0,0,0,.65)'; lbl.style.border='1px solid #223'; lbl.style.borderRadius='4px';
          lbl.style.whiteSpace='nowrap';
          lbl.textContent = (r.name || 'N/A') + (r.mag ? ` (mag ${r.mag})` : '');
          el.appendChild(lbl);
        }
        // Kutuya tıklayınca düzenleme
        el.style.pointerEvents = 'auto';
        el.addEventListener('click', (ev) => { ev.stopPropagation(); openEdit(r.id); }, {passive:true});
      });
    }
    viewer.addHandler('viewport-change', () => {
      overlayLayer.querySelectorAll('.anno-box').forEach(el => {
        if (el.classList.contains('ghost')) {
          if (drawing && drawing.rect) placeElFromRect(el, drawing.rect);
        } else {
          const r = annotations.boxes.find(b => b.id === el.dataset.id);
          if (r) placeElFromRect(el, r);
        }
      });
    });

    // ------- Çizim modunda nav jestlerini devre dışı bırak -------
    let prevMouseGestures = null;
    let prevTouchGestures = null;

    function setDrawMode(on){
      drawMode = on;
      btnDraw.classList.toggle('primary', on);
      btnCancel.disabled = !on;

      if (on) {
        // Önceki ayarları sakla
        prevMouseGestures = { ...viewer.gestureSettingsMouse };
        prevTouchGestures = { ...viewer.gestureSettingsTouch };

        // Navigasyonu tamamen kapatma; event’ler gelmeye devam etsin
        // Sadece pan/zoom jestlerini kapat
        Object.assign(viewer.gestureSettingsMouse, {
          clickToZoom: false,
          dblClickToZoom: false,
          dragToPan: false,
          scrollToZoom: false,
          pinchToZoom: false,
          flickEnabled: false
        });
        Object.assign(viewer.gestureSettingsTouch, {
          pinchToZoom: false,
          flickEnabled: false,
          dragToPan: false
        });
      } else {
        // Eski ayarları geri yükle
        if (prevMouseGestures) Object.assign(viewer.gestureSettingsMouse, prevMouseGestures);
        if (prevTouchGestures) Object.assign(viewer.gestureSettingsTouch, prevTouchGestures);
        prevMouseGestures = prevTouchGestures = null;

        if (drawing && drawing.ghostEl) drawing.ghostEl.remove();
        drawing = null;
      }
    }
    btnDraw.addEventListener('click', () => setDrawMode(!drawMode));
    btnCancel.addEventListener('click', () => setDrawMode(false));
    document.getElementById('chkShow').addEventListener('change', refreshAllOverlays);
    document.getElementById('chkLabels').addEventListener('change', refreshAllOverlays);

    // ------- Çizim akışı (press/drag/release) + default action iptali -------
    viewer.addHandler('canvas-press', (e) => {
      if (!drawMode) return;
      e.preventDefaultAction = true; // pan başlangıcını engelle
      const imgPt = imgPtFromEvent(e);
      drawing = { start: imgPt, rect: {x: imgPt.x, y: imgPt.y, w: 1, h: 1}, ghostEl: makeBoxEl('', true) };
    });
    viewer.addHandler('canvas-drag', (e) => {
      if (!drawMode || !drawing) return;
      e.preventDefaultAction = true; // sürüklemede pan'ı engelle
      const cur = imgPtFromEvent(e);
      const x0 = Math.min(drawing.start.x, cur.x);
      const y0 = Math.min(drawing.start.y, cur.y);
      const w  = Math.abs(cur.x - drawing.start.x);
      const h  = Math.abs(cur.y - drawing.start.y);
      drawing.rect = {x:x0, y:y0, w:w, h:h};
      placeElFromRect(drawing.ghostEl, drawing.rect);
    });
    viewer.addHandler('canvas-release', (e) => {
      if (!drawMode || !drawing) return;
      e.preventDefaultAction = true; // bırakmada da güvene al
      if (drawing.rect.w < 5 || drawing.rect.h < 5) {
        drawing.ghostEl.remove(); drawing = null; return;
      }
      const id = uuid();
      const r = Object.assign({id, name:'', type:'Star', mag:'', bv:'', notes:'', created: new Date().toISOString()}, drawing.rect);
      drawing.ghostEl.remove(); drawing = null;
      annotations.boxes.push(r);
      activeId = id;
      refreshAllOverlays();
      openEdit(id);
      setDrawMode(false);
    });

    // Çizim modunda scroll zoom ve click/double-click zoom'u da engelle
    viewer.addHandler('canvas-scroll', (e) => { if (drawMode) { e.preventDefaultAction = true; } });
    viewer.addHandler('canvas-click', (e) => { if (drawMode) { e.preventDefaultAction = true; } });
    viewer.addHandler('canvas-double-click', (e) => { if (drawMode) { e.preventDefaultAction = true; } });

    // ------- Liste (kaldırıldı) -------
    function refreshList(){
      // Sidebar kaldırıldığı için boş fonksiyon
    }

    // ------- Form -------
    function openEdit(id){
      activeId = id;
      const r = (annotations.boxes || []).find(x=>x.id===id);
      if (!r) return;
      overlayLayer.querySelectorAll('.anno-box').forEach(el => {
        if (!el.classList.contains('ghost')) el.classList.toggle('active', el.dataset.id === id);
      });
      f_name.value = r.name || '';
      f_type.value = r.type || 'Star';
      f_mag.value  = r.mag || '';
      f_bv.value   = r.bv || '';
      f_notes.value= r.notes || '';
      form.style.display = 'block';
    }
    btnClose.addEventListener('click', ()=> form.style.display='none');
    btnSave.addEventListener('click', async ()=>{
      const r = (annotations.boxes || []).find(x=>x.id===activeId);
      if (!r) return;
      r.name = f_name.value.trim();
      r.type = f_type.value;
      r.mag  = f_mag.value;
      r.bv   = f_bv.value.trim();
      r.notes= f_notes.value.trim();
      await saveAnnotations();
      form.style.display = 'none';
      refreshAllOverlays();
    });
    btnDelete.addEventListener('click', async ()=>{
      if (!activeId) return;
      annotations.boxes = (annotations.boxes || []).filter(x=>x.id!==activeId);
      activeId = null;
      await saveAnnotations();
      form.style.display = 'none';
      refreshAllOverlays();
    });

    // ------- Sunucu ile kaydet/yükle -------
    async function loadAnnotations(){
      try{
        const res = await fetch(API_GET, {cache:'no-cache'});
        if (!res.ok) throw new Error('HTTP '+res.status);
        const data = await res.json();
        if (data && data.image === DZI_BASE && Array.isArray(data.boxes)) {
          annotations = data;
        } else {
          annotations = {image:DZI_BASE, boxes:[]};
        }
      }catch(e){
        annotations = {image:DZI_BASE, boxes:[]};
      }
      refreshAllOverlays();
    }
    async function saveAnnotations(){
      const res = await fetch(API_POST, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(annotations)
      });
      if (!res.ok) alert('Kaydetme hatası: HTTP '+res.status);
    }

    // İlk yükle
    loadAnnotations();
  </script>
</body>
</html>
"""
    html = html_tpl.replace("__DZI_BASE__", dzi_base_name)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "viewer.html"), "w", encoding="utf-8") as f:
        f.write(html)

# ------------------------
# HTML: Dinamik compare (1 veya 2 görüntü) — değişmedi (annotations yok)
# ------------------------
def write_compare_html(out_dir):
    html = """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <title>DZI Compare (Dinamik)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { --bg:#111; --fg:#ddd; --accent:#3da9ff; }
    html,body { margin:0; height:100%; background:var(--bg); color:var(--fg); font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
    .toolbar {
      position:fixed; top:0; left:0; right:0; z-index:9999;
      display:flex; gap:.75rem; align-items:center; flex-wrap:wrap;
      padding:.6rem .8rem; background:#000c; backdrop-filter:saturate(120%) blur(6px); border-bottom:1px solid #222;
    }
    .toolbar label { font-size:.9rem; opacity:.95; }
    .toolbar input[type="range"] { width:190px; vertical-align:middle; }
    .toolbar select { background:#1a1a1a; color:var(--fg); border:1px solid #333; border-radius:.5rem; padding:.3rem .5rem; }
    .toolbar .modebtn, .toolbar .chip {
      padding:.35rem .6rem; border:1px solid #333; background:#1a1a1a; color:var(--fg); border-radius:.5rem; cursor:pointer;
    }
    .toolbar .modebtn.active { outline:2px solid var(--accent); }
    .viewer-wrap { position:absolute; top:78px; left:0; right:0; bottom:0; }
    #overlayContainer, #splitContainer { width:100%; height:100%; display:none; }
    #overlayContainer { position:relative; }
    #osdOverlay { position:absolute; inset:0; background:#111; }
    #splitContainer { display:flex; gap:2px; }
    .pane { flex:1 1 50%; position:relative; min-width:0; }
    .pane > div { position:absolute; inset:0; }
    .hint { position:fixed; bottom:.5rem; left:.75rem; font-size:.85rem; opacity:.75; background:#0008; padding:.35rem .55rem; border-radius:.4rem; }
    .sep { width:1px; height:22px; background:#333; margin:0 .5rem; }
  </style>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/openseadragon.min.js" crossorigin="anonymous"></script>
</head>
<body>
  <div class="toolbar">
    <button id="btnOverlay" class="modebtn active" title="Üst üste karşılaştır">Overlay</button>
    <button id="btnSplit" class="modebtn" title="Yan yana karşılaştır">Yan yana</button>

    <div class="sep"></div>

    <label>Image A:
      <select id="selA"></select>
    </label>
    <label>Image B:
      <select id="selB"></select>
    </label>

    <div class="sep"></div>

    <label>Aktif katman:
      <select id="activeLayer">
        <option value="top">Üst</option>
        <option value="bottom" selected>Alt</option>
      </select>
    </label>

    <label>Opaklık (üst):
      <input id="alphaTop" type="range" min="0" max="1" step="0.01" value="0.5">
      <span id="alphaTopVal">0.50</span>
    </label>

    <label>Ölçek (üst):
      <input id="scaleTop" type="range" min="0.25" max="4" step="0.01" value="1.00">
      <span id="scaleTopVal">1.00×</span>
    </label>

    <label>Ölçek (alt):
      <input id="scaleBottom" type="range" min="0.25" max="4" step="0.01" value="1.00">
      <span id="scaleBottomVal">1.00×</span>
    </label>

    <label class="chip" style="display:flex; align-items:center; gap:.4rem;">
      <input type="checkbox" id="lockLayers">
      Katman kilidi (pan/zoom beraber)
    </label>

    <button id="btnSwap" class="modebtn" title="Katmanları değiştir">Katman Değiştir</button>

    <div class="sep"></div>

    <label>
      <input type="checkbox" id="syncChk" checked> Senkron kaydır/zoom (yan yana)
    </label>
  </div>

  <div class="viewer-wrap">
    <div id="overlayContainer" style="display:block;">
      <div id="osdOverlay"></div>
    </div>
    <div id="splitContainer">
      <div class="pane"><div id="osdLeft"></div></div>
      <div class="pane"><div id="osdRight"></div></div>
    </div>
  </div>

  <div class="hint">
    Kaynakları üstten seç. Overlay: kilit kapalıyken sürükleme <b>Aktif katman</b>ı hareket ettirir. Kısayol: <b>Alt=Üst</b>, <b>Shift=Alt</b>.
    Ölçek: Alt+tekerlek → üst, Shift+tekerlek → alt, aksi halde aktif katman. Yan yana: “Senkron”u kapatınca bağımsız.
  </div>

  <script>
    const selA = document.getElementById('selA');
    const selB = document.getElementById('selB');
    const activeLayerSel = document.getElementById('activeLayer');
    const alphaTopEl = document.getElementById('alphaTop');
    const alphaTopVal = document.getElementById('alphaTopVal');
    const scaleTopEl = document.getElementById('scaleTop');
    const scaleTopVal = document.getElementById('scaleTopVal');
    const scaleBottomEl = document.getElementById('scaleBottom');
    const scaleBottomVal = document.getElementById('scaleBottomVal');
    const btnOverlay = document.getElementById('btnOverlay');
    const btnSplit = document.getElementById('btnSplit');
    const btnSwap = document.getElementById('btnSwap');
    const syncChk = document.getElementById('syncChk');
    const lockLayers = document.getElementById('lockLayers');

    let list = [];
    let topIsA = true;
    let topScale = 1.0, bottomScale = 1.0;

    function basename(p){
      const s = p.replace(/\\\\/g,'/').split('/').pop();
      return s.replace(/\\.dzi$/i,'');
    }

    async function loadList() {
      try {
        const res = await fetch('meta.json', {cache:'no-cache'});
        const meta = await res.json();
        const items = (meta.images || []).map(it => {
          const base = basename(it.src || it.dzi || '');
          return { base, dzi: base + '.dzi' };
        });
        list = items;
      } catch(e) {
        list = [];
      }
      selA.innerHTML = '';
      selB.innerHTML = '';
      if (list.length === 0) {
        const opt = new Option('Bulunamadı', '', true, true);
        selA.add(opt.cloneNode(true));
        selB.add(opt);
      } else if (list.length === 1) {
        selA.add(new Option(list[0].base, list[0].base, true, true));
        selB.add(new Option('— Yok —', '', true, true));
      } else {
        list.forEach((it, i) => {
          selA.add(new Option(it.base, it.base, i===0, i===0));
          selB.add(new Option(it.base, it.base, i===1, i===1));
        });
      }
      updateControlStates();
      refreshAll();
    }

    function findDzi(base){ const it = list.find(x=>x.base===base); return it ? it.dzi : null; }
    function currentSources(){
      const a = findDzi(selA.value);
      const b = findDzi(selB.value);
      return {a,b};
    }

    function updateControlStates() {
      const hasTop = !!findDzi(selB.value);
      alphaTopEl.disabled = !hasTop;
      scaleTopEl.disabled = !hasTop;
      btnSwap.disabled = !hasTop;
      lockLayers.disabled = !hasTop;

      activeLayerSel.value = hasTop ? activeLayerSel.value : 'bottom';
      activeLayerSel.disabled = !hasTop;
    }
    selA.addEventListener('change', () => { updateControlStates(); });

    let overlayViewer = OpenSeadragon({
      id: "osdOverlay",
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
      showNavigator: true,
      animationTime: 0.8,
      blendTime: 0.2,
      maxZoomPixelRatio: 15.5,
      visibilityRatio: 1.0,
      constrainDuringPan: true,
      minZoomLevel: 0.5
    });
    let itemBottom = null, itemTop = null;
    let topRefWidth = null, bottomRefWidth = null;

    function loadOverlay(aDzi, bDzi) {
      overlayViewer.world.removeAll();
      itemBottom = itemTop = null;
      topRefWidth = bottomRefWidth = null;
      if(!aDzi && !bDzi) return;

      let bottomSrc = null, topSrc = null;
      if (aDzi && bDzi) {
        bottomSrc = topIsA ? bDzi : aDzi;
        topSrc    = topIsA ? aDzi : bDzi;
      } else {
        bottomSrc = aDzi || bDzi;
        topSrc = null;
      }

      overlayViewer.addTiledImage({
        tileSource: bottomSrc,
        success: function(ev) {
          itemBottom = ev.item;
          const ref = itemBottom.getBounds();
          bottomRefWidth = ref.width;

          if (topSrc) {
            overlayViewer.addTiledImage({
              tileSource: topSrc,
              success: function(ev2) {
                itemTop = ev2.item;
                itemTop.setPosition(ref.getTopLeft(), true);
                itemTop.setWidth(ref.width, true);
                topRefWidth = ref.width;
                itemTop.setOpacity(parseFloat(alphaTopEl.value));
                applyScale(itemTop, topRefWidth, topScale);
                applyScale(itemBottom, bottomRefWidth, bottomScale);
              }
            });
          }
        }
      });
    }

    function applyScale(item, refWidth, scale) {
      if (!item || refWidth == null) return;
      const w = refWidth * scale;
      const center = item.getBounds().getCenter();
      item.setWidth(w, true);
      const b = item.getBounds();
      const shift = center.minus(b.getCenter());
      item.setPosition(b.getTopLeft().plus(shift), true);
    }

    function pickLayerFromEvent(e) {
      if (e && e.originalEvent && e.originalEvent.altKey) return 'top';
      if (e && e.originalEvent && e.originalEvent.shiftKey) return 'bottom';
      return activeLayerSel.value;
    }

    overlayViewer.addHandler('canvas-drag', function(e) {
      if (document.getElementById('lockLayers').checked) return;
      e.preventDefaultAction = true;
      const target = (pickLayerFromEvent(e) === 'top') ? itemTop : itemBottom;
      if (!target) return;
      const deltaVp = overlayViewer.viewport.deltaPointsFromPixels(e.delta);
      const b = target.getBounds();
      target.setPosition(b.getTopLeft().minus(deltaVp), true);
    });

    overlayViewer.addHandler('canvas-scroll', function(e) {
      if (document.getElementById('lockLayers').checked) return;
      e.preventDefaultAction = true;
      const which = pickLayerFromEvent(e);
      const factor = (e.scroll > 0) ? 0.97 : 1.03;
      if (which === 'top' && itemTop) {
        topScale = Math.max(0.25, Math.min(4, topScale * factor));
        document.getElementById('scaleTop').value = topScale.toFixed(2);
        document.getElementById('scaleTopVal').textContent = topScale.toFixed(2) + "×";
        applyScale(itemTop, topRefWidth, topScale);
      } else if (which === 'bottom' && itemBottom) {
        bottomScale = Math.max(0.25, Math.min(4, bottomScale * factor));
        document.getElementById('scaleBottom').value = bottomScale.toFixed(2);
        document.getElementById('scaleBottomVal').textContent = bottomScale.toFixed(2) + "×";
        applyScale(itemBottom, bottomRefWidth, bottomScale);
      }
    });

    document.getElementById('alphaTop').addEventListener('input', () => {
      document.getElementById('alphaTopVal').textContent = parseFloat(document.getElementById('alphaTop').value).toFixed(2);
      if (itemTop) itemTop.setOpacity(parseFloat(document.getElementById('alphaTop').value));
    });
    document.getElementById('scaleTop').addEventListener('input', () => {
      topScale = parseFloat(document.getElementById('scaleTop').value);
      document.getElementById('scaleTopVal').textContent = topScale.toFixed(2) + "×";
      applyScale(itemTop, topRefWidth, topScale);
    });
    document.getElementById('scaleBottom').addEventListener('input', () => {
      bottomScale = parseFloat(document.getElementById('scaleBottom').value);
      document.getElementById('scaleBottomVal').textContent = bottomScale.toFixed(2) + "×";
      applyScale(itemBottom, bottomRefWidth, bottomScale);
    });
    btnSwap.addEventListener('click', () => { topIsA = !topIsA; refreshOverlay(); });

    let leftViewer = OpenSeadragon({
      id: "osdLeft",
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
      showNavigator: true,
      animationTime: 0.8,
      blendTime: 0.2,
      maxZoomPixelRatio: 15.5,
      visibilityRatio: 1.0,
      constrainDuringPan: true,
      minZoomLevel: 0.5
    });
    let rightViewer = OpenSeadragon({
      id: "osdRight",
      prefixUrl: "https://cdnjs.cloudflare.com/ajax/libs/openseadragon/4.1.1/images/",
      showNavigator: true,
      animationTime: 0.8,
      blendTime: 0.2,
      maxZoomPixelRatio: 15.5,
      visibilityRatio: 1.0,
      constrainDuringPan: true,
      minZoomLevel: 0.5
    });

    function loadSplit(aDzi, bDzi) {
      if (aDzi) leftViewer.open(aDzi); else leftViewer.close();
      if (bDzi) rightViewer.open(bDzi); else rightViewer.close();
    }

    let syncing = false;
    function syncView(from, to) {
      if (!syncChk.checked) return;
      if (syncing) return;
      try {
        syncing = true;
        const center = from.viewport.getCenter();
        const zoom = from.viewport.getZoom();
        to.viewport.zoomTo(zoom);
        to.viewport.panTo(center);
      } finally {
        syncing = false;
      }
    }
    leftViewer.addHandler('viewport-change', () => syncView(leftViewer, rightViewer));
    rightViewer.addHandler('viewport-change', () => syncView(rightViewer, leftViewer));

    function setMode(overlay) {
      const ov = document.getElementById('overlayContainer');
      const sp = document.getElementById('splitContainer');
      if (overlay) {
        ov.style.display = 'block';
        sp.style.display = 'none';
        btnOverlay.classList.add('active');
        btnSplit.classList.remove('active');
        refreshOverlay();
      } else {
        ov.style.display = 'none';
        sp.style.display = 'flex';
        btnOverlay.classList.remove('active');
        btnSplit.classList.add('active');
        refreshSplit();
      }
    }
    btnOverlay.addEventListener('click', () => setMode(true));
    btnSplit.addEventListener('click', () => setMode(false));

    selA.addEventListener('change', ()=>{ updateControlStates(); refreshAll(); });
    selB.addEventListener('change', ()=>{ updateControlStates(); refreshAll(); });

    function refreshOverlay(){ const {a,b}=currentSources(); loadOverlay(a,b); }
    function refreshSplit(){ const {a,b}=currentSources(); loadSplit(a,b); }
    function refreshAll(){ refreshOverlay(); refreshSplit(); }

    loadList();

    window.addEventListener('resize', () => {
      overlayViewer.viewport && overlayViewer.viewport.goHome(true);
      leftViewer.viewport && leftViewer.viewport.goHome(true);
      rightViewer.viewport && rightViewer.viewport.goHome(true);
    });
  </script>
</body>
</html>
"""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "compare.html"), "w", encoding="utf-8") as f:
        f.write(html)

# ------------------------
# pyvips kontrolleri
# ------------------------
def has_python_pyvips():
    try:
        import pyvips  # noqa
        return True
    except Exception:
        return False

def has_cli_vips():
    return shutil.which("vips") is not None

# ------------------------
# DZI üretimi (pyvips -> vips CLI -> Pillow)
# ------------------------
def dzi_with_pyvips_python(src_path, out_dir, base_name, tile_size, overlap, fmt):
    import pyvips
    suffix = ".jpg[Q=90]" if fmt.lower().startswith("j") else ".png"
    dst = os.path.join(out_dir, base_name)
    os.makedirs(out_dir, exist_ok=True)
    image = pyvips.Image.new_from_file(src_path, access="sequential")
    image.dzsave(dst, tile_size=tile_size, overlap=overlap, suffix=suffix, layout="dz")
    return f"{base_name}.dzi", f"{base_name}_files"

def _cleanup_dz_destination(out_dir, base_name):
    dzi = os.path.join(out_dir, f"{base_name}.dzi")
    files = os.path.join(out_dir, f"{base_name}_files")
    if os.path.isfile(dzi):
        os.remove(dzi)
    if os.path.isdir(files):
        shutil.rmtree(files)

def dzi_with_vips_cli(src_path, out_dir, base_name, tile_size, overlap, fmt, overwrite=False):
    os.makedirs(out_dir, exist_ok=True)
    if overwrite:
        _cleanup_dz_destination(out_dir, base_name)
    dst_prefix = os.path.join(out_dir, base_name)
    suffix = ".jpg[Q=90]" if fmt.lower().startswith("j") else ".png"
    cmd = [
        "vips", "dzsave", src_path, dst_prefix,
        f"--tile-size={tile_size}",
        f"--overlap={overlap}",
        f"--suffix={suffix}",
        "--layout=dz"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"vips dzsave failed ({proc.returncode})")
    return f"{base_name}.dzi", f"{base_name}_files"

def dzi_with_pillow(src_path, out_dir, base_name, tile_size, overlap, fmt, unsafe_big=False):
    from PIL import Image, ImageOps, Image as PILImage
    if unsafe_big:
        PILImage.MAX_IMAGE_PIXELS = None

    def sanitize_to_rgb(img):
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            img8 = ImageOps.autocontrast(img.convert("I")).convert("L")
            return img8.convert("RGB")
        elif img.mode in ("P",):
            return img.convert("RGB")
        elif img.mode in ("L",):
            return img.convert("RGB")
        elif img.mode in ("RGBA", "RGB"):
            return img
        else:
            return img.convert("RGB")

    def build_dzi_xml(width, height, tile, fmt_, overlap_=0):
        ext = "jpg" if fmt_.lower().startswith("j") else "png"
        return """<?xml version="1.0" encoding="UTF-8"?>
<Image TileSize="{tile}" Overlap="{overlap_}" Format="{ext}" xmlns="http://schemas.microsoft.com/deepzoom/2008">
  <Size Width="{width}" Height="{height}"/>
</Image>
""".format(tile=tile, overlap_=overlap_, ext=ext, width=width, height=height)

    def compute_max_level(w, h):
        return int(math.ceil(math.log(max(w, h), 2)))

    def dims_at_level(w, h, max_level, level):
        scale = 2 ** (level - max_level)
        nw = max(1, int(math.ceil(w * scale)))
        nh = max(1, int(math.ceil(h * scale)))
        return nw, nh

    def save_tile(img, path, fmt_):
        params = {}
        if fmt_.lower().startswith("j"):
            fmt2 = "JPEG"
            params["quality"] = 90
            params["optimize"] = True
            params["progressive"] = True
        else:
            fmt2 = "PNG"
        img.save(path, fmt2, **params)

    os.makedirs(out_dir, exist_ok=True)
    base = base_name
    files_dir = os.path.join(out_dir, f"{base}_files")
    os.makedirs(files_dir, exist_ok=True)

    from PIL import Image as _I
    im = _I.open(src_path)
    try:
        im.seek(0)
    except Exception:
        pass
    im = sanitize_to_rgb(im)
    W, H = im.size

    # DZI XML’i yaz
    dzi_xml = build_dzi_xml(W, H, tile_size, fmt, overlap)
    with open(os.path.join(out_dir, f"{base}.dzi"), "w", encoding="utf-8") as f:
        f.write(dzi_xml)

    max_level = compute_max_level(W, H)
    ext = "jpg" if fmt.lower().startswith("j") else "png"

    for level in range(0, max_level + 1):
        lv_w, lv_h = dims_at_level(W, H, max_level, level)
        lvl_img = im.resize((lv_w, lv_h), _I.Resampling.LANCZOS)

        cols = (lv_w + tile_size - 1) // tile_size
        rows = (lv_h + tile_size - 1) // tile_size

        level_dir = os.path.join(files_dir, str(level))
        os.makedirs(level_dir, exist_ok=True)

        for row in range(rows):
          y0 = row * tile_size
          y1 = min(y0 + tile_size, lv_h)
          for col in range(cols):
            x0 = col * tile_size
            x1 = min(x0 + tile_size, lv_w)
            tile = lvl_img.crop((x0, y0, x1, y1))
            out_path = os.path.join(level_dir, f"{col}_{row}.{ext}")
            save_tile(tile, out_path, fmt)

    return f"{base}.dzi", f"{base}_files"

# ------------------------
# Basit HTTP Sunucu (+ /api/annotations/*)
# ------------------------
def serve_directory(root_dir: str, port: int = 8000):
    ann_root = os.path.join(root_dir, "annotations")
    os.makedirs(ann_root, exist_ok=True)

    class CwdHandler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            rel = path.lstrip("/")
            return os.path.join(root_dir, rel)

        def _send_json(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/annotations/"):
                base = unquote(parsed.path.split("/api/annotations/")[-1]).strip("/")
                if not base:
                    return self._send_json({"error":"missing base"}, 400)
                fp = os.path.join(ann_root, f"{base}.json")
                if os.path.isfile(fp):
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        data = {"image": base, "boxes": []}
                else:
                    data = {"image": base, "boxes": []}
                return self._send_json(data, 200)
            return super().do_GET()

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/annotations/"):
                base = unquote(parsed.path.split("/api/annotations/")[-1]).strip("/")
                if not base:
                    return self._send_json({"error":"missing base"}, 400)
                length = int(self.headers.get("Content-Length", "0") or "0")
                try:
                    raw = self.rfile.read(length)
                    data = json.loads(raw.decode("utf-8"))
                    if not isinstance(data, dict) or data.get("image") != base or "boxes" not in data:
                        return self._send_json({"error":"invalid payload"}, 400)
                    fp = os.path.join(ann_root, f"{base}.json")
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    return self._send_json({"ok": True}, 200)
                except Exception as e:
                    return self._send_json({"error": str(e)}, 500)
            self.send_error(404)

    httpd = HTTPServer(("0.0.0.0", port), CwdHandler)
    print(f"[i] Sunucu: http://localhost:{port}/viewer.html  (veya compare.html)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

# ------------------------
# Ana
# ------------------------
def main():
    p = argparse.ArgumentParser(description="TIFF -> DZI tile + OpenSeadragon viewer (+ dinamik karşılaştırma + viewer annotations)")
    p.add_argument("--tiff", required=True, help="Girdi 1 (TIFF/PNG/JPG)")
    p.add_argument("--tiff2", help="Girdi 2 (opsiyonel)")
    p.add_argument("--out", default="./output", help="Çıkış klasörü (vars: ./output)")
    p.add_argument("--tile", type=int, default=256, help="Tile boyutu (vars: 256)")
    p.add_argument("--fmt", default="jpg", choices=["jpg", "jpeg", "png"], help="Tile formatı (vars: jpg)")
    p.add_argument("--overlap", type=int, default=0, help="Tile overlap (vars: 0)")
    p.add_argument("--serve", action="store_true", help="Yerel HTTP sunucu başlat ve sayfayı aç")
    p.add_argument("--port", type=int, default=8000, help="Sunucu portu (vars: 8000)")
    p.add_argument("--backend", choices=["auto", "pyvips", "pillow"], default="auto",
                   help="DZI üretim motoru: auto|pyvips|pillow (vars: auto)")
    p.add_argument("--overwrite", action="store_true",
                   help="Mevcut .dzi ve _files klasörünü sil ve yeniden üret")
    p.add_argument("--unsafe-big", action="store_true",
                   help="(Pillow) MAX_IMAGE_PIXELS sınırını kaldır")
    args = p.parse_args()

    src1 = args.tiff
    src2 = args.tiff2
    out_dir = args.out
    tile = args.tile
    fmt = args.fmt
    overlap = args.overlap
    backend = args.backend
    overwrite = args.overwrite
    unsafe_big = args.unsafe_big

    if not os.path.isfile(src1):
        print(f"[!] Bulunamadı: {src1}", file=sys.stderr)
        sys.exit(1)
    if src2 and not os.path.isfile(src2):
        print(f"[!] Bulunamadı: {src2}", file=sys.stderr)
        sys.exit(1)

    base1 = os.path.splitext(os.path.basename(src1))[0]
    base2 = os.path.splitext(os.path.basename(src2))[0] if src2 else None
    os.makedirs(out_dir, exist_ok=True)

    print(f"[i] Girdi1: {src1}")
    if src2: print(f"[i] Girdi2: {src2}")
    print(f"[i] Backend: {backend}")

    def build_one(src, base):
        dzi_path = None
        files_dir = None
        last_err = None

        if backend in ("auto", "pyvips") and has_python_pyvips():
            try:
                if overwrite:
                    _cleanup_dz_destination(out_dir, base)
                print(f"[i] pyvips (Python) ile DZI üretiliyor... ({base})")
                dzi_path, files_dir = dzi_with_pyvips_python(src, out_dir, base, tile, overlap, fmt)
            except Exception as e:
                last_err = e
                if backend == "pyvips":
                    print(f"[!] pyvips (Python) başarısız: {e}", file=sys.stderr)
                else:
                    print(f"[!] pyvips (Python) başarısız, vips(CLI) deneniyor: {e}")

        if dzi_path is None and backend in ("auto", "pyvips") and has_cli_vips():
            try:
                print(f"[i] vips (CLI) ile DZI üretiliyor... ({base})")
                dzi_path, files_dir = dzi_with_vips_cli(src, out_dir, base, tile, overlap, fmt, overwrite=overwrite)
            except Exception as e:
                last_err = e
                if backend == "pyvips":
                    print(f"[!] vips (CLI) başarısız: {e}", file=sys.stderr)
                else:
                    print(f"[!] vips (CLI) başarısız, Pillow'a düşülüyor: {e}")

        if dzi_path is None:
            print(f"[i] Pillow ile DZI üretiliyor... ({base})")
            try:
                dzi_path, files_dir = dzi_with_pillow(src, out_dir, base, tile, overlap, fmt, unsafe_big=unsafe_big)
            except Exception as e:
                if "DecompressionBombError" in str(e) and not unsafe_big:
                    print("[!] Pillow DecompressionBombError: MAX_IMAGE_PIXELS kaldırılıp tekrar denenecek.")
                    try:
                        dzi_path, files_dir = dzi_with_pillow(src, out_dir, base, tile, overlap, fmt, unsafe_big=True)
                    except Exception as e2:
                        print(f"[!] Pillow yeniden deneme de başarısız: {e2}", file=sys.stderr)
                        sys.exit(2)
                else:
                    print(f"[!] Pillow başarısız: {e}", file=sys.stderr)
                    if last_err:
                        print(f"[i] Önceki hata: {last_err}", file=sys.stderr)
                    sys.exit(2)
        return dzi_path, files_dir

    # Görselleri işle
    dzi1, tiles1 = build_one(src1, base1)
    if src2:
        dzi2, tiles2 = build_one(src2, base2)
    else:
        dzi2 = tiles2 = None

    # Tekli viewer (annotations sadece burada)
    write_viewer_html(out_dir, base1)

    # Meta (dinamik compare bunu okur)
    meta = {"images": []}
    meta["images"].append({
        "src": os.path.join(out_dir, dzi1),
        "tiles_dir": os.path.join(out_dir, tiles1),
        "tile": tile, "format": fmt, "overlap": overlap
    })
    if src2:
        meta["images"].append({
            "src": os.path.join(out_dir, dzi2),
            "tiles_dir": os.path.join(out_dir, tiles2),
            "tile": tile, "format": fmt, "overlap": overlap
        })
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # Dinamik compare sayfasını yaz (annotations yok)
    write_compare_html(out_dir)

    print("[✓] Tamamlandı")
    print(f"    - DZI #1: {os.path.join(out_dir, dzi1)}")
    if dzi2:
        print(f"    - DZI #2: {os.path.join(out_dir, dzi2)}")
    print(f"    - Viewer: {os.path.join(out_dir, 'viewer.html')}")
    print(f"    - Compare: {os.path.join(out_dir, 'compare.html')}")

    if args.serve:
        def _serve():
            serve_directory(out_dir, args.port)
        t = Thread(target=_serve, daemon=True)
        t.start()
        url = f"http://localhost:{args.port}/viewer.html"
        try:
            webbrowser.open(url)
        except Exception:
            pass
        print("[i] Çıkmak için Ctrl+C.")
        try:
            t.join()
        except KeyboardInterrupt:
            print("\n[i] Kapatılıyor...")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Ambient Watcher - 摄像头调试面板
实时预览 + ffmpeg 参数 + 硬件缩放控制 + Center Stage
http://localhost:8765
"""
import subprocess
import threading
import time
import os
import sys
import json
import webbrowser
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 确保能导入项目模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FFMPEG_BIN = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

# 尝试加载 MacCameraControl
try:
    from src.mac_camera_control import MacCameraControl, list_devices as list_native_devices
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False

# ============================================================
# 全局状态
# ============================================================
current_frame = None
frame_lock = threading.Lock()
capture_running = False
capture_thread = None
hw_control = None  # MacCameraControl

capture_stats = {
    "device_index": "0",
    "device_name": "MacBook Pro相机",
    "width": 1920,
    "height": 1080,
    "framerate": 30,
    "fps_actual": 0.0,
    "frame_count": 0,
    "frame_size_kb": 0,
    "status": "stopped",
    "error": "",
    "ffmpeg_cmd": "",
    "zoom": 1.0,
    "zoom_min": 1.0,
    "zoom_max": 16.0,
    "center_stage_supported": False,
    "center_stage_enabled": False,
    "has_native_control": HAS_NATIVE,
}
available_devices = []


def discover_devices():
    global available_devices
    try:
        result = subprocess.run(
            [FFMPEG_BIN, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True, text=True, timeout=5
        )
        devices = []
        in_video = False
        for line in result.stderr.splitlines():
            if "AVFoundation video devices" in line:
                in_video = True
                continue
            if "AVFoundation audio devices" in line:
                break
            if in_video and "[" in line:
                parts = line.split("]")
                if len(parts) >= 2:
                    idx_part = parts[-2].split("[")[-1].strip()
                    name = parts[-1].strip()
                    try:
                        idx = int(idx_part)
                        if "iphone" not in name.lower() and "ipad" not in name.lower():
                            devices.append({"index": idx, "name": name})
                    except ValueError:
                        pass
        available_devices = devices
    except Exception as e:
        print(f"Device discovery failed: {e}")


def init_hw_control():
    global hw_control
    if not HAS_NATIVE:
        return
    hw_control = MacCameraControl({'device_keyword': 'MacBook'})
    if hw_control.open():
        hw_control.enable_center_stage(False)
        hw_control.set_widest_fov()
        _sync_hw_stats()
    else:
        hw_control = None


def _sync_hw_stats():
    if hw_control:
        capture_stats["zoom"] = hw_control.get_zoom()
        capture_stats["zoom_min"] = hw_control.get_min_zoom()
        capture_stats["zoom_max"] = hw_control.get_max_zoom()
        capture_stats["center_stage_supported"] = hw_control.is_center_stage_supported()
        capture_stats["center_stage_enabled"] = hw_control.is_center_stage_enabled()


# ============================================================
# ffmpeg 捕获
# ============================================================
def capture_loop(device_index, width, height, framerate):
    global current_frame, capture_running, capture_stats

    capture_stats.update({
        "device_index": str(device_index),
        "width": width, "height": height, "framerate": framerate,
        "status": "starting", "error": "", "frame_count": 0,
    })

    cmd = [
        FFMPEG_BIN,
        "-f", "avfoundation",
        "-video_size", f"{width}x{height}",
        "-framerate", str(framerate),
        "-i", str(device_index),
        "-c:v", "mjpeg", "-q:v", "5",
        "-f", "mpjpeg", "-an",
        "pipe:1"
    ]
    capture_stats["ffmpeg_cmd"] = " ".join(cmd)

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1024*1024)
    except Exception as e:
        capture_stats["status"] = "error"
        capture_stats["error"] = str(e)
        return

    capture_stats["status"] = "running"
    fps_counter = 0
    fps_timer = time.time()
    buf = b""
    BOUNDARY = b"--ffmpeg"

    try:
        while capture_running:
            chunk = proc.stdout.read(65536)
            if not chunk:
                if capture_running:
                    stderr_out = proc.stderr.read(300).decode("utf-8", errors="replace") if proc.stderr else ""
                    capture_stats["status"] = "error"
                    capture_stats["error"] = f"Stream ended. {stderr_out}"
                break

            buf += chunk

            while True:
                bp = buf.find(BOUNDARY)
                if bp == -1:
                    break
                he = buf.find(b"\r\n\r\n", bp)
                if he == -1:
                    break

                header = buf[bp:he].decode("utf-8", errors="replace")
                cl = None
                for line in header.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try:
                            cl = int(line.split(":")[1].strip())
                        except ValueError:
                            pass

                js = he + 4
                if cl is not None:
                    je = js + cl
                    if len(buf) < je:
                        break
                    jpeg = buf[js:je]
                    buf = buf[je:]
                else:
                    nb = buf.find(BOUNDARY, bp + len(BOUNDARY))
                    if nb == -1:
                        break
                    jpeg = buf[js:nb].rstrip(b"\r\n")
                    buf = buf[nb:]

                if len(jpeg) > 100 and jpeg[:2] == b"\xff\xd8":
                    with frame_lock:
                        current_frame = jpeg
                    capture_stats["frame_count"] += 1
                    capture_stats["frame_size_kb"] = len(jpeg) / 1024
                    fps_counter += 1
                    elapsed = time.time() - fps_timer
                    if elapsed >= 1.0:
                        capture_stats["fps_actual"] = fps_counter / elapsed
                        fps_counter = 0
                        fps_timer = time.time()
                    _sync_hw_stats()

    except Exception as e:
        if capture_running:
            capture_stats["status"] = "error"
            capture_stats["error"] = str(e)

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
    capture_stats["status"] = "stopped"


# ============================================================
# HTTP
# ============================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Ambient Watcher - Camera Debug</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a2e;color:#e0e0e0;font-family:-apple-system,'SF Mono',monospace}
.header{background:#16213e;padding:10px 20px;display:flex;align-items:center;justify-content:space-between}
.header h1{font-size:16px;color:#00d4ff}
.badge{font-size:12px;padding:3px 10px;border-radius:10px;font-weight:600}
.badge-running{background:#00c853;color:#000}.badge-stopped{background:#ff5252;color:#fff}
.badge-starting{background:#ffd600;color:#000}.badge-error{background:#ff9100;color:#000}
.main{display:flex;height:calc(100vh - 44px)}
.vid{flex:1;display:flex;align-items:center;justify-content:center;background:#0a0a1a;overflow:hidden}
.vid img{max-width:100%;max-height:100%;object-fit:contain}
.vid .ph{color:#555;font-size:18px}
.side{width:360px;background:#16213e;padding:14px;overflow-y:auto;border-left:1px solid #2a2a4e}
.sec{margin-bottom:14px}
.sec h3{color:#00d4ff;font-size:11px;margin-bottom:5px;text-transform:uppercase;letter-spacing:1px}
.row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #2a2a4e;font-size:12px}
.k{color:#888}.v{color:#e0e0e0;font-weight:600}
.cmd{background:#0a0a1a;padding:8px;border-radius:6px;font-size:10px;color:#00d4ff;word-break:break-all;line-height:1.4}
select,button,.slider-wrap input{width:100%;padding:6px;margin-bottom:5px;border:1px solid #2a2a4e;background:#0a0a1a;color:#e0e0e0;border-radius:5px;font-size:12px;cursor:pointer}
button{background:#00d4ff;color:#000;font-weight:600;border:none}
button:hover{background:#00b8d4}
button.stop{background:#ff5252;color:#fff}
label{font-size:11px;color:#666;display:block;margin-bottom:2px;margin-top:3px}
.err{background:#3e1111;padding:6px;border-radius:5px;color:#ff5252;font-size:11px}
.slider-wrap{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.slider-wrap input[type=range]{flex:1;-webkit-appearance:none;height:6px;background:#2a2a4e;border-radius:3px;border:none;padding:0}
.slider-wrap input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#00d4ff;cursor:pointer}
.slider-val{min-width:40px;text-align:right;font-size:12px;color:#00d4ff;font-weight:600}
.toggle{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:12px}
.toggle input{width:auto;margin:0}
.hw-badge{font-size:10px;padding:2px 6px;border-radius:4px;background:#2a2a4e;color:#888}
.hw-badge.on{background:#00c853;color:#000}
</style>
</head>
<body>
<div class="header">
  <h1>Ambient Watcher Camera Debug</h1>
  <div>
    <span class="hw-badge" id="hwBadge">Native: --</span>
    <span class="badge" id="sBadge">--</span>
  </div>
</div>
<div class="main">
  <div class="vid">
    <img id="stream" alt="">
    <div class="ph" id="ph">Connecting...</div>
  </div>
  <div class="side">
    <div class="sec">
      <h3>Parameters</h3>
      <div class="row"><span class="k">Device</span><span class="v" id="pDev">--</span></div>
      <div class="row"><span class="k">Resolution</span><span class="v" id="pRes">--</span></div>
      <div class="row"><span class="k">FPS (set / actual)</span><span class="v" id="pFps">--</span></div>
      <div class="row"><span class="k">Frames</span><span class="v" id="pFrm">--</span></div>
      <div class="row"><span class="k">Frame Size</span><span class="v" id="pSz">--</span></div>
    </div>

    <div class="sec" id="zoomSec">
      <h3>Zoom / FOV Control</h3>
      <div class="row"><span class="k">Zoom</span><span class="v" id="pZoom">--</span></div>
      <label>Zoom Factor</label>
      <div class="slider-wrap">
        <input type="range" id="zoomSlider" min="1" max="16" step="0.1" value="1">
        <span class="slider-val" id="zoomVal">1.0</span>
      </div>
      <div class="toggle">
        <input type="checkbox" id="csToggle">
        <span>Center Stage</span>
        <span class="hw-badge" id="csBadge">--</span>
      </div>
    </div>

    <div class="sec">
      <h3>ffmpeg cmd</h3>
      <div class="cmd" id="pCmd">--</div>
    </div>
    <div class="sec" id="errSec" style="display:none">
      <h3>Error</h3>
      <div class="err" id="pErr"></div>
    </div>
    <div class="sec">
      <h3>Controls</h3>
      <label>Device</label>
      <select id="devSel"></select>
      <label>Resolution</label>
      <select id="resSel">
        <option value="1920x1080">1920x1080</option>
        <option value="1280x720">1280x720</option>
        <option value="640x480">640x480</option>
      </select>
      <label>Framerate</label>
      <select id="fpsSel">
        <option value="30">30</option>
        <option value="15">15</option>
        <option value="10">10</option>
        <option value="5">5</option>
      </select>
      <button onclick="doStart()">Apply & Restart</button>
      <button class="stop" onclick="doStop()">Stop</button>
    </div>
  </div>
</div>
<script>
const img=document.getElementById('stream'), ph=document.getElementById('ph');
const zoomSlider=document.getElementById('zoomSlider'), zoomVal=document.getElementById('zoomVal');
const csToggle=document.getElementById('csToggle');
let debounceTimer=null;

function startStream(){img.src='/frame?'+Date.now()}
img.onload=function(){img.style.display='block';ph.style.display='none';setTimeout(()=>{img.src='/frame?'+Date.now()},33)};
img.onerror=function(){img.style.display='none';ph.style.display='block';ph.textContent='No Signal';setTimeout(startStream,1000)};

zoomSlider.addEventListener('input',function(){
  zoomVal.textContent=parseFloat(this.value).toFixed(1);
  clearTimeout(debounceTimer);
  debounceTimer=setTimeout(()=>{fetch('/api/zoom?factor='+this.value)},100);
});

csToggle.addEventListener('change',function(){
  fetch('/api/center_stage?enabled='+(this.checked?'1':'0'));
});

async function poll(){
  try{
    const r=await fetch('/api/status');const d=await r.json();
    document.getElementById('pDev').textContent=d.device_index+' ('+d.device_name+')';
    document.getElementById('pRes').textContent=d.width+'x'+d.height;
    document.getElementById('pFps').textContent=d.framerate+' / '+d.fps_actual.toFixed(1);
    document.getElementById('pFrm').textContent=d.frame_count;
    document.getElementById('pSz').textContent=d.frame_size_kb.toFixed(1)+' KB';
    document.getElementById('pCmd').textContent=d.ffmpeg_cmd||'--';
    document.getElementById('pZoom').textContent=d.zoom.toFixed(1)+' ('+d.zoom_min.toFixed(1)+'-'+d.zoom_max.toFixed(1)+')';
    const b=document.getElementById('sBadge');b.textContent=d.status;b.className='badge badge-'+d.status;
    zoomSlider.min=d.zoom_min;zoomSlider.max=d.zoom_max;
    // 只在用户没在拖动时更新 slider
    if(!document.activeElement||document.activeElement!==zoomSlider){
      zoomSlider.value=d.zoom;zoomVal.textContent=d.zoom.toFixed(1);
    }
    csToggle.checked=d.center_stage_enabled;
    const csb=document.getElementById('csBadge');
    csb.textContent=d.center_stage_supported?'Supported':'Not Available';
    csb.className='hw-badge'+(d.center_stage_supported?' on':'');
    const hwb=document.getElementById('hwBadge');
    hwb.textContent='Native: '+(d.has_native_control?'ON':'OFF');
    hwb.className='hw-badge'+(d.has_native_control?' on':'');
    if(d.error){document.getElementById('errSec').style.display='block';document.getElementById('pErr').textContent=d.error}
    else{document.getElementById('errSec').style.display='none'}
    if(!d.has_native_control){document.getElementById('zoomSec').style.opacity='0.4'}
  }catch(e){}
}

async function loadDevices(){
  try{const r=await fetch('/api/devices');const devs=await r.json();
  const s=document.getElementById('devSel');s.innerHTML='';
  devs.forEach(d=>{const o=document.createElement('option');o.value=d.index;o.textContent='['+d.index+'] '+d.name;s.appendChild(o)})}catch(e){}
}

async function doStart(){
  const dev=document.getElementById('devSel').value;
  const res=document.getElementById('resSel').value.split('x');
  const fps=document.getElementById('fpsSel').value;
  await fetch('/api/start?device='+dev+'&width='+res[0]+'&height='+res[1]+'&fps='+fps);
  setTimeout(startStream,500);
}
async function doStop(){await fetch('/api/stop')}

loadDevices();startStream();setInterval(poll,500);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            self._html()
        elif path == "/frame":
            self._frame()
        elif path == "/api/status":
            self._json(capture_stats)
        elif path == "/api/devices":
            self._json(available_devices)
        elif path == "/api/zoom":
            self._handle_zoom()
        elif path == "/api/center_stage":
            self._handle_center_stage()
        elif self.path.startswith("/api/start"):
            self._handle_start()
        elif path == "/api/stop":
            stop_capture()
            self._text("OK")
        else:
            self.send_error(404)

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode())

    def _frame(self):
        with frame_lock:
            f = current_frame
        if f:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(f)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(f)
        else:
            self.send_error(503)

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _text(self, msg):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def _handle_zoom(self):
        q = parse_qs(urlparse(self.path).query)
        try:
            factor = float(q.get("factor", ["1.0"])[0])
        except (ValueError, IndexError):
            self.send_error(400, "Invalid factor")
            return
        factor = max(0.5, min(factor, 20.0))
        if hw_control:
            hw_control.set_zoom(factor)
            _sync_hw_stats()
        self._text("OK")

    def _handle_center_stage(self):
        q = parse_qs(urlparse(self.path).query)
        enabled = q.get("enabled", ["0"])[0] == "1"
        if hw_control:
            hw_control.enable_center_stage(enabled)
            _sync_hw_stats()
        self._text("OK")

    def _handle_start(self):
        q = parse_qs(urlparse(self.path).query)
        try:
            dev = q.get("device", ["0"])[0]
            w = int(q.get("width", ["1920"])[0])
            h = int(q.get("height", ["1080"])[0])
            fps = int(q.get("fps", ["30"])[0])
        except (ValueError, IndexError):
            self.send_error(400, "Invalid parameters")
            return
        w = max(320, min(w, 3840))
        h = max(240, min(h, 2160))
        fps = max(1, min(fps, 60))
        start_capture(dev, w, h, fps)
        self._text("OK")


def start_capture(device_index="0", width=1920, height=1080, framerate=30):
    global capture_running, capture_thread
    stop_capture()
    time.sleep(0.3)

    name = str(device_index)
    for d in available_devices:
        if str(d["index"]) == str(device_index):
            name = d["name"]
            break
    capture_stats["device_name"] = name

    capture_running = True
    capture_thread = threading.Thread(
        target=capture_loop, args=(device_index, width, height, framerate), daemon=True
    )
    capture_thread.start()


def stop_capture():
    global capture_running, current_frame
    capture_running = False
    if capture_thread:
        capture_thread.join(timeout=3)
    with frame_lock:
        current_frame = None


def main():
    port = 8765
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 50)
    print("  Ambient Watcher - Camera Debug Panel")
    print("=" * 50)

    print("\nDiscovering devices...")
    discover_devices()
    for d in available_devices:
        print(f"  [{d['index']}] {d['name']}")

    print("\nInitializing hardware control...")
    init_hw_control()
    if hw_control:
        print(f"  Zoom: {hw_control.get_zoom()} (range {hw_control.get_min_zoom()}-{hw_control.get_max_zoom()})")
        print(f"  Center Stage: {'ON' if hw_control.is_center_stage_enabled() else 'OFF'}")
    else:
        print("  (not available)")

    print("\nStarting capture...")
    start_capture("0", 1920, 1080, 30)

    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://localhost:{port}"
    print(f"\n  >>> {url}")
    print("  >>> Ctrl+C to quit\n")
    webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        stop_capture()
        server.shutdown()


if __name__ == "__main__":
    main()

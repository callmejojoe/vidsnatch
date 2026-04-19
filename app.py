#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import re
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import urllib.request

DOWNLOAD_DIR = os.path.expanduser("~/Downloads/VidSnatch")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Global state for progress tracking
download_jobs = {}  # job_id -> {status, progress, filename, error}

def ensure_ytdlp():
    """Install yt-dlp if not present."""
    result = subprocess.run(["which", "yt-dlp"], capture_output=True)
    if result.returncode != 0:
        print("Installing yt-dlp...")
        subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp", "--break-system-packages", "-q"], check=True)
    return True

def get_video_info(url):
    """Fetch video metadata."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None, result.stderr
        data = json.loads(result.stdout)
        return {
            "title": data.get("title", "Unknown"),
            "uploader": data.get("uploader", data.get("channel", "Unknown")),
            "duration": data.get("duration_string", data.get("duration", "?")),
            "thumbnail": data.get("thumbnail", ""),
            "formats": get_format_options(data),
            "webpage_url": data.get("webpage_url", url),
        }, None
    except subprocess.TimeoutExpired:
        return None, "Request timed out. Check the URL."
    except Exception as e:
        return None, str(e)

def get_format_options(data):
    formats = data.get("formats", [])
    options = []
    seen = set()

    # Add best combined options
    combined = [
        ("best", "Best Quality (auto)"),
        ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best", "Best MP4"),
        ("bestvideo[height<=1080]+bestaudio/best[height<=1080]", "1080p max"),
        ("bestvideo[height<=720]+bestaudio/best[height<=720]", "720p max"),
        ("bestvideo[height<=480]+bestaudio/best[height<=480]", "480p max"),
        ("bestaudio[ext=m4a]/bestaudio", "Audio only (M4A)"),
        ("bestaudio", "Audio only (best)"),
    ]
    for fmt_id, label in combined:
        options.append({"id": fmt_id, "label": label})

    return options

def download_video(job_id, url, format_id):
    """Run yt-dlp download in background thread."""
    download_jobs[job_id] = {"status": "downloading", "progress": 0, "filename": None, "error": None, "log": ""}

    output_template = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", format_id,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--newline",
        "-o", output_template,
        url
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log_lines = []
        for line in proc.stdout:
            line = line.strip()
            log_lines.append(line)
            # Parse progress
            if "[download]" in line and "%" in line:
                match = re.search(r'(\d+\.?\d*)%', line)
                if match:
                    download_jobs[job_id]["progress"] = float(match.group(1))
            # Get filename
            if "[Merger]" in line or "Destination:" in line:
                match = re.search(r'Destination:\s*(.+)', line)
                if match:
                    download_jobs[job_id]["filename"] = os.path.basename(match.group(1).strip())
            download_jobs[job_id]["log"] = "\n".join(log_lines[-20:])

        proc.wait()
        if proc.returncode == 0:
            download_jobs[job_id]["status"] = "done"
            download_jobs[job_id]["progress"] = 100
        else:
            download_jobs[job_id]["status"] = "error"
            download_jobs[job_id]["error"] = "Download failed. Check URL or format."
    except Exception as e:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["error"] = str(e)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VidSnatch</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0a;
    --surface: #111;
    --border: #1e1e1e;
    --accent: #ff3d00;
    --accent2: #ff6d40;
    --text: #e8e8e8;
    --muted: #555;
    --green: #39ff14;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: var(--bg); color: var(--text); font-family: 'DM Mono', monospace; }

  body {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-height: 100vh;
    padding: 40px 20px;
    background-image: radial-gradient(ellipse at 50% 0%, rgba(255,61,0,0.08) 0%, transparent 60%);
  }

  header {
    text-align: center;
    margin-bottom: 48px;
  }

  .logo {
    font-family: 'Bebas Neue', cursive;
    font-size: clamp(56px, 12vw, 100px);
    letter-spacing: 6px;
    background: linear-gradient(135deg, #ff3d00, #ff8c00, #ff3d00);
    background-size: 200% 200%;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: shimmer 4s ease infinite;
    line-height: 1;
  }

  @keyframes shimmer {
    0%, 100% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
  }

  .tagline {
    font-size: 11px;
    letter-spacing: 4px;
    color: var(--muted);
    text-transform: uppercase;
    margin-top: 8px;
  }

  .card {
    width: 100%;
    max-width: 680px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 32px;
    margin-bottom: 24px;
  }

  .input-row {
    display: flex;
    gap: 10px;
  }

  input[type="text"] {
    flex: 1;
    background: #0a0a0a;
    border: 1px solid var(--border);
    border-radius: 2px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    padding: 12px 16px;
    outline: none;
    transition: border-color 0.2s;
  }
  input[type="text"]:focus { border-color: var(--accent); }
  input[type="text"]::placeholder { color: var(--muted); }

  button {
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 2px;
    font-family: 'Bebas Neue', cursive;
    font-size: 18px;
    letter-spacing: 2px;
    padding: 12px 24px;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    white-space: nowrap;
  }
  button:hover { background: var(--accent2); }
  button:active { transform: scale(0.97); }
  button:disabled { background: #333; color: var(--muted); cursor: not-allowed; transform: none; }

  .section-label {
    font-size: 10px;
    letter-spacing: 3px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 16px;
  }

  /* Info card */
  .info-card { display: none; }
  .info-card.visible { display: block; }

  .thumb-row {
    display: flex;
    gap: 20px;
    align-items: flex-start;
    margin-bottom: 24px;
  }

  .thumb {
    width: 160px;
    height: 90px;
    object-fit: cover;
    border-radius: 2px;
    border: 1px solid var(--border);
    flex-shrink: 0;
    background: var(--border);
  }

  .thumb-placeholder {
    width: 160px;
    height: 90px;
    background: var(--border);
    border-radius: 2px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
  }

  .meta h2 {
    font-family: 'Bebas Neue', cursive;
    font-size: 22px;
    letter-spacing: 1px;
    margin-bottom: 6px;
    line-height: 1.2;
  }

  .meta p {
    font-size: 11px;
    color: var(--muted);
    margin-bottom: 3px;
  }

  select {
    width: 100%;
    background: #0a0a0a;
    border: 1px solid var(--border);
    border-radius: 2px;
    color: var(--text);
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    padding: 10px 14px;
    outline: none;
    margin-bottom: 16px;
    cursor: pointer;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23555' stroke-width='1.5' fill='none'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 14px center;
  }

  /* Progress */
  .progress-wrap { display: none; margin-top: 20px; }
  .progress-wrap.visible { display: block; }

  .progress-bar-bg {
    height: 3px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 8px;
  }
  .progress-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    border-radius: 2px;
    transition: width 0.3s ease;
    width: 0%;
  }

  .progress-text {
    font-size: 11px;
    color: var(--muted);
    display: flex;
    justify-content: space-between;
  }

  .status-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    margin-right: 6px;
    background: var(--muted);
  }
  .status-dot.active { background: var(--green); animation: pulse 1s ease infinite; }
  .status-dot.done { background: var(--green); animation: none; }
  .status-dot.error { background: var(--accent); animation: none; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .log-box {
    margin-top: 12px;
    background: #0a0a0a;
    border: 1px solid var(--border);
    border-radius: 2px;
    padding: 10px 14px;
    font-size: 10px;
    color: var(--muted);
    max-height: 120px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    display: none;
  }
  .log-box.visible { display: block; }

  .done-banner {
    background: rgba(57, 255, 20, 0.07);
    border: 1px solid rgba(57, 255, 20, 0.2);
    border-radius: 2px;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--green);
    margin-top: 12px;
    display: none;
  }
  .done-banner.visible { display: block; }

  .error-banner {
    background: rgba(255,61,0,0.07);
    border: 1px solid rgba(255,61,0,0.2);
    border-radius: 2px;
    padding: 12px 16px;
    font-size: 12px;
    color: var(--accent2);
    margin-top: 12px;
    display: none;
  }
  .error-banner.visible { display: block; }

  .dir-note {
    font-size: 10px;
    color: var(--muted);
    text-align: center;
    margin-top: 8px;
  }
  .dir-note span { color: #888; }

  .spinner {
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  footer {
    margin-top: 32px;
    font-size: 10px;
    color: var(--muted);
    letter-spacing: 2px;
    text-align: center;
  }
</style>
</head>
<body>

<header>
  <div class="logo">VidSnatch</div>
  <div class="tagline">paste link &nbsp;·&nbsp; pick quality &nbsp;·&nbsp; grab video</div>
</header>

<!-- URL input -->
<div class="card">
  <div class="section-label">Video URL</div>
  <div class="input-row">
    <input type="text" id="urlInput" placeholder="https://youtube.com/watch?v=... or any site" />
    <button id="fetchBtn" onclick="fetchInfo()">Fetch</button>
  </div>
</div>

<!-- Info + download card -->
<div class="card info-card" id="infoCard">
  <div class="section-label">Video Info</div>

  <div class="thumb-row">
    <div id="thumbWrap" class="thumb-placeholder">🎬</div>
    <div class="meta" id="metaInfo">
      <h2 id="vidTitle">–</h2>
      <p id="vidUploader"></p>
      <p id="vidDuration"></p>
    </div>
  </div>

  <div class="section-label">Format / Quality</div>
  <select id="formatSelect"></select>

  <button id="dlBtn" onclick="startDownload()" style="width:100%; font-size:20px; padding:14px;">
    Download
  </button>

  <!-- Progress -->
  <div class="progress-wrap" id="progressWrap">
    <div class="progress-bar-bg">
      <div class="progress-bar-fill" id="progressFill"></div>
    </div>
    <div class="progress-text">
      <span><span class="status-dot" id="statusDot"></span><span id="statusText">Starting...</span></span>
      <span id="progressPct">0%</span>
    </div>
    <div class="log-box" id="logBox"></div>
    <div class="done-banner" id="doneBanner">✓ Download complete — saved to ~/Downloads/VidSnatch/</div>
    <div class="error-banner" id="errorBanner"></div>
  </div>
</div>

<div class="dir-note">Downloads saved to <span>~/Downloads/VidSnatch/</span></div>

<footer>Powered by yt-dlp &nbsp;·&nbsp; 1000+ supported sites</footer>

<script>
let currentJobId = null;
let pollInterval = null;

async function fetchInfo() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) return;

  const btn = document.getElementById('fetchBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';

  try {
    const res = await fetch('/api/info?url=' + encodeURIComponent(url));
    const data = await res.json();

    if (data.error) {
      alert('Error: ' + data.error);
      btn.disabled = false;
      btn.textContent = 'Fetch';
      return;
    }

    // Populate info
    document.getElementById('vidTitle').textContent = data.title;
    document.getElementById('vidUploader').textContent = '↑ ' + data.uploader;
    document.getElementById('vidDuration').textContent = '⏱ ' + data.duration;

    const thumbWrap = document.getElementById('thumbWrap');
    if (data.thumbnail) {
      thumbWrap.innerHTML = `<img class="thumb" src="${data.thumbnail}" onerror="this.parentNode.innerHTML='🎬'">`;
    }

    // Populate formats
    const sel = document.getElementById('formatSelect');
    sel.innerHTML = '';
    data.formats.forEach(f => {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.textContent = f.label;
      sel.appendChild(opt);
    });

    document.getElementById('infoCard').classList.add('visible');
    resetProgress();
  } catch(e) {
    alert('Failed to fetch info: ' + e.message);
  }

  btn.disabled = false;
  btn.textContent = 'Fetch';
}

async function startDownload() {
  const url = document.getElementById('urlInput').value.trim();
  const fmt = document.getElementById('formatSelect').value;
  if (!url || !fmt) return;

  const btn = document.getElementById('dlBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Downloading...';

  resetProgress();
  document.getElementById('progressWrap').classList.add('visible');
  document.getElementById('logBox').classList.add('visible');

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ url, format: fmt })
    });
    const data = await res.json();
    currentJobId = data.job_id;
    pollProgress();
  } catch(e) {
    showError('Failed to start: ' + e.message);
    btn.disabled = false;
    btn.textContent = 'Download';
  }
}

function pollProgress() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/status?job=' + currentJobId);
      const data = await res.json();
      updateProgress(data);
      if (data.status === 'done' || data.status === 'error') {
        clearInterval(pollInterval);
        const btn = document.getElementById('dlBtn');
        btn.disabled = false;
        btn.textContent = 'Download Again';
      }
    } catch(e) {}
  }, 800);
}

function updateProgress(data) {
  const pct = Math.round(data.progress || 0);
  document.getElementById('progressFill').style.width = pct + '%';
  document.getElementById('progressPct').textContent = pct + '%';
  document.getElementById('logBox').textContent = data.log || '';

  const dot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');

  if (data.status === 'downloading') {
    dot.className = 'status-dot active';
    statusText.textContent = 'Downloading...';
  } else if (data.status === 'done') {
    dot.className = 'status-dot done';
    statusText.textContent = 'Complete!';
    document.getElementById('doneBanner').classList.add('visible');
    document.getElementById('progressFill').style.width = '100%';
    document.getElementById('progressPct').textContent = '100%';
  } else if (data.status === 'error') {
    dot.className = 'status-dot error';
    statusText.textContent = 'Error';
    showError(data.error);
  }
}

function showError(msg) {
  const el = document.getElementById('errorBanner');
  el.textContent = '✗ ' + msg;
  el.classList.add('visible');
}

function resetProgress() {
  document.getElementById('progressFill').style.width = '0%';
  document.getElementById('progressPct').textContent = '0%';
  document.getElementById('statusText').textContent = 'Starting...';
  document.getElementById('statusDot').className = 'status-dot';
  document.getElementById('doneBanner').classList.remove('visible');
  document.getElementById('errorBanner').classList.remove('visible');
  document.getElementById('logBox').textContent = '';
}

// Enter key support
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('urlInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') fetchInfo();
  });
});
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())

        elif path == "/api/info":
            url = qs.get("url", [""])[0]
            if not url:
                self.json_response({"error": "No URL provided"})
                return
            info, err = get_video_info(url)
            if err:
                self.json_response({"error": err})
            else:
                self.json_response(info)

        elif path == "/api/status":
            job_id = qs.get("job", [""])[0]
            if job_id in download_jobs:
                self.json_response(download_jobs[job_id])
            else:
                self.json_response({"status": "unknown"})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/download":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            url = body.get("url", "")
            fmt = body.get("format", "best")

            job_id = str(int(time.time() * 1000))
            thread = threading.Thread(target=download_video, args=(job_id, url, fmt), daemon=True)
            thread.start()
            self.json_response({"job_id": job_id})
        else:
            self.send_response(404)
            self.end_headers()

    def json_response(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    print("🔧 Checking dependencies...")
    ensure_ytdlp()
    print(f"📁 Downloads will save to: {DOWNLOAD_DIR}")
    PORT = 7979
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"🚀 VidSnatch running at http://localhost:{PORT}")
    print("   Press Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

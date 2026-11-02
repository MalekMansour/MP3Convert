"""
WAV -> MP3 Converter
Run:  pip install -r requirements.txt
      python app.py
Then open http://127.0.0.1:5000 (it opens automatically).
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import webbrowser
import zipfile

import imageio_ffmpeg
from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None  # no upload size limit

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()  # bundled ffmpeg, no separate install
WORK_DIR = tempfile.mkdtemp(prefix="wav2mp3_")
ALLOWED_BITRATES = {"128", "192", "256", "320"}
lock = threading.Lock()


def safe_id(value):
    if not value or not re.fullmatch(r"[a-f0-9\-]{8,64}", value):
        abort(400, "bad session id")
    return value


def safe_name(name):
    name = os.path.basename(name or "audio")
    name = re.sub(r"[^\w\-. ()\[\]]", "_", name).strip() or "audio"
    return name


def unique_path(folder, filename):
    base, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


@app.post("/convert")
def convert():
    sid = safe_id(request.form.get("session"))
    bitrate = request.form.get("bitrate", "192")
    if bitrate not in ALLOWED_BITRATES:
        bitrate = "192"
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file received"), 400

    name = safe_name(f.filename)
    if not name.lower().endswith(".wav"):
        return jsonify(error="Not a .wav file"), 400

    session_dir = os.path.join(WORK_DIR, sid)
    out_dir = os.path.join(session_dir, "mp3")
    os.makedirs(out_dir, exist_ok=True)

    src = os.path.join(session_dir, f"{uuid.uuid4().hex}.wav")
    f.save(src)

    with lock:  # reserve a unique output name
        dst = unique_path(out_dir, os.path.splitext(name)[0] + ".mp3")
        open(dst, "wb").close()

    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", src,
           "-vn", "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k", dst]
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.remove(src)

    if result.returncode != 0:
        os.remove(dst)
        msg = (result.stderr.strip().splitlines() or ["Conversion failed"])[-1]
        return jsonify(error=msg), 500

    out_name = os.path.basename(dst)
    return jsonify(name=out_name, size=os.path.getsize(dst))


@app.get("/download/<sid>/<path:name>")
def download_one(sid, name):
    sid = safe_id(sid)
    path = os.path.join(WORK_DIR, sid, "mp3", os.path.basename(name))
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=os.path.basename(name))


@app.get("/download-all/<sid>")
def download_all(sid):
    sid = safe_id(sid)
    out_dir = os.path.join(WORK_DIR, sid, "mp3")
    files = sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []
    if not files:
        abort(404)
    zip_path = os.path.join(WORK_DIR, sid, "converted_mp3s.zip")
    # MP3 is already compressed, so store without recompressing (much faster)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for fn in files:
            z.write(os.path.join(out_dir, fn), fn)
    return send_file(zip_path, as_attachment=True, download_name="converted_mp3s.zip")


@app.post("/clear/<sid>")
def clear(sid):
    sid = safe_id(sid)
    shutil.rmtree(os.path.join(WORK_DIR, sid), ignore_errors=True)
    return jsonify(ok=True)


@app.get("/")
def index():
    return PAGE


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WAV to MP3</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg:#0f0f11; --card:#18181b; --line:#27272c; --soft:#202024;
    --text:#f2f2f4; --muted:#8e8e96; --accent:#8b8bff; --accent-soft:#25254a;
    --ok:#4ccf8f; --ok-soft:#163326; --err:#ff6b81; --err-soft:#3a1a21;
    --shadow:none; color-scheme:dark;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:15px/1.5 Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
         -webkit-font-smoothing:antialiased; }
  .wrap { max-width:620px; margin:56px auto; padding:0 20px; }
  header { margin-bottom:20px; }
  h1 { font-size:22px; font-weight:650; letter-spacing:-.02em; margin:0; }
  .sub { color:var(--muted); font-size:14px; margin:2px 0 0; }

  .card { background:var(--card); border:1px solid var(--line); border-radius:16px;
          box-shadow:var(--shadow); overflow:hidden; }

  #drop { margin:16px; border:1.5px dashed var(--line); border-radius:12px;
          padding:36px 20px; text-align:center; cursor:pointer; transition:.15s; }
  #drop:hover, #drop.over { border-color:var(--accent); background:var(--accent-soft); }
  #drop svg { color:var(--accent); margin-bottom:8px; }
  #drop .big { font-weight:550; }
  #drop .small { color:var(--muted); font-size:13px; margin-top:2px; }

  .controls { display:flex; align-items:center; justify-content:space-between;
              gap:12px; padding:0 16px 16px; flex-wrap:wrap; }
  .label { color:var(--muted); font-size:13px; margin-right:8px; }
  .seg { display:inline-flex; background:var(--soft); border-radius:9px; padding:3px; }
  .seg button { border:0; background:none; color:var(--muted); font:inherit; font-size:13px;
                padding:5px 11px; border-radius:7px; cursor:pointer; }
  .seg button.on { background:var(--card); color:var(--text); font-weight:550;
                   box-shadow:0 1px 2px rgba(0,0,0,.08); }
  #summary { color:var(--muted); font-size:13px; }

  #list { list-style:none; margin:0; padding:0; border-top:1px solid var(--line); }
  #list:empty { display:none; }
  #list li { display:flex; align-items:center; gap:12px; padding:12px 16px;
             border-bottom:1px solid var(--line); position:relative; }
  #list li:last-child { border-bottom:0; }
  .icon { width:34px; height:34px; border-radius:9px; background:var(--soft); color:var(--muted);
          display:grid; place-items:center; flex-shrink:0; font-size:10px; font-weight:700; letter-spacing:.04em; }
  .done .icon { background:var(--accent-soft); color:var(--accent); }
  .meta { flex:1; min-width:0; }
  .name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; }
  .status { font-size:12px; color:var(--muted); }
  .status.err { color:var(--err); }
  .pill { font-size:12px; font-weight:550; padding:3px 9px; border-radius:99px; white-space:nowrap; }
  .pill.ok { background:var(--ok-soft); color:var(--ok); }
  .pill.err { background:var(--err-soft); color:var(--err); }
  .dl { color:var(--muted); display:grid; place-items:center; width:30px; height:30px;
        border-radius:8px; text-decoration:none; }
  .dl:hover { background:var(--soft); color:var(--accent); }
  .track { position:absolute; left:0; bottom:-1px; height:2px; background:var(--accent);
           width:0; transition:width .2s; }
  .track.busy { width:100%; animation:pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity:.3; } }

  footer { display:flex; justify-content:flex-end; gap:8px; padding:12px 16px;
           border-top:1px solid var(--line); background:var(--soft); }
  footer.hidden { display:none; }
  .btn { font:inherit; font-size:14px; border-radius:9px; padding:8px 16px; cursor:pointer;
         border:1px solid var(--line); background:var(--card); color:var(--text); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:#0f0f11; font-weight:550; }
  .btn:disabled { opacity:.45; cursor:not-allowed; }
  .note { text-align:center; color:var(--muted); font-size:12px; margin-top:16px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>WAV to MP3</h1>
    <p class="sub">Convert as many files as you want.</p>
  </header>

  <div class="card">
    <div id="drop">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/></svg>
      <div class="big">Drop WAV files here</div>
      <div class="small">or click to browse</div>
      <input id="picker" type="file" accept=".wav,audio/wav,audio/x-wav" multiple hidden>
    </div>

    <div class="controls">
      <div>
        <span class="label">Quality</span>
        <div class="seg" id="seg">
          <button data-v="128">128</button>
          <button data-v="192" class="on">192</button>
          <button data-v="256">256</button>
          <button data-v="320">320</button>
        </div>
        <span class="label" style="margin-left:6px">kbps</span>
      </div>
      <span id="summary"></span>
    </div>

    <ul id="list"></ul>

    <footer id="footer" class="hidden">
      <button id="clearBtn" class="btn">Clear</button>
      <button id="allBtn" class="btn primary" disabled>Download all</button>
    </footer>
  </div>

  <p class="note">Files stay on your computer and are deleted when you close the app.</p>
</div>

<script>
const newId = () => crypto.randomUUID ? crypto.randomUUID()
  : Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2,'0')).join('');
let session = newId();
let bitrate = '192';
const queue = [];
let active = 0, done = 0, failed = 0, total = 0;
const PARALLEL = 3;

const $ = id => document.getElementById(id);
const drop = $('drop'), picker = $('picker'), list = $('list'), allBtn = $('allBtn'),
      summary = $('summary'), footer = $('footer');

$('seg').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  [...$('seg').children].forEach(x => x.classList.toggle('on', x === b));
  bitrate = b.dataset.v;
};

drop.onclick = () => picker.click();
picker.onchange = () => { addFiles(picker.files); picker.value = ''; };
['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => addFiles(ev.dataTransfer.files));

const fmtSize = b => b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.max(1,Math.round(b/1024))+' KB';
const DL_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg>';

function row(fileName){
  const li = document.createElement('li');
  li.innerHTML = `<div class="icon">WAV</div>
    <div class="meta"><div class="name"></div><div class="status"></div></div>
    <div class="track"></div>`;
  li.querySelector('.name').textContent = fileName;
  list.appendChild(li);
  return li;
}

function addFiles(files){
  for (const file of files){
    const li = row(file.name);
    const status = li.querySelector('.status');
    if (!file.name.toLowerCase().endsWith('.wav')){
      status.textContent = 'Skipped, not a .wav file'; status.classList.add('err'); continue;
    }
    status.textContent = 'Waiting';
    total++; queue.push({file, li});
  }
  update(); pump();
}

function pump(){ while (active < PARALLEL && queue.length){ active++; upload(queue.shift()); } }

function upload({file, li}){
  const status = li.querySelector('.status'), track = li.querySelector('.track');
  const fd = new FormData();
  fd.append('session', session); fd.append('bitrate', bitrate); fd.append('file', file);
  status.textContent = 'Uploading';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/convert');
  xhr.upload.onprogress = e => { if (e.lengthComputable) track.style.width = (e.loaded/e.total*100)+'%'; };
  xhr.upload.onload = () => { track.classList.add('busy'); status.textContent = 'Converting'; };
  xhr.onload = () => {
    track.remove();
    let data = {}; try { data = JSON.parse(xhr.responseText); } catch(e){}
    if (xhr.status === 200){
      done++;
      li.classList.add('done');
      li.querySelector('.icon').textContent = 'MP3';
      li.querySelector('.name').textContent = data.name;
      status.textContent = fmtSize(data.size) + ' · ' + bitrate + ' kbps';
      const a = document.createElement('a');
      a.className = 'dl'; a.title = 'Download'; a.innerHTML = DL_ICON;
      a.href = `/download/${session}/${encodeURIComponent(data.name)}`;
      li.appendChild(a);
    } else {
      failed++;
      status.textContent = data.error || ('Error ' + xhr.status); status.classList.add('err');
      li.insertAdjacentHTML('beforeend', '<span class="pill err">Failed</span>');
    }
    finish();
  };
  xhr.onerror = () => { track.remove(); failed++; status.textContent = 'Connection error'; status.classList.add('err'); finish(); };
  xhr.send(fd);
}

function finish(){ active--; update(); pump(); }

function update(){
  const pending = total - done - failed;
  summary.textContent = !total ? '' : (pending ? `${done} of ${total} converted` : `All done · ${done} converted`)
    + (failed ? `, ${failed} failed` : '');
  allBtn.disabled = done === 0;
  allBtn.textContent = done > 1 ? `Download all (${done})` : 'Download all';
  footer.classList.toggle('hidden', list.children.length === 0);
}

allBtn.onclick = () => { window.location = `/download-all/${session}`; };

$('clearBtn').onclick = async () => {
  if (active || queue.length){ if (!confirm('Files are still converting. Clear anyway?')) return; queue.length = 0; }
  await fetch(`/clear/${session}`, {method:'POST'});
  session = newId();
  list.innerHTML = ''; done = failed = total = 0; update();
};
</script>
</body>
</html>"""


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
    print(f"WAV -> MP3 converter running at {url}  (Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        app.run(host="127.0.0.1", port=5000, threaded=True)
    finally:
        shutil.rmtree(WORK_DIR, ignore_errors=True)

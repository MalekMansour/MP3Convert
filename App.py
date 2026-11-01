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
  :root { --bg:#111214; --card:#1b1d21; --line:#2c2f35; --text:#e8e8ea;
          --muted:#8b8f98; --accent:#7c5cff; --ok:#3ecf8e; --err:#ff5c7a; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); }
  .wrap { max-width:760px; margin:40px auto; padding:0 20px; }
  h1 { font-size:24px; margin:0 0 4px; }
  .sub { color:var(--muted); margin:0 0 24px; font-size:14px; }
  #drop { border:2px dashed var(--line); border-radius:14px; padding:44px 20px;
          text-align:center; cursor:pointer; background:var(--card); transition:.15s; }
  #drop.over { border-color:var(--accent); background:#221f33; }
  #drop strong { color:var(--accent); }
  .bar { display:flex; gap:10px; align-items:center; margin:18px 0; flex-wrap:wrap; }
  .bar .spacer { flex:1; }
  select, button { font:inherit; color:var(--text); background:var(--card);
                   border:1px solid var(--line); border-radius:8px; padding:8px 14px; }
  button { cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); font-weight:600; }
  button:disabled { opacity:.4; cursor:not-allowed; }
  #summary { color:var(--muted); font-size:14px; }
  ul { list-style:none; padding:0; margin:0; }
  li { display:flex; align-items:center; gap:12px; background:var(--card);
       border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin-bottom:8px; }
  .name { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .status { font-size:13px; color:var(--muted); white-space:nowrap; }
  .status.ok { color:var(--ok); } .status.err { color:var(--err); }
  li a { color:var(--accent); text-decoration:none; font-size:13px; font-weight:600; }
  progress { width:90px; height:6px; accent-color:var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <h1>WAV &rarr; MP3 Converter</h1>
  <p class="sub">Drop in as many .wav files as you like. Everything runs on your own computer.</p>

  <div id="drop">
    <div style="font-size:34px">&#127925;</div>
    <p>Drag &amp; drop WAV files here, or <strong>click to browse</strong></p>
    <input id="picker" type="file" accept=".wav,audio/wav,audio/x-wav" multiple hidden>
  </div>

  <div class="bar">
    <label for="bitrate">Quality</label>
    <select id="bitrate">
      <option value="128">128 kbps</option>
      <option value="192" selected>192 kbps</option>
      <option value="256">256 kbps</option>
      <option value="320">320 kbps (best)</option>
    </select>
    <span id="summary"></span>
    <span class="spacer"></span>
    <button id="clearBtn">Clear</button>
    <button id="allBtn" class="primary" disabled>Download all (.zip)</button>
  </div>

  <ul id="list"></ul>
</div>

<script>
let session = crypto.randomUUID ? crypto.randomUUID()
  : ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g,c=>(c^crypto.getRandomValues(new Uint8Array(1))[0]&15>>c/4).toString(16));
const queue = [];
let active = 0, done = 0, failed = 0, total = 0;
const PARALLEL = 3;

const drop = document.getElementById('drop');
const picker = document.getElementById('picker');
const list = document.getElementById('list');
const allBtn = document.getElementById('allBtn');
const summary = document.getElementById('summary');

drop.onclick = () => picker.click();
picker.onchange = () => { addFiles(picker.files); picker.value = ''; };
['dragenter','dragover'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('over'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', ev => addFiles(ev.dataTransfer.files));

function fmtSize(b){ return b > 1048576 ? (b/1048576).toFixed(1)+' MB' : Math.max(1,Math.round(b/1024))+' KB'; }

function addFiles(files){
  for (const file of files){
    const li = document.createElement('li');
    const name = document.createElement('span'); name.className='name'; name.textContent=file.name;
    const status = document.createElement('span'); status.className='status';
    li.append(name, status); list.appendChild(li);
    if (!file.name.toLowerCase().endsWith('.wav')){
      status.textContent='Skipped (not .wav)'; status.classList.add('err'); continue;
    }
    status.textContent='Waiting...';
    total++; queue.push({file, li, status});
  }
  update(); pump();
}

function pump(){
  while (active < PARALLEL && queue.length){ active++; upload(queue.shift()); }
}

function upload({file, li, status}){
  const fd = new FormData();
  fd.append('session', session);
  fd.append('bitrate', document.getElementById('bitrate').value);
  fd.append('file', file);
  const prog = document.createElement('progress'); prog.max = 100; prog.value = 0;
  status.textContent = 'Uploading'; li.insertBefore(prog, status);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/convert');
  xhr.upload.onprogress = e => { if (e.lengthComputable) prog.value = e.loaded/e.total*100; };
  xhr.upload.onload = () => { prog.removeAttribute('value'); status.textContent = 'Converting...'; };
  xhr.onload = () => {
    prog.remove();
    let data = {}; try { data = JSON.parse(xhr.responseText); } catch(e){}
    if (xhr.status === 200){
      done++; status.textContent = fmtSize(data.size); status.classList.add('ok');
      const a = document.createElement('a');
      a.href = `/download/${session}/${encodeURIComponent(data.name)}`; a.textContent = 'Download';
      li.querySelector('.name').textContent = data.name; li.appendChild(a);
    } else {
      failed++; status.textContent = 'Failed: ' + (data.error || xhr.status); status.classList.add('err');
    }
    finish();
  };
  xhr.onerror = () => { prog.remove(); failed++; status.textContent='Failed: connection error'; status.classList.add('err'); finish(); };
  xhr.send(fd);
}

function finish(){ active--; update(); pump(); }

function update(){
  const pending = total - done - failed;
  summary.textContent = total ? `${done}/${total} converted` + (failed ? `, ${failed} failed` : '') + (pending ? ` · ${pending} in progress` : '') : '';
  allBtn.disabled = done === 0;
}

allBtn.onclick = () => { window.location = `/download-all/${session}`; };

document.getElementById('clearBtn').onclick = async () => {
  if (active || queue.length){ if(!confirm('Files are still converting. Clear anyway?')) return; queue.length = 0; }
  await fetch(`/clear/${session}`, {method:'POST'});
  session = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + 'a0b1c2d3';
  list.innerHTML=''; done = failed = total = 0; update();
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

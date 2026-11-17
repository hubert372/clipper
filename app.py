"""Clipper - obserwuje streamy Twitch, wykrywa skoki czatu i wycina pionowe klipy z napisami.

Uruchom:  python app.py   (panel otworzy sie pod http://127.0.0.1:8765)
Wymaga:   Python 3.10+, ffmpeg w PATH, pip install -r requirements.txt
"""
import json
import mimetypes
import os
import queue
import random
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
REC = DATA / "recordings"
CLIPS = DATA / "clips"
CFG = DATA / "config.json"
CLIPS_DB = DATA / "clips.json"
HOST, PORT = "127.0.0.1", 8765
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULTS = {
    "bucket_sec": 10,        # co ile sekund liczymy wiadomosci
    "window_buckets": 30,    # z ilu ostatnich okien liczymy srednia (30 x 10 s = 5 min)
    "multiplier": 3.0,       # skok = tyle razy wiecej wiadomosci niz srednia
    "min_msgs": 15,          # minimum wiadomosci w oknie, zeby uznac skok
    "cooldown_sec": 90,      # przerwa miedzy klipami z jednego kanalu
    "pre_sec": 22,           # ile sekund PRZED skokiem trafia do klipu
    "post_sec": 8,           # ile sekund PO skoku
    "quality": "720p60,720p,best",
    "layout": "blur",        # blur = caly kadr na rozmytym tle, crop = przyciecie do srodka
    "captions": True,
    "whisper_model": "small",
    "language": "",          # puste = wykryj automatycznie (np. "pl", "en")
    "auto_clip": True,
    "keep_recordings": False,
}


def which(name):
    local = BASE / (name + (".exe" if os.name == "nt" else ""))
    return str(local) if local.exists() else shutil.which(name)


def run(cmd, cwd=None, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW)


def probe_duration(path):
    """Dlugosc (w sekundach) pliku, ktory wciaz sie nagrywa."""
    fp = which("ffprobe")
    if not fp:
        return None
    try:
        r = run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return None


def parse_channel(text):
    text = (text or "").strip().lower()
    m = re.search(r"twitch\.tv/([a-z0-9_]{2,25})", text)
    if m:
        return m.group(1)
    return text if re.fullmatch(r"[a-z0-9_]{2,25}", text) else None


# ---------------------------------------------------------------- napisy
_whisper = {"model": None, "name": None}
_whisper_lock = threading.Lock()


def whisper_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def transcribe(path, model_name, language):
    """Zwraca liste slow: [(start, end, tekst), ...]."""
    from faster_whisper import WhisperModel
    with _whisper_lock:
        if _whisper["name"] != model_name:
            try:
                model = WhisperModel(model_name, device="auto", compute_type="auto")
            except Exception:
                model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _whisper.update(model=model, name=model_name)

        def go():
            segs, _ = _whisper["model"].transcribe(str(path), language=language or None,
                                                   word_timestamps=True, vad_filter=True)
            return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]
        try:
            return go()
        except Exception:
            # typowy problem: brak bibliotek CUDA - przelacz na procesor
            _whisper.update(model=WhisperModel(model_name, device="cpu", compute_type="int8"))
            return go()


def ass_time(t):
    t = max(0.0, t)
    return "%d:%02d:%05.2f" % (t // 3600, (t % 3600) // 60, t % 60)


def build_ass(words, layout):
    margin_v = 430 if layout == "blur" else 330
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Cap,Arial,92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,2,60,60,%d,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" % margin_v
    )
    lines = []
    for i in range(0, len(words), 3):           # po 3 slowa na ekranie
        group = words[i:i + 3]
        for j, (start, end, _) in enumerate(group):
            stop = group[j + 1][0] if j + 1 < len(group) else min(end + 0.25, group[-1][1] + 0.6)
            if i + 3 < len(words) and j + 1 == len(group):
                stop = min(stop, words[i + 3][0])
            if stop <= start:
                stop = start + 0.15
            parts = []
            for k, (_, _, txt) in enumerate(group):
                txt = txt.upper().replace("{", "(").replace("}", ")").replace("\\", "")
                parts.append("{\\c&H00E6FF&}%s{\\c&HFFFFFF&}" % txt if k == j else txt)  # aktualne slowo na zolto
            lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,%s" % (ass_time(start), ass_time(stop), " ".join(parts)))
    return head + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- kanal
class Channel:
    def __init__(self, app, name, enabled=True):
        self.app, self.name, self.enabled = app, name, enabled
        self.state = "stopped"          # stopped | waiting | live
        self.chat_ok = False
        self.chat_err = False
        self.hist = deque(maxlen=60)    # wiadomosci na okno
        self.cur = 0
        self.thr = None
        self.bucket_end = 0.0
        self.last_clip = 0.0
        self.rec_path = None
        self.live_since = None
        self.proc = None
        self.gen = 0

    def _alive(self, g):
        return self.enabled and self.gen == g and not self.app.stopping

    def start(self):
        self.enabled = True
        self.gen += 1
        self.state = "waiting"
        threading.Thread(target=self._chat, args=(self.gen,), daemon=True).start()
        threading.Thread(target=self._record, args=(self.gen,), daemon=True).start()

    def stop(self):
        self.enabled = False
        self.gen += 1
        self.state = "stopped"
        p = self.proc
        if p and p.poll() is None:
            p.terminate()

    # --- czat: anonimowe polaczenie tylko do odczytu, bez logowania
    def _chat(self, g):
        while self._alive(g):
            s = None
            try:
                raw = socket.create_connection(("irc.chat.twitch.tv", 6697), timeout=10)
                s = ssl.create_default_context().wrap_socket(raw, server_hostname="irc.chat.twitch.tv")
                s.sendall(("NICK justinfan%d\r\nJOIN #%s\r\n" % (random.randint(10000, 99999), self.name)).encode())
                s.settimeout(1.0)
                self.chat_ok, self.chat_err = True, False
                buf = b""
                while self._alive(g):
                    self._tick()
                    try:
                        data = s.recv(8192)
                    except (socket.timeout, TimeoutError):
                        continue
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split(b"\r\n")
                    for ln in lines:
                        if ln.startswith(b"PING"):
                            s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        elif b" PRIVMSG #" in ln:
                            self.cur += 1
            except Exception as e:
                if self._alive(g) and not self.chat_err:
                    self.chat_err = True
                    self.app.log("%s: brak polaczenia z czatem (%s), ponawiam w tle" % (self.name, e))
            finally:
                self.chat_ok = False
                try:
                    s and s.close()
                except Exception:
                    pass
            for _ in range(10):
                if not self._alive(g):
                    return
                self._tick()
                time.sleep(1)

    def _tick(self):
        now = time.time()
        step = self.app.settings["bucket_sec"]
        if not self.bucket_end or now - self.bucket_end > step * 3:
            self.bucket_end = now + step
            self.cur = 0
            return
        if now >= self.bucket_end:
            count, self.cur = self.cur, 0
            self.bucket_end += step
            self.close_bucket(count)

    def close_bucket(self, count):
        s = self.app.settings
        base = list(self.hist)[-int(s["window_buckets"]):]
        self.hist.append(count)
        self.thr = max(s["min_msgs"], sum(base) / len(base) * s["multiplier"]) if len(base) >= 6 else None
        if (self.thr and count >= self.thr and s["auto_clip"] and self.state == "live"
                and time.time() - self.last_clip >= s["cooldown_sec"]):
            self.trigger("skok czatu", count)

    def trigger(self, reason, peak=0):
        if self.state != "live" or not self.rec_path:
            return None
        s = self.app.settings
        path = self.rec_path
        pos = probe_duration(path)
        if pos is None:
            pos = time.time() - (self.live_since or time.time())
        start = max(0.0, pos - s["pre_sec"])
        clip = {"id": uuid.uuid4().hex[:10], "channel": self.name, "created": time.time(), "reason": reason,
                "peak": peak, "status": "pending", "file": None, "text": "",
                "start": round(start, 2), "dur": round(pos - start + s["post_sec"], 2)}
        self.last_clip = time.time()
        self.app.add_clip(clip, path)
        self.app.log("%s: %s (%s wiad.) - klip za %d s" % (self.name, reason, peak, s["post_sec"]))
        threading.Timer(s["post_sec"] + 3, lambda: self.app.jobs.put((clip, path))).start()
        return clip

    # --- nagrywanie: streamlink sam czeka, az kanal wejdzie na zywo
    def _record(self, g):
        while self._alive(g):
            path = REC / ("%s_%s.ts" % (self.name, time.strftime("%Y%m%d_%H%M%S")))
            cmd = [sys.executable, "-m", "streamlink", "--retry-streams", "30", "--retry-open", "3", "--force",
                   "-o", str(path), "https://twitch.tv/" + self.name, self.app.settings["quality"]]
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=NO_WINDOW)
            except Exception as e:
                self.app.log("%s: nie moge uruchomic streamlink (%s)" % (self.name, e))
                time.sleep(15)
                continue
            while self.proc.poll() is None:
                if not self._alive(g):
                    self.proc.terminate()
                    break
                if self.state != "live" and path.exists() and path.stat().st_size > 200_000:
                    self.state, self.rec_path, self.live_since = "live", path, time.time()
                    self.app.log("%s: NA ZYWO - nagrywam" % self.name)
                time.sleep(1)
            if self.rec_path == path:
                self.app.log("%s: stream zakonczony" % self.name)
            self.rec_path, self.live_since = None, None
            if self.enabled and self.gen == g:
                self.state = "waiting"
            self.app.finish_recording(path)
            for _ in range(10):
                if not self._alive(g):
                    return
                time.sleep(1)

    def info(self):
        size = 0
        try:
            size = self.rec_path.stat().st_size if self.rec_path else 0
        except OSError:
            pass
        return {"name": self.name, "enabled": self.enabled, "state": self.state, "chat": self.chat_ok,
                "hist": list(self.hist)[-30:], "cur": self.cur, "thr": self.thr,
                "live_since": self.live_since, "rec_mb": round(size / 1e6)}


# ---------------------------------------------------------------- aplikacja
class App:
    def __init__(self):
        for d in (REC, CLIPS):
            d.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stopping = False
        self.logs = deque(maxlen=80)
        self.jobs = queue.Queue()
        self.refs = {}       # nagranie -> liczba klipow, ktore jeszcze z niego korzystaja
        self.done = set()    # nagrania zakonczone
        cfg = {}
        if CFG.exists():
            try:
                cfg = json.loads(CFG.read_text("utf-8"))
            except Exception:
                pass
        self.settings = {**DEFAULTS, **{k: v for k, v in cfg.get("settings", {}).items() if k in DEFAULTS}}
        self.clips = []
        if CLIPS_DB.exists():
            try:
                self.clips = [c for c in json.loads(CLIPS_DB.read_text("utf-8")) if c.get("status") == "ready"]
            except Exception:
                pass
        self.channels = {}
        for c in cfg.get("channels", []):
            self.channels[c["name"]] = Channel(self, c["name"], c.get("enabled", True))

    def start(self):
        threading.Thread(target=self._worker, daemon=True).start()
        for ch in self.channels.values():
            if ch.enabled:
                ch.start()

    def log(self, msg):
        self.logs.append([time.time(), msg])
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    def save(self):
        with self.lock:
            CFG.write_text(json.dumps({"settings": self.settings, "channels": [
                {"name": c.name, "enabled": c.enabled} for c in self.channels.values()]}, indent=2), "utf-8")
            CLIPS_DB.write_text(json.dumps(self.clips, indent=1), "utf-8")

    def add_clip(self, clip, rec):
        with self.lock:
            self.clips.insert(0, clip)
            self.refs[rec] = self.refs.get(rec, 0) + 1

    def finish_recording(self, path):
        with self.lock:
            self.done.add(path)
        self._cleanup(path)

    def _cleanup(self, path):
        with self.lock:
            if path in self.done and not self.refs.get(path) and not self.settings["keep_recordings"]:
                self.done.discard(path)
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _worker(self):
        while True:
            clip, rec = self.jobs.get()
            try:
                clip["status"] = "processing"
                self.make_clip(clip, rec)
                clip["status"] = "ready"
                self.log("%s: klip gotowy (%s)" % (clip["channel"], clip["file"]))
            except Exception as e:
                clip["status"] = "error"
                clip["error"] = str(e)[-300:]
                self.log("%s: blad klipu - %s" % (clip["channel"], str(e)[-200:]))
            finally:
                with self.lock:
                    self.refs[rec] = self.refs.get(rec, 1) - 1
                self._cleanup(rec)
                self.save()

    def make_clip(self, clip, rec):
        ff = which("ffmpeg")
        if not ff:
            raise RuntimeError("brak ffmpeg - zainstaluj: winget install Gyan.FFmpeg")
        s = self.settings
        cid = clip["id"]
        raw, sub = cid + "_raw.ts", cid + ".ass"
        out = "%s_%s_%s.mp4" % (clip["channel"], time.strftime("%m%d_%H%M%S", time.localtime(clip["created"])), cid)
        try:
            r = run([ff, "-y", "-v", "error", "-ss", str(clip["start"]), "-i", str(rec), "-t", str(clip["dur"]),
                     "-c", "copy", raw], cwd=CLIPS)
            if r.returncode or not (CLIPS / raw).exists() or (CLIPS / raw).stat().st_size < 10_000:
                raise RuntimeError("wycinanie nie powiodlo sie: " + r.stderr[-200:])
            has_sub = False
            if s["captions"] and whisper_available():
                try:
                    words = transcribe(CLIPS / raw, s["whisper_model"], s["language"])
                    if words:
                        (CLIPS / sub).write_text(build_ass(words, s["layout"]), "utf-8")
                        clip["text"] = " ".join(w[2] for w in words)[:160]
                        has_sub = True
                except Exception as e:
                    self.log("%s: napisy pominiete (%s)" % (clip["channel"], str(e)[-150:]))
            if s["layout"] == "crop":
                vf = "[0:v]scale=-2:1920,crop=1080:1920,setsar=1[v]"
            else:
                vf = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                      "boxblur=24:4[bg];[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
            if has_sub:
                vf += ";[v]subtitles=%s[o]" % sub
            r = run([ff, "-y", "-v", "error", "-i", raw, "-filter_complex", vf, "-map", "[o]" if has_sub else "[v]",
                     "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out], cwd=CLIPS)
            if r.returncode or not (CLIPS / out).exists():
                raise RuntimeError("render nie powiodl sie: " + r.stderr[-200:])
            clip["file"] = out
        finally:
            for f in (raw, sub):
                try:
                    (CLIPS / f).unlink(missing_ok=True)
                except OSError:
                    pass

    def state(self):
        with self.lock:
            return {
                "channels": [c.info() for c in self.channels.values()],
                "clips": self.clips[:200],
                "settings": self.settings,
                "logs": list(self.logs)[-40:],
                "deps": {"ffmpeg": bool(which("ffmpeg") and which("ffprobe")), "whisper": whisper_available()},
                "now": time.time(),
            }

    # --- akcje z panelu
    def api(self, path, body):
        if path == "/api/channels/add":
            name = parse_channel(body.get("name"))
            if not name:
                return {"error": "Podaj nazwe kanalu albo link twitch.tv/..."}
            if name not in self.channels:
                self.channels[name] = Channel(self, name)
                self.channels[name].start()
                self.log("%s: dodano kanal" % name)
        elif path == "/api/channels/remove":
            ch = self.channels.pop(body.get("name"), None)
            if ch:
                ch.stop()
        elif path == "/api/channels/toggle":
            ch = self.channels.get(body.get("name"))
            if ch:
                ch.start() if body.get("enabled") else ch.stop()
        elif path == "/api/clip":
            ch = self.channels.get(body.get("name"))
            if not ch or not ch.trigger("recznie"):
                return {"error": "Kanal nie jest teraz na zywo"}
        elif path == "/api/clips/delete":
            with self.lock:
                for c in [c for c in self.clips if c["id"] == body.get("id")]:
                    if c["status"] in ("ready", "error"):
                        self.clips.remove(c)
                        if c.get("file"):
                            (CLIPS / c["file"]).unlink(missing_ok=True)
        elif path == "/api/settings":
            for k, v in body.items():
                if k in DEFAULTS:
                    d = DEFAULTS[k]
                    try:
                        self.settings[k] = bool(v) if isinstance(d, bool) else type(d)(v)
                    except (TypeError, ValueError):
                        pass
            for k in ("bucket_sec", "window_buckets", "pre_sec", "post_sec"):
                self.settings[k] = max(1, self.settings[k])
        else:
            return {"error": "nieznana akcja"}
        self.save()
        return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._send(200, (BASE / "panel.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, self.app.state())
        if path.startswith("/clips/"):
            name = os.path.basename(path)
            f = CLIPS / name
            if not re.fullmatch(r"[\w.-]+\.mp4", name) or not f.is_file():
                return self._send(404, {"error": "brak pliku"})
            return self._file(f)
        self._send(404, {"error": "nie znaleziono"})

    def _file(self, f):
        size = f.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                return self._send(416, {"error": "zakres"})
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        try:
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(262144, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionError):
            pass

    def do_POST(self):
        # panel dziala tylko lokalnie - odrzucamy zadania z obcych stron
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://%s:%d" % (HOST, PORT), "http://localhost:%d" % PORT):
            return self._send(403, {"error": "zabronione"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except Exception:
            return self._send(400, {"error": "zly format"})
        res = self.app.api(self.path.split("?")[0], body)
        self._send(400 if "error" in res else 200, res)


def main():
    app = App()
    Handler.app = app
    try:
        import streamlink  # noqa: F401
    except Exception:
        app.log("UWAGA: brak streamlink - uruchom: pip install -r requirements.txt")
    if not which("ffmpeg"):
        app.log("UWAGA: brak ffmpeg - zainstaluj: winget install Gyan.FFmpeg")
    app.start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d" % (HOST, PORT)
    app.log("Panel: " + url)
    if "--no-browser" not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stopping = True
        for ch in app.channels.values():
            ch.stop()
        app.save()


if __name__ == "__main__":
    main()

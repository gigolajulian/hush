"""Hush: mutes Discord while the Claude app is capturing the mic, unmutes only if it muted.

Signal: WASAPI capture session of claude.exe goes ACTIVE while dictating.
Action: Discord local RPC (GET/SET_VOICE_SETTINGS), so the real mute state is read first.
"""
import io, json, os, shutil, struct, subprocess, sys, threading, time, uuid, urllib.parse, urllib.request, zipfile
from pathlib import Path

import winreg

import comtypes, psutil, pystray
from comtypes import CLSCTX_ALL
from PIL import Image, ImageDraw, ImageFont
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.constants import CLSID_MMDeviceEnumerator
from pycaw.pycaw import IAudioSessionControl2, IAudioSessionManager2

VERSION = "1.1.2"
REPO = "gigolajulian/hush"
APP_DIR = Path(__file__).resolve().parent
UPDATE_EVERY = 24 * 3600
POLL = 0.25
RELEASE_POLLS = 2  # inactive this many polls in a row before unmuting
STATE_DIR = Path(os.environ["LOCALAPPDATA"]) / "Hush"
TOKEN_FILE = STATE_DIR / "token.json"
LOG_FILE = STATE_DIR / "hush.log"
SETTINGS_FILE = STATE_DIR / "settings.json"


def env(name):
    """Env var, falling back to the user registry so vars set after login work without a restart."""
    if os.environ.get(name): return os.environ[name]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k: return winreg.QueryValueEx(k, name)[0]
    except OSError: return None


def log(msg):
    STATE_DIR.mkdir(exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


# ---------- signal ----------
class ClaudeMic:
    def __init__(self):
        comtypes.CoInitialize()
        self.enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        self.mgrs, self.mgrs_at, self.names = [], 0, {}

    def _managers(self):
        if time.time() - self.mgrs_at > 10:  # pick up new/unplugged mics
            coll = self.enum.EnumAudioEndpoints(1, 1)  # eCapture, ACTIVE
            self.mgrs = [coll.Item(i).Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
                         for i in range(coll.GetCount())]
            self.mgrs_at = time.time()
        return self.mgrs

    def _name(self, pid):
        if pid not in self.names:
            try: self.names[pid] = psutil.Process(pid).name().lower()
            except Exception: return ""
        return self.names[pid]

    def active(self):
        try:
            for mgr in self._managers():
                se = mgr.GetSessionEnumerator()
                for j in range(se.GetCount()):
                    c = se.GetSession(j).QueryInterface(IAudioSessionControl2)
                    if c.GetState() == 1 and self._name(c.GetProcessId()) == "claude.exe":
                        return True
        except Exception as e:
            log(f"wasapi error {e!r}")
            self.mgrs_at = 0
        return False


# ---------- discord rpc ----------
class Discord:
    SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]

    def __init__(self):
        self.pipe = None

    def _send(self, op, payload):
        data = json.dumps(payload).encode()
        self.pipe.write(struct.pack("<ii", op, len(data)) + data)

    def _recv(self):
        op, n = struct.unpack("<ii", self.pipe.read(8))
        return op, json.loads(self.pipe.read(n))

    def _cmd(self, cmd, args=None):
        nonce = str(uuid.uuid4())
        self._send(1, {"cmd": cmd, "args": args or {}, "nonce": nonce})
        while True:
            op, msg = self._recv()
            if op == 2: raise ConnectionError(msg)
            if msg.get("nonce") == nonce:
                if msg.get("evt") == "ERROR": raise RuntimeError(f"{cmd}: {msg['data']}")
                return msg["data"]

    def _token(self, form):
        form.update(client_id=env("DISCORD_CLIENT_ID"), client_secret=env("DISCORD_CLIENT_SECRET"))
        req = urllib.request.Request("https://discord.com/api/oauth2/token", urllib.parse.urlencode(form).encode(),
                                     {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Hush (local, 1.0)"})
        tok = json.loads(urllib.request.urlopen(req, timeout=15).read())
        tok["expires_at"] = time.time() + tok["expires_in"] - 60
        STATE_DIR.mkdir(exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(tok), encoding="utf-8")
        return tok

    def connect(self):
        try:
            self._connect()
        except Exception:
            self.close()  # never leave a half-open pipe behind
            raise

    def _connect(self):
        cid = env("DISCORD_CLIENT_ID")
        if not cid or not env("DISCORD_CLIENT_SECRET"):
            raise RuntimeError("DISCORD_CLIENT_ID / DISCORD_CLIENT_SECRET not set")
        for i in range(10):
            try:
                self.pipe = open(rf"\\.\pipe\discord-ipc-{i}", "r+b", buffering=0)
                break
            except OSError:
                continue
        else:
            raise ConnectionError("Discord not running")
        self._send(0, {"v": 1, "client_id": cid})
        op, msg = self._recv()  # READY, or op 2 CLOSE with a reason
        if op == 2: raise ConnectionError(msg.get("message"))
        tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8")) if TOKEN_FILE.exists() else None
        if tok and tok["expires_at"] < time.time():
            try: tok = self._token({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
            except Exception: tok = None
        if not tok:  # one-time Authorize popup inside Discord
            code = self._cmd("AUTHORIZE", {"client_id": cid, "scopes": self.SCOPES})["code"]
            tok = self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": "http://localhost"})
        try:
            self._cmd("AUTHENTICATE", {"access_token": tok["access_token"]})
        except RuntimeError:
            TOKEN_FILE.unlink(missing_ok=True)  # revoked: re-authorize next connect
            raise
        log("discord connected")

    def close(self):
        if self.pipe:
            try: self.pipe.close()
            except Exception: pass
        self.pipe = None

    def call(self, cmd, args=None):
        if not self.pipe: self.connect()
        try:
            return self._cmd(cmd, args)
        except (OSError, ConnectionError, struct.error):
            self.close()
            raise

    def muted(self): return self.call("GET_VOICE_SETTINGS")["mute"]
    def set_mute(self, v): self.call("SET_VOICE_SETTINGS", {"mute": v})


# ---------- logic ----------
class Muter:
    """Edge logic, kept free of I/O so it can be self-checked."""

    def __init__(self, discord):
        self.d, self.we_muted, self.talking, self.idle_polls = discord, False, False, 0

    def tick(self, mic_active):
        if mic_active:
            self.idle_polls = 0
            if not self.talking:
                self.talking = True
                if not self.d.muted():
                    self.d.set_mute(True)
                    self.we_muted = True
                    log("muted discord")
        elif self.talking:
            self.idle_polls += 1
            if self.idle_polls >= RELEASE_POLLS:
                self.talking = False
                self.release()

    def release(self):
        if self.we_muted:
            self.we_muted = False
            if self.d.muted():  # if the user already unmuted, leave it
                self.d.set_mute(False)
                log("unmuted discord")


# ---------- updates ----------
def load_settings():
    try: return {"auto_update": True, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    except (OSError, ValueError): return {"auto_update": True}


def save_settings(s):
    STATE_DIR.mkdir(exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s), encoding="utf-8")


def vtuple(v):
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3] if x.isdigit())


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": f"Hush/{VERSION}", "Accept": "application/vnd.github+json"})
    for attempt in range(3):  # GitHub answers 5xx while it builds a fresh release zip
        try: return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2: raise
            time.sleep(5)


def latest_release():
    """(tag, zip_url) of the newest GitHub release, or None if there is none."""
    try:
        r = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest"))
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise
    return r["tag_name"], r["zipball_url"]


def newer_release():
    rel = latest_release()
    return rel if rel and vtuple(rel[0]) > vtuple(VERSION) else None


def apply_update(tag, zip_url, app_dir=APP_DIR):
    """Replace the app files with the release. Git checkouts pull instead, so a dev tree is never overwritten."""
    if (app_dir / ".git").exists():
        subprocess.run(["git", "-C", str(app_dir), "pull", "--ff-only", "-q"], check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        with zipfile.ZipFile(io.BytesIO(_get(zip_url, timeout=60))) as z:
            for info in z.infolist():
                rel = Path(*Path(info.filename).parts[1:])  # drop the "owner-repo-sha/" root folder
                if info.is_dir() or not rel.parts: continue
                dest = (app_dir / rel).resolve()
                if app_dir.resolve() not in dest.parents: continue  # refuse paths that escape the app folder
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(dest, "wb") as out: shutil.copyfileobj(src, out)
    py = app_dir / ".venv" / "Scripts" / "python.exe"
    if py.exists():
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                        str(app_dir / "requirements.txt")], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    log(f"updated to {tag}")


def restart():
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    subprocess.Popen([str(pyw), str(APP_DIR / "hush.py")], cwd=str(APP_DIR),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


# ---------- tray ----------
def _draw_icon(on):
    """Dot with a vertical line through it. Only the colors change: grey while watching, cyan while Hush holds a mute."""
    s = 4  # draw at 4x, downsample for smooth edges
    im = Image.new("RGBA", (64 * s, 64 * s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse((8 * s, 8 * s, 56 * s, 56 * s), fill=(0, 200, 220, 255) if on else (120, 122, 126, 255))
    dr.rectangle((26 * s, 0, 38 * s, 64 * s), fill=(0, 0, 0, 0))  # transparent gap around the line
    dr.rounded_rectangle((29 * s, 1 * s, 35 * s, 63 * s), radius=3 * s, fill=(255, 255, 255, 255) if on else (200, 200, 198, 255))
    return im.resize((64, 64), Image.LANCZOS)


ICONS = {True: _draw_icon(True), False: _draw_icon(False)}


def icon_img(on):
    return ICONS[on]


def main():
    state = {"paused": False, "status": "starting", "stop": False, "busy": False, "update": ""}
    settings = load_settings()
    icon = pystray.Icon("hush", icon_img(False), "Hush")

    def loop():
        mic, d = ClaudeMic(), Discord()
        m, retry_at = Muter(d), 0
        while not state["stop"]:
            state["busy"] = m.talking or m.we_muted  # never restart for an update mid-dictation
            try:
                if state["paused"]:
                    state["status"] = "paused"
                elif time.time() >= retry_at:
                    if not d.pipe: d.connect()  # connect up front so the tray shows the real Discord state
                    m.tick(mic.active())
                    state["status"] = "muting Discord" if m.we_muted else "connected to Discord"
            except Exception as e:
                msg = "Discord not running" if "not running" in str(e) else str(e)[:60]
                if state["status"] != msg: log(f"error {e!r}")  # don't spam the log every retry
                state["status"] = msg
                m.talking = m.we_muted and m.talking  # if the mute never landed, retry it on the next active poll
                retry_at = time.time() + 5
            if icon.icon is not icon_img(m.we_muted): icon.icon = icon_img(m.we_muted)  # only touch the tray on change
            if icon.title != f"Hush | {state['status']}": icon.title = f"Hush | {state['status']}"
            time.sleep(POLL)
        try: m.release()
        except Exception: pass

    loop_thread = threading.Thread(target=loop, daemon=True)
    check_lock = threading.Lock()

    def shutdown():
        state["stop"] = True
        loop_thread.join(timeout=3)  # let the loop give back any mute it holds
        icon.stop()

    def check(manual):
        """Look for a newer release and install it. Waits until no dictation is in progress."""
        if not check_lock.acquire(blocking=False): return
        try:
            state["update"] = "checking for updates"
            rel = newer_release()
            if not rel:
                state["update"] = f"up to date ({VERSION})"
                if manual: icon.notify(f"Hush {VERSION} is up to date.", "Hush")
                return
            state["update"] = f"updating to {rel[0]}"
            while state["busy"] and not state["stop"]: time.sleep(1)
            if state["stop"]: return
            apply_update(*rel)
            icon.notify(f"Updated to {rel[0]}. Restarting.", "Hush")
            restart()
            shutdown()
        except Exception as e:
            log(f"update error {e!r}")
            state["update"] = "update check failed"
            if manual: icon.notify("Update check failed. See the log.", "Hush")
        finally:
            check_lock.release()

    def auto_updates():
        time.sleep(30)  # let startup settle
        while not state["stop"]:
            if settings["auto_update"]: check(manual=False)
            for _ in range(UPDATE_EVERY):
                if state["stop"]: return
                time.sleep(1)

    def toggle_pause(_, __): state["paused"] = not state["paused"]

    def toggle_auto(_, __):
        settings["auto_update"] = not settings["auto_update"]
        save_settings(settings)

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _: state["status"], None, enabled=False),
        pystray.MenuItem(lambda _: state["update"] or f"Hush {VERSION}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Pause", toggle_pause, checked=lambda _: state["paused"]),
        pystray.MenuItem("Check for updates", lambda: threading.Thread(target=check, args=(True,), daemon=True).start()),
        pystray.MenuItem("Auto update", toggle_auto, checked=lambda _: settings["auto_update"]),
        pystray.MenuItem("Quit", lambda: shutdown()),
    )
    loop_thread.start()
    threading.Thread(target=auto_updates, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()

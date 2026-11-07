"""Hush: mutes Discord while the Claude app is capturing the mic, unmutes only if it muted.

Signal: WASAPI capture session of claude.exe goes ACTIVE while dictating.
Action: Discord local RPC (GET/SET_VOICE_SETTINGS), so the real mute state is read first.
"""
import json, os, struct, threading, time, uuid, urllib.parse, urllib.request
from pathlib import Path

import winreg

import comtypes, psutil, pystray
from comtypes import CLSCTX_ALL
from PIL import Image, ImageDraw, ImageFont
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.constants import CLSID_MMDeviceEnumerator
from pycaw.pycaw import IAudioSessionControl2, IAudioSessionManager2

POLL = 0.25
RELEASE_POLLS = 2  # inactive this many polls in a row before unmuting
GUARD_PROCS = {"r5apex.exe", "r5apex_dx12.exe", "easyanticheat.exe", "easyanticheat_eos.exe"}
STATE_DIR = Path(os.environ["LOCALAPPDATA"]) / "Hush"
TOKEN_FILE = STATE_DIR / "token.json"
LOG_FILE = STATE_DIR / "hush.log"


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


def guarded():
    return any((p.info["name"] or "").lower() in GUARD_PROCS for p in psutil.process_iter(["name"]))


# ---------- tray ----------
def _draw_icon(on):
    """The h-dot app icon; the dot turns cyan while Hush holds a mute."""
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    try: font = ImageFont.truetype("seguisb.ttf", 72)  # Segoe UI Semibold, ships with Windows
    except OSError: font = ImageFont.load_default()
    x0, y0, x1, y1 = dr.textbbox((0, 0), "h", font=font)
    dr.text((-x0 + 2, 62 - y1), "h", font=font, fill=(232, 232, 230, 255))  # h fills the height, no tile
    w = x1 - x0
    dr.ellipse((w + 5, 47, w + 19, 61), fill=(0, 200, 220, 255) if on else (140, 142, 146, 255))
    return im


ICONS = {True: _draw_icon(True), False: _draw_icon(False)}


def icon_img(on):
    return ICONS[on]


def main():
    state = {"paused": False, "status": "starting", "stop": False}
    icon = pystray.Icon("hush", icon_img(False), "Hush")

    def loop():
        mic, d = ClaudeMic(), Discord()
        m, last_guard, guard, retry_at = Muter(d), 0, False, 0
        while not state["stop"]:
            try:
                if time.time() - last_guard > 2:
                    last_guard, was = time.time(), guard
                    guard = guarded()
                    if guard and not was:
                        log("apex running: idle")
                        try: m.release()
                        except Exception: pass
                        m.talking = False
                        d.close()
                if guard or state["paused"]:
                    state["status"] = "idle: Apex running" if guard else "paused"
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

    def toggle_pause(_, __): state["paused"] = not state["paused"]

    def quit_(i, _):
        state["stop"] = True
        i.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _: state["status"], None, enabled=False),
        pystray.MenuItem("Pause", toggle_pause, checked=lambda _: state["paused"]),
        pystray.MenuItem("Quit", quit_),
    )
    threading.Thread(target=loop, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()

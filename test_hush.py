"""Self-check for the mute/unmute edge logic. Run: .venv\\Scripts\\python test_hush.py"""
import hush

hush.log = lambda msg: None
hush.RELEASE_POLLS = 2  # the sequences below assume the Windows hold; macOS uses a longer one


class FakeDiscord:
    def __init__(self, muted, call=True): self.m, self.calls, self.call = muted, [], call
    def muted(self): return self.m
    def in_call(self): return self.call
    vol = 80
    def input_volume(self): return self.vol
    def set_input_volume(self, v): self.vol = v; self.calls.append(("vol", v))
    def set_mute(self, v): self.m = v; self.calls.append(v)


def run(start_muted, seq, user=None, call=True):
    d = FakeDiscord(start_muted, call)
    m = hush.Muter(d)
    for i, a in enumerate(seq):
        if user and i in user: d.m = user[i]
        m.tick(a)
    return d


# dictate while unmuted: mute, then unmute after 2 idle polls
d = run(False, [1, 1, 0, 0]); assert d.calls == [True, False] and not d.m
# one idle blip does not unmute
d = run(False, [1, 0, 1, 1]); assert d.calls == [True]
# already muted by user: never touched
d = run(True, [1, 1, 0, 0, 0]); assert d.calls == [] and d.m
# user unmutes mid-dictation: helper does not re-touch
d = run(False, [1, 1, 0, 0], user={1: False}); assert d.calls == [True]
# not in a voice call: never touched
d = run(False, [1, 1, 0, 0], call=False); assert d.calls == [] and not d.m

# quiet mute: volume to 0 and back, mute flag never touched
hush.remember_volume = lambda v: None
def run_quiet(seq, user_vol=None):
    d = FakeDiscord(False); m = hush.Muter(d, quiet=lambda: True)
    for i, a in enumerate(seq):
        if user_vol and i in user_vol: d.vol = user_vol[i]
        m.tick(a)
    return d
d = run_quiet([1, 1, 0, 0]); assert d.calls == [("vol", 0), ("vol", 80)] and not d.m
# user moves the slider mid-dictation: helper leaves it
d = run_quiet([1, 1, 0, 0], user_vol={1: 50}); assert d.calls == [("vol", 0)] and d.vol == 50

# version compare
assert hush.vtuple("v1.10.0") > hush.vtuple("1.9.3") and hush.vtuple("v1.1.0") == hush.vtuple("1.1.0")

# zip update: files land in the app folder, path escapes are refused
import io, tempfile, zipfile
from pathlib import Path
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("gigolajulian-hush-abc123/hush.py", "new")
    z.writestr("gigolajulian-hush-abc123/assets/icon.svg", "svg")
    z.writestr("gigolajulian-hush-abc123/../../evil.txt", "x")
hush._get = lambda url, timeout=0: buf.getvalue() if url == "zip" else b"sig"
real_signed = hush.signed
hush.signed = lambda tag, data, sig: tag == "v9.9.9" and data == buf.getvalue() and sig == "sig"
with tempfile.TemporaryDirectory() as t:
    app = Path(t) / "a" / "app"; app.mkdir(parents=True)
    (app / "hush.py").write_text("old")
    for tag, z, s in (("v9.9.8", "zip", "sig"), ("v9.9.9", "zip", None), ("v9.9.9", None, None)):  # bad or no signature
        try: hush.apply_update(tag, z, s, app_dir=app); raise AssertionError("unsigned update installed")
        except RuntimeError as e: assert "not installing" in str(e)
    assert (app / "hush.py").read_text() == "old"
    hush.apply_update("v9.9.9", "zip", "sig", app_dir=app)
    assert (app / "hush.py").read_text() == "new" and (app / "assets" / "icon.svg").exists()
    assert not any(p.name == "evil.txt" for p in Path(t).rglob("*"))
hush.signed = real_signed

# ed25519 verifier: RFC 8032 test 1 (empty message), then tampered inputs
pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
assert hush.ed25519_verify(pk, b"", sig)
assert not hush.ed25519_verify(pk, b"x", sig)
assert not hush.ed25519_verify(pk, b"", sig[:-1] + bytes([sig[-1] ^ 1]))
assert not hush.ed25519_verify(hush.PUBKEY, b"", sig)
assert not hush.signed("v1.0.0", b"zip", "not base64!") and not hush.signed("v1.0.0", b"zip", "")
print("ok")

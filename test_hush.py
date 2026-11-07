"""Self-check for the mute/unmute edge logic. Run: .venv\\Scripts\\python test_hush.py"""
import hush

hush.log = lambda msg: None


class FakeDiscord:
    def __init__(self, muted): self.m, self.calls = muted, []
    def muted(self): return self.m
    def set_mute(self, v): self.m = v; self.calls.append(v)


def run(start_muted, seq, user=None):
    d = FakeDiscord(start_muted)
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
print("ok")

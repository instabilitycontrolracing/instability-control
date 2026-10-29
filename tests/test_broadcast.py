import socket, time, types
import numpy as np
from engineer import broadcast as B, audio_tool


def tone(sr=22050, s=0.5, f=1000):
    t = np.arange(int(sr * s)) / sr
    return (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_fx_louder_and_limited():
    x = tone()
    y = B.broadcast_fx(B._resample(x, 22050), B.RATE, grit=1.0, db=6.0)
    assert np.abs(y).max() <= 1.0
    assert np.sqrt(np.mean(y ** 2)) > np.sqrt(np.mean(x ** 2))


def test_call_has_keyup_and_tail():
    x = tone()
    a = B.build_call(x, 22050, keyup=True)
    b = B.build_call(x, 22050, keyup=False)
    assert len(a) > len(b) + int(0.2 * B.RATE)
    assert np.abs(a[:int(0.05 * B.RATE)]).max() > 0.05      # the click is audible


def test_player_mixes_call_and_crowd():
    p = B.Player(log=lambda m: None)
    p.add_call(tone(), 22050)
    p.add_crowd(np.full((B.RATE // 2, 2), 0.1, np.float32))
    out = np.zeros((1024, 2), np.float32)
    p.render(out)
    assert np.abs(out).max() > 0


def test_exclude_line(tmp_path, monkeypatch):
    f = tmp_path / "apollo_tv.txt"
    monkeypatch.setattr(audio_tool, "STREAM_FILE", str(f))
    am = audio_tool.AudioMix.__new__(audio_tool.AudioMix)
    am._write = lambda path, text: open(path, "w").write(text)
    audio_tool.EXCLUDE_PID = 4242
    try:
        am.write_stream()
        assert "Exclude PID: 4242" in f.read_text()
        audio_tool.EXCLUDE_PID = None
        am.write_stream()
        assert "Exclude" not in f.read_text()
    finally:
        audio_tool.EXCLUDE_PID = None


def test_link_sends_to_player(monkeypatch):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    monkeypatch.setattr(B, "PORT", srv.getsockname()[1])
    monkeypatch.setattr(audio_tool, "EXCLUDE_PID", None)
    s = types.SimpleNamespace(bcast_on=True, bcast_crowd=True)
    changes = []
    link = B.Link(s, log=lambda m: None, on_change=lambda: changes.append(audio_tool.EXCLUDE_PID))
    c, _ = srv.accept()
    for _ in range(50):
        if link.connected: break
        time.sleep(0.02)
    assert link.connected and changes and changes[-1]
    link.clip(tone(), 22050)
    p = B.Player(log=lambda m: None)
    c.settimeout(3)
    got = []
    orig = p.add_call
    p.add_call = lambda x, sr: (got.append(len(x)), orig(x, sr))
    import threading
    threading.Thread(target=lambda: p._client(c), daemon=True).start()
    for _ in range(100):
        if got: break
        time.sleep(0.02)
    link.stop()
    assert got and got[0] == len(tone())
    assert audio_tool.EXCLUDE_PID is None


def test_ring_same_as_index_version():
    """2026-10-29 (efficiency): the slice-based crowd ring gives exactly what the old index-array version gave."""
    class Old(B.Player):
        def add_crowd(self, b):
            n = len(b)
            idx = (self.cw + np.arange(n)) % len(self.crowd)
            with self.lock:
                self.crowd[idx] = b
                self.cw = (self.cw + n) % len(self.crowd)

        def render(self, out):
            frames = out.shape[0]
            out[:] = 0
            with self.lock:
                avail = (self.cw - self.cr) % len(self.crowd)
                if avail > B.RATE:
                    self.cr = (self.cw - int(0.2 * B.RATE)) % len(self.crowd); avail = int(0.2 * B.RATE); self.skips += 1
                if not self.crowd_on and avail >= int(0.2 * B.RATE):
                    self.crowd_on = True
                if self.crowd_on:
                    if avail >= frames:
                        idx = (self.cr + np.arange(frames)) % len(self.crowd)
                        out += self.crowd[idx] * (10 ** (self.cfg["crowd_db"] / 20.0))
                        self.cr = (self.cr + frames) % len(self.crowd)
                    else:
                        self.crowd_on = False; self.underruns += 1
                if self.cur is None and self.calls:
                    self.cur, self.pos = self.calls.pop(0), 0
                if self.cur is not None:
                    n = min(frames, len(self.cur) - self.pos)
                    seg = self.cur[self.pos:self.pos + n]
                    out[:n, 0] += seg; out[:n, 1] += seg
                    self.pos += n
                    if self.pos >= len(self.cur):
                        self.cur = None
            np.clip(out, -0.98, 0.98, out=out)

    rng = np.random.default_rng(5)
    a, b = Old(log=lambda m: None), B.Player(log=lambda m: None)
    a.cfg["crowd_db"] = b.cfg["crowd_db"] = -3.0
    oa, ob = np.zeros((1024, 2), np.float32), np.zeros((1024, 2), np.float32)
    for i in range(400):
        n = int(rng.choice([2048, 1500, 977, 3000, 120000 if i == 250 else 2048]))
        blk = (rng.standard_normal((n, 2)) * 0.1).astype(np.float32)
        a.add_crowd(blk); b.add_crowd(blk)
        for _ in range(int(rng.integers(0, 4))):
            a.render(oa); b.render(ob)
            assert np.array_equal(oa, ob)
        assert a.cw == b.cw and a.cr == b.cr and np.array_equal(a.crowd, b.crowd)


def test_put_message_bytes_unchanged():
    """_put builds the same bytes as before with one copy."""
    s = types.SimpleNamespace(bcast_on=True, bcast_crowd=True)
    link = B.Link.__new__(B.Link)
    link.q = __import__("queue").Queue()
    blk = np.arange(64, dtype=np.float64).reshape(32, 2) / 7
    link._put(2, B.RATE, 2, blk)
    link._put(1, 24000, 1, blk[:, 0])
    m2, m1 = bytes(link.q.get()), bytes(link.q.get())
    assert m2 == B.HDR.pack(2, B.RATE, 2, 32) + blk.astype(np.float32).tobytes()
    assert m1 == B.HDR.pack(1, 24000, 1, 32) + blk[:, 0].astype(np.float32).tobytes()


def test_keyup_tail_cached_identical():
    assert np.array_equal(B._fixed(B.keyup_click, B.RATE, 1), B.keyup_click())
    assert np.array_equal(B._fixed(B.squelch_tail, B.RATE, 2), B.squelch_tail())

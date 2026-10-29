"""#499: the controller's buttons send the right iRacing replay commands, and nothing while driving."""
from engineer import replay_remote as R


class FakeIR:
    is_initialized = is_connected = True

    def __init__(self, replay=True, on_track=False, speed=1):
        self.v = {"IsReplayPlaying": replay, "IsOnTrack": on_track, "ReplayPlaySpeed": speed}
        self.sent = []

    def __getitem__(self, k):
        return self.v.get(k)

    def replay_set_play_speed(self, s, slow=False):
        self.sent.append(("speed", s, slow))

    def replay_search(self, m):
        self.sent.append(("search", m))


def make(ir):
    r = R.ReplayRemote.__new__(R.ReplayRemote)
    r.ir, r.log, r.flag_url, r.running, r._slow, r._dir, r._step = ir, (lambda *a: None), "", False, False, 0, 0
    return r


def test_buttons():
    ir = FakeIR(); r = make(ir)
    r.press(R.A); assert ir.sent[-1] == ("speed", 0, False)
    ir.v["ReplayPlaySpeed"] = 0; r.press(R.A); assert ir.sent[-1] == ("speed", 1, False)
    r.press(R.RIGHT); r.press(R.RIGHT); assert ir.sent[-1] == ("speed", 4, False)
    r.press(R.LEFT); assert ir.sent[-1] == ("speed", -2, False)
    r.press(R.RB); assert ir.sent[-1] == ("search", R.NEXT_INC)
    r.press(R.Y); assert ("search", R.TO_END) in ir.sent


def test_never_while_driving():
    assert make(FakeIR(replay=False, on_track=True)).allowed() is False
    assert make(FakeIR(replay=True, on_track=True)).allowed() is True
    assert make(FakeIR(replay=False, on_track=False)).allowed() is True


def test_empty_slots_polled_rarely():
    """2026-10-29: a connected pad is read every frame, empty slots only every 2 s (Microsoft's XInput advice);
    a press still works, and iRacing is only asked on a press."""
    import threading, time
    calls = {0: 0, 1: 0, 2: 0, 3: 0}

    class XI:
        def XInputGetState(self, pad, ref):
            calls[pad] += 1
            if pad != 0:
                return 1167                      # ERROR_DEVICE_NOT_CONNECTED
            st = ref._obj
            st.Gamepad.wButtons = R.B if calls[0] > 5 else 0
            return 0

    ir = FakeIR(); r = make(ir); r.running = True
    asked = []
    r.allowed = lambda: asked.append(1) or True
    old = R._xinput
    R._xinput = lambda: XI()
    try:
        t = threading.Thread(target=r._loop, daemon=True); t.start()
        time.sleep(0.5)
        r.running = False; t.join(1)
    finally:
        R._xinput = old
    assert calls[0] > 10
    assert calls[1] == calls[2] == calls[3] == 1
    assert ("speed", 1, False) in ir.sent          # B pressed once -> normal speed
    assert len(asked) == 1                          # asked iRacing only for the one press

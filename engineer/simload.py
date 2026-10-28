"""Is the sim on a loading screen? (2026-10-27, #454, request: "the sounds get choppy at loading screens ... that is where it
is worst").

iRacing sends its live data 60 times a second. On a loading screen (joining, a session change that reloads, a big
hitch) the sim stalls and those updates collapse. While that happens the PC is at its busiest, so the engineer stops
making sound: the crowd / ambience fade out and radio lines wait (they are kept, not dropped) until the sim has run
smoothly again for a moment. Nothing to hear on a loading screen anyway.

BUSY is read by the crowd mixer (audio thread) and the radio worker - a plain bool, no locks.
"""
import time

BUSY = False
_last_tick = None
_last_t = None
_rate = 60.0
_low_since = None
_ok_since = None
_busy_since = None
LOW, OK = 20.0, 45.0            # updates per second: below LOW = stalling, above OK = smooth
GO_BUSY_S, CLEAR_S = 0.5, 2.0   # how long it must stay low / smooth before switching


def update(session_tick, now=None, log=None):
    """Call every engine tick with iRacing's SessionTick (None when not connected)."""
    global BUSY, _last_tick, _last_t, _rate, _low_since, _ok_since, _busy_since
    now = time.monotonic() if now is None else now
    if session_tick is None:
        _last_tick = _last_t = None
        _set(False, now, log)
        return
    if _last_tick is None or session_tick < _last_tick:
        _last_tick, _last_t = session_tick, now
        return
    dt = now - _last_t
    if dt < 0.2:                # measure over at least 0.2 s
        return
    r = (session_tick - _last_tick) / dt
    _last_tick, _last_t = session_tick, now
    _rate += (r - _rate) * 0.5
    if _rate < LOW:
        _ok_since = None
        _low_since = _low_since or now
        if now - _low_since >= GO_BUSY_S:
            _set(True, now, log)
    elif _rate > OK:
        _low_since = None
        _ok_since = _ok_since or now
        if now - _ok_since >= CLEAR_S:
            _set(False, now, log)
    else:
        _low_since = None


def _set(v, now, log):
    global BUSY, _busy_since
    if v == BUSY:
        return
    BUSY = v
    if v:
        _busy_since = now
    if log:
        try:
            log("[sound] sim loading - crowd and radio wait" if v else
                f"[sound] sim running smoothly again - sound back ({now - (_busy_since or now):.0f} s)")
        except Exception:
            pass


def busy_for():
    return (time.monotonic() - _busy_since) if (BUSY and _busy_since) else 0.0

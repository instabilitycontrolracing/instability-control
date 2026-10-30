"""The separate sound program (2026-10-29): never a gap, the bed covers pits / menus / a slow engineer."""
import os, sys, unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engineer import audio_proc as A
from engineer import crowd as C

RATE = 48000


def _player(seconds=2.0, loop=None, tmp=None):
    ctrl = np.zeros(A.NCTRL, np.int64)
    ctrl[A.GAIN] = A.SCALE
    ring = np.zeros((int(RATE * seconds), 2), np.float32)
    path = ""
    if loop is not None:
        path = os.path.join(tmp, "bed.npy"); np.save(path, loop); ctrl[A.LOOP_GEN] = 1
    p = A.Player(ctrl, ring, RATE, path)
    p.reload_loop()
    return p, ctrl, ring


def _write(ctrl, ring, block):
    w = int(ctrl[A.W]); n = len(block); fr = len(ring); p = w % fr; k = min(n, fr - p)
    ring[p:p + k] = block[:k]
    if n > k:
        ring[:n - k] = block[k:]
    ctrl[A.W] = w + n


class PlayerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        t = np.arange(RATE * 4) / RATE
        self.bed = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)[:, None].repeat(2, 1)

    def test_feed_passes_through_exactly(self):
        p, ctrl, ring = _player()
        x = np.random.default_rng(1).uniform(-0.5, 0.5, (4096, 2)).astype(np.float32)
        _write(ctrl, ring, x)
        out = np.zeros((1024, 2), np.float32); got = []
        for _ in range(4):
            p.render(out); got.append(out.copy())
        self.assertTrue(np.allclose(np.concatenate(got), x, atol=1e-6))
        self.assertEqual(int(ctrl[A.R]), 4096)

    def test_engineer_falls_behind_bed_covers_no_silence(self):
        p, ctrl, ring = _player(loop=self.bed, tmp=self.tmp)
        ctrl[A.LOOP_GAIN] = A.SCALE
        ctrl[A.MODE] = 0
        out = np.zeros((1024, 2), np.float32)
        x = np.full((1024 * 20, 2), 0.2, np.float32)
        _write(ctrl, ring, x)
        for _ in range(20):
            p.render(out)
            self.assertGreater(float(np.abs(out).max()), 0.05)
        # now the engineer stalls for half a second: no block may be silent
        silent = 0
        for _ in range(int(RATE * 0.5 / 1024)):
            p.render(out)
            if float(np.abs(out[-256:]).max()) < 0.01:
                silent += 1
        self.assertEqual(silent, 0)
        self.assertGreater(int(ctrl[A.DRY]), 0)

    def test_static_mode_plays_bed_and_drops_feed(self):
        p, ctrl, ring = _player(loop=self.bed, tmp=self.tmp)
        ctrl[A.LOOP_GAIN] = A.SCALE // 2
        ctrl[A.MODE] = 1
        p.g_feed, p.g_bed = 0.0, 1.0
        _write(ctrl, ring, np.full((8192, 2), 0.9, np.float32))
        out = np.zeros((1024, 2), np.float32)
        for _ in range(8):
            p.render(out)
            self.assertLess(float(np.abs(out).max()), 0.16)     # bed at half level only, feed not heard
        self.assertEqual(int(ctrl[A.R]), 8192)                   # feed consumed, never piles up

    def test_cut_fades_and_drops(self):
        p, ctrl, ring = _player()
        _write(ctrl, ring, np.full((RATE, 2), 0.5, np.float32))
        out = np.zeros((1024, 2), np.float32)
        p.render(out)
        ctrl[A.CUT] += 1
        p.render(out)
        self.assertLess(abs(float(out[-1, 0])), 0.01)
        self.assertEqual(int(ctrl[A.R]), int(ctrl[A.W]))

    def test_blend_is_gradual(self):
        p, ctrl, ring = _player(loop=self.bed, tmp=self.tmp)
        ctrl[A.LOOP_GAIN] = A.SCALE
        p.g_feed, p.g_bed = 0.0, 1.0
        ctrl[A.MODE] = 0
        _write(ctrl, ring, np.zeros((RATE, 2), np.float32))
        out = np.zeros((1024, 2), np.float32); peaks = []
        for _ in range(int(RATE * 0.6 / 1024)):
            p.render(out); peaks.append(float(np.abs(out).max()))
        self.assertGreater(peaks[0], 0.2)                        # the bed fades out, not cut off
        self.assertLess(peaks[-1], peaks[0])


class NoFlutterTests(unittest.TestCase):
    def test_slow_engineer_does_not_flutter(self):
        """A feed arriving at 80% of real time: few long stretches of bed, not a swap every block."""
        import tempfile
        t = np.arange(RATE * 4) / RATE
        bed = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)[:, None].repeat(2, 1)
        p, ctrl, ring = _player(seconds=4.0, loop=bed, tmp=tempfile.mkdtemp())
        ctrl[A.LOOP_GAIN] = A.SCALE
        out = np.zeros((1024, 2), np.float32)
        blk = np.full((819, 2), 0.2, np.float32)
        swaps, prev = 0, p.dry
        for _ in range(47 * 20):                       # 20 s
            _write(ctrl, ring, blk)
            p.render(out)
            if p.dry != prev:
                swaps += 1; prev = p.dry
        self.assertLess(swaps, 20 * 2)                 # at most about one round trip a second
        self.assertEqual(int(ctrl[A.DRY]) * 2 >= swaps - 1, True)


class BedTests(unittest.TestCase):
    def test_bed_is_seamless(self):
        rng = np.random.default_rng(3)
        mk = lambda n: C.Clip(n, (rng.uniform(-0.3, 0.3, (RATE * 7, 2)) * 32767).astype(np.int16))
        bed = C.build_bed({"bed_stadium_crowd_far": mk("a"), "bed_crowd_buzz_mid": mk("b")}, seconds=10)
        self.assertEqual(bed.shape, (RATE * 10, 2))
        self.assertLessEqual(float(np.abs(bed).max()), 0.91)
        jump = float(np.abs(bed[0] - bed[-1]).max())
        typical = float(np.median(np.abs(np.diff(bed[:, 0]))))
        self.assertLess(jump, typical * 12 + 0.05)

    def test_no_beds_no_bed(self):
        self.assertIsNone(C.build_bed({}))


if __name__ == "__main__":
    unittest.main()

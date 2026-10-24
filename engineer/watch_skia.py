"""ApexHUD's broadcast watch (port of ApexHUD-Native WatchRenderer.cs) for skia-python,
plus the intro frame: the watch spinning to local time while the app window forms around it."""
import math, os
import skia

HERE = os.path.dirname(os.path.abspath(__file__))
DIAL = os.path.join(HERE, "ui", "assets", "dial.png")


def hexc(rgb, a=255):
    return skia.Color((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255, a)


class Watch:
    def __init__(self):
        self.dial = skia.Image.open(DIAL) if os.path.exists(DIAL) else None
        p = lambda **k: skia.Paint(AntiAlias=True, **k)
        self.cream = p(Color=hexc(0xF4F0E6))
        self.bez_main = p(Style=skia.Paint.kStroke_Style, StrokeWidth=8, Shader=skia.GradientShader.MakeLinear(
            [(50, 4), (50, 96)], [hexc(0xFCF7E8), hexc(0xEDE3CA), hexc(0xC7BB9C), hexc(0x8E8267), hexc(0x534A38)],
            [0, .22, .48, .72, 1]))
        self.bez_dark = p(Style=skia.Paint.kStroke_Style, StrokeWidth=8, Shader=skia.GradientShader.MakeRadial(
            (50, 96), 59.8, [skia.Color(20, 16, 8, 140), skia.Color(20, 16, 8, 26), skia.Color(20, 16, 8, 0)], [0, .6, 1]))
        self.bez_gloss = p(Style=skia.Paint.kStroke_Style, StrokeWidth=8, Shader=skia.GradientShader.MakeRadial(
            (33.4, 22.4), 50.6, [skia.Color(255, 255, 250, 179), skia.Color(255, 255, 250, 31), skia.Color(255, 255, 250, 0)], [0, .55, 1]))
        self.flute_iv = p(Style=skia.Paint.kStroke_Style, StrokeWidth=.32, Color=skia.Color(255, 252, 240, 140))
        self.flute_bk = p(Style=skia.Paint.kStroke_Style, StrokeWidth=.34, Color=skia.Color(0, 0, 0, 140))
        self.inner = p(Style=skia.Paint.kStroke_Style, StrokeWidth=.55, Color=skia.Color(0, 0, 0, 179))
        self.outer = p(Style=skia.Paint.kStroke_Style, StrokeWidth=.4, Color=skia.Color(0, 0, 0, 115))
        self.sub_hand = p(Style=skia.Paint.kStroke_Style, StrokeWidth=1.1, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0x2A2418))
        self.gold = p(Color=hexc(0xC5A572))
        self.hour_edge = p(Style=skia.Paint.kStroke_Style, StrokeWidth=3.6, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0x9C7C45))
        self.min_edge = p(Style=skia.Paint.kStroke_Style, StrokeWidth=2.6, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0x9C7C45))
        self.hour = p(Style=skia.Paint.kStroke_Style, StrokeWidth=2.8, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0xF2E8D0))
        self.minute = p(Style=skia.Paint.kStroke_Style, StrokeWidth=1.9, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0xF2E8D0))
        self.second = p(Style=skia.Paint.kStroke_Style, StrokeWidth=.7, StrokeCap=skia.Paint.kRound_Cap, Color=hexc(0xC5A572))
        self.pin_gold = p(Color=hexc(0xE4C887))
        self.pin_core = p(Color=hexc(0x7A6240))
        self.shadow = p(Color=skia.Color(0, 0, 0, 166), MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 6))
        self.flutes = []
        for i in range(128):
            a = i * 2 * math.pi / 128
            s, c = math.sin(a), math.cos(a)
            self.flutes.append(((50 + 42 * s, 50 - 42 * c), (50 + 50 * s, 50 - 50 * c), i % 2 == 0))

    def draw(self, c, cx, cy, radius, hour_deg, min_deg, sec_deg, rotate=0.0, alpha=1.0, shadow=True):
        s = radius / 50.0
        if alpha <= 0:
            return
        if alpha < 1:
            c.saveLayerAlpha(None, int(alpha * 255))
        if shadow:  # drop-shadow(0 10px 24px rgba(0,0,0,.65)) in watch units
            c.save(); c.translate(cx, cy + 10 * s / 2.2); c.scale(s, s)
            sp = skia.Paint(AntiAlias=True, Color=skia.Color(0, 0, 0, 150), MaskFilter=skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, 5.5))
            c.drawCircle(0, 0, 49, sp)
            c.restore()
        c.save()
        c.translate(cx, cy); c.rotate(rotate); c.scale(s, s); c.translate(-50, -50)
        # dial
        c.save()
        path = skia.Path(); path.addCircle(50, 50, 44)
        c.clipPath(path, skia.ClipOp.kIntersect, True)
        c.drawCircle(50, 50, 44, self.cream)
        if self.dial:
            half = 88 * 1.24 / 2
            c.drawImageRect(self.dial, skia.Rect(50 - half, 50 - half, 50 + half, 50 + half),
                            skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear))
        c.restore()
        # subdials
        for (x, y), deg in (((28.8, 47.65), -25), ((70.75, 47.65), 15), ((49.95, 71.35), 40)):
            c.save(); c.rotate(deg, x, y); c.drawLine(x, y, x, y - 6.5, self.sub_hand); c.restore()
            c.drawCircle(x, y, .9, self.gold)
        # hands
        c.save(); c.rotate(hour_deg, 50, 50); c.drawLine(50, 55, 50, 28, self.hour_edge); c.drawLine(50, 55, 50, 28, self.hour); c.restore()
        c.save(); c.rotate(min_deg, 50, 50); c.drawLine(50, 55, 50, 16, self.min_edge); c.drawLine(50, 55, 50, 16, self.minute); c.restore()
        c.save(); c.rotate(sec_deg, 50, 50); c.drawLine(50, 60, 50, 13, self.second); c.drawCircle(50, 19, 1.2, self.second); c.restore()
        c.drawCircle(50, 50, 2.3, self.pin_gold); c.drawCircle(50, 50, 1.2, self.pin_core)
        # bezel
        c.drawCircle(50, 50, 46, self.bez_main)
        c.drawCircle(50, 50, 46, self.bez_dark)
        for a, b, iv in self.flutes:
            c.drawLine(a[0], a[1], b[0], b[1], self.flute_iv if iv else self.flute_bk)
        c.drawCircle(50, 50, 42, self.inner)
        c.drawCircle(50, 50, 49.9, self.outer)
        c.drawCircle(50, 50, 46, self.bez_gloss)
        c.restore()
        if alpha < 1:
            c.restore()


# ---------------- easing ----------------
class CubicBezier:
    def __init__(self, x1, y1, x2, y2):
        self.cx = 3 * x1; self.bx = 3 * (x2 - x1) - self.cx; self.ax = 1 - self.cx - self.bx
        self.cy = 3 * y1; self.by = 3 * (y2 - y1) - self.cy; self.ay = 1 - self.cy - self.by

    def _x(self, t): return ((self.ax * t + self.bx) * t + self.cx) * t
    def _y(self, t): return ((self.ay * t + self.by) * t + self.cy) * t
    def _dx(self, t): return (3 * self.ax * t + 2 * self.bx) * t + self.cx

    def __call__(self, x):
        if x <= 0: return 0.0
        if x >= 1: return 1.0
        t = x
        for _ in range(8):
            e = self._x(t) - x
            if abs(e) < 1e-6: return self._y(t)
            d = self._dx(t)
            if abs(d) < 1e-6: break
            t -= e / d
        lo, hi, t = 0.0, 1.0, x
        for _ in range(40):
            xt = self._x(t)
            if abs(xt - x) < 1e-6: break
            if x > xt: lo = t
            else: hi = t
            t = (lo + hi) / 2
        return self._y(t)


ARRIVE = CubicBezier(.34, 1.4, .64, 1)   # ApexHUD v46-watch-arrive
IO = CubicBezier(.65, 0, .35, 1)          # smooth in-out
OUT = CubicBezier(.16, 1, .3, 1)


def keyed(keys, p):
    if p <= keys[0][0]: return keys[0][1]
    for i in range(1, len(keys)):
        if p <= keys[i][0]:
            p0, v0 = keys[i - 1]; p1, v1 = keys[i]
            return v0 + (v1 - v0) * ARRIVE((p - p0) / (p1 - p0))
    return keys[-1][1]


def lerp(a, b, t): return a + (b - a) * t


def clock_angles(t_secs_of_day):
    s = t_secs_of_day
    return (s / 3600 % 12) * 30, (s / 60 % 60) * 6, (s % 60) * 6


# ---------------- the intro ----------------
T_ARRIVE, T_HOLD, T_MORPH, T_BAR = 0.10, 0.95, 1.65, 0.45   # starts / durations (s)
MORPH_START = T_HOLD
MORPH_END = T_HOLD + T_MORPH
INTRO_LEN = MORPH_END + 0.15


class Intro:
    """Draws one frame of the intro into a canvas of size W x H (physical px). k = px per CSS px."""
    def __init__(self, W, H, k, start_clock_secs):
        self.W, self.H, self.k = W, H, k
        self.watch = Watch()
        self.t_end_clock = start_clock_secs + MORPH_END   # wall time when the spin finishes
        self.bg = skia.Paint(AntiAlias=True, Color=hexc(0x05070C))
        Lw = W / k
        # body::before glows (ellipses -> scaled radial gradients)
        m1 = skia.Matrix(); m1.setScale(1, 520 / 1200, Lw / 2 * k, -140 * k)
        self.glow1 = skia.Paint(AntiAlias=True, Shader=skia.GradientShader.MakeRadial(
            (Lw / 2 * k, -140 * k), 1200 * k * .5, [skia.Color(197, 165, 114, 36), skia.Color(197, 165, 114, 0)], [0, .7],
            skia.TileMode.kClamp, 0, m1))
        m2 = skia.Matrix(); m2.setScale(1, 600 / 900, Lw / 2 * k, H * 1.2)
        self.glow2 = skia.Paint(AntiAlias=True, Shader=skia.GradientShader.MakeRadial(
            (Lw / 2 * k, H * 1.2), 900 * k * .5, [skia.Color(27, 62, 140, 46), skia.Color(27, 62, 140, 0)], [0, .7],
            skia.TileMode.kClamp, 0, m2))
        self.bar = skia.Paint(AntiAlias=True, Color=skia.Color(13, 20, 36, 199))
        bs = skia.Surface(int(W), int(H))
        bc = bs.getCanvas(); bc.drawRect(skia.Rect(0, 0, W, H), self.bg)
        bc.drawRect(skia.Rect(0, 0, W, H), self.glow1); bc.drawRect(skia.Rect(0, 0, W, H), self.glow2)
        self.bg_img = bs.makeImageSnapshot()
        self.edge = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=1 * k)

    def frame(self, c, t):
        W, H, k = self.W, self.H, self.k
        c.clear(skia.ColorTRANSPARENT)
        # watch geometry: centre of the window -> the session-bar slot (top middle)
        cx0, cy0, r0 = W / 2, H / 2 - 10 * k, 150 * k
        cx1, cy1, r1 = W / 2, (8 + 66) * k, 66 * k
        m = IO(min(1, max(0, (t - MORPH_START) / T_MORPH)))
        cx, cy, r = lerp(cx0, cx1, m), lerp(cy0, cy1, m), lerp(r0, r1, m)

        # --- the window forming around the watch ---
        if m > 0:
            pr = r * 0.97  # starts as a circle hugging the watch, centred on it as it moves
            left, right = lerp(cx - pr, 0, m), lerp(cx + pr, W, m)
            top, bottom = lerp(cy - pr, 0, m), lerp(cy + pr, H, m)
            rad = lerp(pr, 8 * k, IO(min(1, m * 1.15)))
            rr = skia.RRect.MakeRectXY(skia.Rect(left, top, right, bottom), rad, rad)
            c.save()
            c.clipRRect(rr, True)
            c.drawImage(self.bg_img, 0, 0)
            b = min(1, max(0, (t - (MORPH_END - T_BAR)) / T_BAR))
            if b > 0:  # session bar plate fades in as the window finishes forming
                bp = skia.Paint(self.bar); bp.setAlphaf(.78 * OUT(b))
                c.drawRect(skia.Rect(0, 0, W, 92 * k), bp)
                hp = skia.Paint(AntiAlias=True, Color=skia.Color(0, 0, 0, int(140 * OUT(b))))
                c.drawRect(skia.Rect(0, 0, W, 4 * k), hp)
            c.restore()
            # thin gold rim while forming (gone once it's a window)
            e = skia.Paint(self.edge); e.setColor(skia.Color(255, 216, 118, int(110 * (1 - m) ** .6)))
            c.drawRRect(rr, e)

        # --- watch ---
        p_arr = min(1, max(0, (t - T_ARRIVE) / 0.7))
        sc = keyed([(0, .36), (.62, 1.085), (.80, .965), (1, 1)], p_arr)
        rot = keyed([(0, -14), (.62, 3), (.80, -1), (1, 0)], p_arr)
        alpha = min(1, p_arr / .35)
        # hands: all at 12 until the morph, then spin to local time (minute hand takes an extra lap)
        th, tm, ts = clock_angles(self.t_end_clock)
        spin = IO(min(1, max(0, (t - MORPH_START) / (T_MORPH * .92))))
        if t >= MORPH_END:
            th, tm, ts = clock_angles(self.t_end_clock + (t - MORPH_END))
            h, mi, se = th, tm, ts
        else:
            h, mi, se = th * spin, (tm + 360) * spin, (ts + 720) * spin
        self.watch.draw(c, cx, cy, r * sc, h, mi, se, rotate=rot, alpha=alpha)


def render_icon_png(path, size=256):
    """The app logo: the watch face, hands at 10:10 like a catalogue shot."""
    import numpy as np
    a = np.zeros((size, size, 4), np.uint8)
    surf = skia.Surface(a, colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType)
    c = surf.getCanvas()
    Watch().draw(c, size / 2, size / 2, size / 2 - 1, -55, 60, 150, shadow=False)
    surf.flushAndSubmit()
    from PIL import Image
    Image.fromarray(a, "RGBA").save(path)
    return path

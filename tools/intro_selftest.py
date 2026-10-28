import ctypes, os, subprocess, sys, time, glob
from ctypes import wintypes
from PIL import ImageGrab
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test", "_dev", "intro_frames")
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(os.path.join(OUT, "*.png")): os.remove(f)
ctypes.windll.shcore.SetProcessDpiAwareness(2)
u = ctypes.windll.user32
k = u.GetDpiForSystem() / 96
wa = wintypes.RECT(); u.SystemParametersInfoW(0x30, 0, ctypes.byref(wa), 0)
w, h = int(1120 * k), int(780 * k)
x = wa.left + (wa.right - wa.left - w) // 2; y = wa.top + (wa.bottom - wa.top - h) // 2
print("dpi scale", k, "rect", x, y, w, h)
p = subprocess.Popen([os.path.join(ROOT, "venv_eng", "Scripts", "pythonw.exe"), "-m", "engineer.app"], cwd=ROOT)
t0 = time.time(); i = 0
while time.time() - t0 < 9:
    im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    im.resize((w // 2, h // 2)).save(os.path.join(OUT, f"f{i:03d}_{time.time() - t0:05.2f}.png")); i += 1
print("frames", i)
hw = u.FindWindowW(None, "Race Engineer")
r = wintypes.RECT(); u.GetWindowRect(hw, ctypes.byref(r)); print("app window rect", r.left, r.top, r.right - r.left, r.bottom - r.top)
u.PostMessageW(hw, 0x0010, 0, 0)
try: p.wait(8); print("closed ok")
except Exception: p.kill(); print("killed")

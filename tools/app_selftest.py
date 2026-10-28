import ctypes, os, subprocess, sys, time
from ctypes import wintypes
from PIL import ImageGrab
ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test", "_dev")
u = ctypes.windll.user32
ctypes.windll.shcore.SetProcessDpiAwareness(2)
p = subprocess.Popen([os.path.join(ROOT, "venv_eng", "Scripts", "python.exe"), "-m", "engineer.app"], cwd=ROOT,
                     stdout=open(os.path.join(OUT, "app_stdout.txt"), "w"), stderr=subprocess.STDOUT)
t0 = time.time(); hwnd = 0
while time.time() - t0 < 15 and not hwnd:
    hwnd = u.FindWindowW(None, "Race Engineer"); time.sleep(0.05)
print("window after", round(time.time() - t0, 2), "s")
u.SetForegroundWindow(hwnd)
t1 = time.time()
for at in (0.5, 1.2, 2.2, 3.4, 4.3, 5.0, 6.5, 9.0):
    while time.time() - t1 < at: time.sleep(0.01)
    r = wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(os.path.join(OUT, f"app_{int(at*10):03d}.png"))
u.PostMessageW(hwnd, 0x0010, 0, 0)
try:
    p.wait(10); print("closed ok")
except Exception:
    p.kill(); print("had to kill")

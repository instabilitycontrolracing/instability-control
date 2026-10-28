import ctypes, os, threading, time
from ctypes import wintypes
import webview
from PIL import ImageGrab
OUT = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test", "_dev")
ctypes.windll.shcore.SetProcessDpiAwareness(2)
HTML = """<html><body style='margin:0;background:transparent'>
<div style='position:absolute;left:150px;top:100px;width:200px;height:200px;border-radius:50%;background:#C5A572'></div></body></html>"""
def shot(win):
    time.sleep(2.5)
    u = ctypes.windll.user32
    h = u.FindWindowW(None, "transp")
    r = wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
    ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True).save(os.path.join(OUT, "transp.png"))
    print("rect", r.left, r.top, r.right, r.bottom, "version", webview.__dict__.get("__version__"))
    win.destroy()
w = webview.create_window("transp", html=HTML, width=500, height=400, frameless=True, transparent=True, easy_drag=False)
webview.start(shot, w)

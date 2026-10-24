import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engineer import gui
from PIL import ImageGrab
out = os.path.join(os.environ["USERPROFILE"], "Desktop", "Engineer Voice - Engine Test", "_dev", "gui_pc.png")
app = gui.App()
def shot():
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(out)
    print("devices:", app.dev.cget("values")[:6])
    print("controllers:", app.buttons.names)
    print("engine running:", app.engine and app.engine.running)
    app.on_close()
app.after(5000, shot)
app.mainloop()
print("closed ok")

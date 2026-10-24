"""Race Engineer window.  pythonw -m engineer.gui"""
import os, queue, sys, threading, time
import customtkinter as ctk

from .settings import Settings
from . import buttons as B

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGF = os.path.join(ROOT, "engineer_log.txt")

M_LIGHT, M_DARK, M_RED = "#3FA9F5", "#1B3E8C", "#E2231A"
BG, CARD, CARD2, TEXT, MUTED, ACCENT, OK, WARN = "#0E1116", "#161B22", "#1F2630", "#E6EDF3", "#8B98A5", "#2F7FE0", "#3FB950", "#D29922"
FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"


def output_devices():
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        out, seen = [], set()
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and apis[d["hostapi"]]["name"] in ("MME", "Windows WASAPI", "ALSA", "Core Audio"):
                n = d["name"]
                if n not in seen:
                    seen.add(n); out.append(n)
        return out
    except Exception:
        return []


class App(ctk.CTk):
    def __init__(self, engine_factory=None):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.s = Settings.load()
        self.q = queue.Queue()
        self.engine = None
        self.engine_factory = engine_factory
        self.title("Race Engineer")
        self.geometry("920x640")
        self.minsize(780, 560)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.buttons = B.Buttons(self.on_button, log=self.log)
        self.after(100, self._pump)
        self.after(400, self._boot)

    # ---------- layout ----------
    def _build(self):
        stripe = ctk.CTkFrame(self, height=5, fg_color=BG, corner_radius=0)
        stripe.pack(fill="x")
        for c in (M_LIGHT, M_DARK, M_RED):
            ctk.CTkFrame(stripe, height=5, fg_color=c, corner_radius=0).pack(side="left", fill="both", expand=True)

        top = ctk.CTkFrame(self, fg_color=BG)
        top.pack(fill="x", padx=22, pady=(16, 8))
        left = ctk.CTkFrame(top, fg_color=BG)
        left.pack(side="left")
        ctk.CTkLabel(left, text="RACE ENGINEER", font=(FONT, 22, "bold"), text_color=TEXT).pack(anchor="w")
        self.sub = ctk.CTkLabel(left, text="Off", font=(FONT, 13), text_color=MUTED)
        self.sub.pack(anchor="w")
        self.go = ctk.CTkButton(top, text="Start", width=150, height=44, corner_radius=10,
                                font=(FONT, 15, "bold"), fg_color=ACCENT, command=self.toggle)
        self.go.pack(side="right")

        tiles = ctk.CTkFrame(self, fg_color=BG)
        tiles.pack(fill="x", padx=22, pady=(0, 10))
        self.tile = {}
        for k, title in (("ir", "iRacing"), ("track", "Track"), ("car", "Car"), ("sess", "Session")):
            f = ctk.CTkFrame(tiles, fg_color=CARD, corner_radius=10)
            f.pack(side="left", fill="x", expand=True, padx=(0 if k == "ir" else 8, 0))
            ctk.CTkLabel(f, text=title.upper(), font=(FONT, 10, "bold"), text_color=MUTED).pack(anchor="w", padx=14, pady=(10, 0))
            v = ctk.CTkLabel(f, text="-", font=(FONT, 14, "bold"), text_color=TEXT, anchor="w")
            v.pack(anchor="w", padx=14, pady=(0, 10), fill="x")
            self.tile[k] = v

        self.tabs = ctk.CTkTabview(self, fg_color=CARD, segmented_button_selected_color=ACCENT,
                                   segmented_button_fg_color=CARD2, segmented_button_unselected_color=CARD2,
                                   corner_radius=12)
        self.tabs.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        for t in ("Radio", "Sound", "Calls", "Buttons", "General"):
            self.tabs.add(t)
        self._tab_radio(self.tabs.tab("Radio"))
        self._tab_sound(self.tabs.tab("Sound"))
        self._tab_calls(self.tabs.tab("Calls"))
        self._tab_buttons(self.tabs.tab("Buttons"))
        self._tab_general(self.tabs.tab("General"))

    def _section(self, parent, title, note=None):
        f = ctk.CTkFrame(parent, fg_color=CARD2, corner_radius=10)
        f.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(f, text=title, font=(FONT, 14, "bold"), text_color=TEXT).pack(anchor="w", padx=16, pady=(12, 0))
        if note:
            ctk.CTkLabel(f, text=note, font=(FONT, 12), text_color=MUTED, justify="left", wraplength=780).pack(anchor="w", padx=16)
        body = ctk.CTkFrame(f, fg_color=CARD2, height=4)
        body.pack(fill="x", padx=16, pady=(6, 12))
        return body

    def _tab_radio(self, t):
        self.feed = ctk.CTkTextbox(t, fg_color=BG, text_color=TEXT, font=(FONT, 13), corner_radius=10, wrap="word")
        self.feed.pack(fill="both", expand=True, padx=6, pady=(6, 8))
        self.feed.tag_config("eng", foreground=M_LIGHT)
        self.feed.tag_config("you", foreground=WARN)
        self.feed.tag_config("sys", foreground=MUTED)
        self.feed.configure(state="disabled")
        row = ctk.CTkFrame(t, fg_color=CARD)
        row.pack(fill="x", padx=6, pady=(0, 6))
        self.ask = ctk.CTkEntry(row, placeholder_text="Ask your engineer, e.g. \"how's the gap to the car in front?\"",
                                height=38, font=(FONT, 13), fg_color=BG, border_color=CARD2)
        self.ask.pack(side="left", fill="x", expand=True)
        self.ask.bind("<Return>", lambda e: self.send())
        ctk.CTkButton(row, text="Ask", width=80, height=38, fg_color=ACCENT, command=self.send).pack(side="left", padx=(8, 0))
        row2 = ctk.CTkFrame(t, fg_color=CARD)
        row2.pack(fill="x", padx=6, pady=(0, 4))
        ctk.CTkButton(row2, text="Radio check", width=130, fg_color=CARD2, hover_color=M_DARK,
                      command=lambda: self.engine and self.engine.voice.test_tone()).pack(side="left")
        self.demo_btn = ctk.CTkButton(row2, text="Play demo race", width=150, fg_color=CARD2, hover_color=M_DARK,
                                      command=self.demo)
        self.demo_btn.pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Questions are typed for now. Your radio button + voice is next.",
                     font=(FONT, 11), text_color=MUTED).pack(side="right")

    def _tab_sound(self, t):
        b = self._section(t, "Volume")
        self.vol_lbl = ctk.CTkLabel(b, text="", width=60, font=(FONT, 13, "bold"))
        sl = ctk.CTkSlider(b, from_=0, to=1.5, number_of_steps=30, command=self.set_volume, button_color=ACCENT,
                           progress_color=ACCENT)
        sl.set(self.s.volume); sl.pack(side="left", fill="x", expand=True); self.vol_lbl.pack(side="left", padx=10)
        self.set_volume(self.s.volume, save=False)

        b = self._section(t, "Radio sound", "How much it sounds like he's on a headset over the radio. The middle is the one you picked (radio test 2).")
        self.rad_lbl = ctk.CTkLabel(b, text="", width=110, font=(FONT, 13, "bold"))
        rs = ctk.CTkSlider(b, from_=0, to=2, number_of_steps=40, command=self.set_radio, button_color=ACCENT,
                           progress_color=ACCENT)
        rs.set(self.s.radio_strength); rs.pack(side="left", fill="x", expand=True); self.rad_lbl.pack(side="left", padx=10)
        self.set_radio(self.s.radio_strength, save=False)
        ctk.CTkButton(b, text="Reset", width=70, fg_color=CARD, command=lambda: (rs.set(1.0), self.set_radio(1.0))).pack(side="left")

        b = self._section(t, "Output", "Where his voice plays. Pick your headset if you don't want him on the speakers.")
        devs = ["Windows default"] + output_devices()
        cur = self.s.device if self.s.device in devs else "Windows default"
        self.dev = ctk.CTkOptionMenu(b, values=devs, width=420, fg_color=BG, button_color=ACCENT, command=self.set_device)
        self.dev.set(cur); self.dev.pack(side="left")
        ctk.CTkButton(b, text="Test", width=80, fg_color=ACCENT,
                      command=lambda: self.engine and self.engine.voice.test_tone()).pack(side="left", padx=10)

    def _switch(self, parent, text, attr, note=None):
        row = ctk.CTkFrame(parent, fg_color=CARD2)
        row.pack(fill="x", pady=3)
        sw = ctk.CTkSwitch(row, text=text, font=(FONT, 13), progress_color=ACCENT,
                           command=lambda: self.set_flag(attr, bool(sw.get())))
        if getattr(self.s, attr):
            sw.select()
        sw.pack(side="left")
        if note:
            ctk.CTkLabel(row, text=note, font=(FONT, 11), text_color=MUTED).pack(side="left", padx=12)
        return sw

    def _tab_calls(self, t):
        b = self._section(t, "What he calls")
        self._switch(b, "Spotter", "spotter", "car left / car right / clear")
        self._switch(b, "Gap updates", "gaps", "car ahead and behind during the race")
        self._switch(b, "Quiet in corners", "hold_in_corners", "non-urgent messages wait for the straight")
        row = ctk.CTkFrame(b, fg_color=CARD2)
        row.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(row, text="Gap update every", font=(FONT, 13)).pack(side="left")
        seg = ctk.CTkSegmentedButton(row, values=["1", "2", "3", "5"], selected_color=ACCENT,
                                     command=lambda v: self.set_flag("gaps_every", int(v)))
        seg.set(str(self.s.gaps_every)); seg.pack(side="left", padx=10)
        ctk.CTkLabel(row, text="laps", font=(FONT, 13)).pack(side="left")
        self._section(t, "Always on", "Flags, penalties, track limits, safety car, fuel warnings, pit calls, last lap and the finish. "
                      "Hybrid-only calls are only used when you're in the M Hybrid V8.")

    def _tab_buttons(self, t):
        self.bind_lbl = {}
        for attr, title, note in (
                ("radio_button", "Radio button", "Your wheel's B button. Hold it to talk to your engineer (voice recognition is next; for now it does a radio check)."),
                ("team_button", "Team / meeting button", "A button on your Ajazz box for the team advisors and meetings (the meeting room comes later).")):
            b = self._section(t, title, note)
            lbl = ctk.CTkLabel(b, text=B.describe(getattr(self.s, attr)), font=(FONT, 13, "bold"), text_color=TEXT)
            lbl.pack(side="left")
            self.bind_lbl[attr] = lbl
            ctk.CTkButton(b, text="Clear", width=70, fg_color=CARD, command=lambda a=attr: self.set_binding(a, None)).pack(side="right")
            ctk.CTkButton(b, text="Set", width=90, fg_color=ACCENT, command=lambda a=attr: self.capture(a)).pack(side="right", padx=8)
        b = self._section(t, "Controllers found")
        self.ctrl_lbl = ctk.CTkLabel(b, text="Looking...", font=(FONT, 12), text_color=MUTED, justify="left")
        self.ctrl_lbl.pack(anchor="w")
        self.after(1500, self._refresh_ctrls)

    def _tab_general(self, t):
        b = self._section(t, "Starting up")
        self._switch(b, "Turn the engineer on when this window opens", "autostart_engine")
        sw = self._switch(b, "Open Race Engineer when Windows starts", "start_with_windows")
        sw.configure(command=lambda: self.set_startup(bool(sw.get())))
        b = self._section(t, "About", "Your race engineer for iRacing. It finds iRacing on its own: just leave this window open (or minimised) and drive.")
        ctk.CTkButton(b, text="Open log file", width=140, fg_color=CARD, command=self.open_log).pack(side="left")

    # ---------- actions ----------
    def log(self, msg):
        self.q.put(("log", msg))
        try:
            with open(LOGF, "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except OSError:
            pass

    def _pump(self):
        try:
            while True:
                kind, x = self.q.get_nowait()
                if kind == "log":
                    self._feed(x)
                elif kind == "status":
                    self._show_status(x)
                elif kind == "fn":
                    x()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _feed(self, msg):
        tag = "eng" if msg.startswith("ENGINEER:") else ("you" if msg.startswith("YOU:") else "sys")
        if tag == "sys" and msg.startswith("[") and "error" not in msg:
            return  # keep the readout clean; details stay in the log file
        self.feed.configure(state="normal")
        self.feed.insert("end", time.strftime("%H:%M  ") + msg.replace("ENGINEER: ", "").replace("YOU: ", "You: ") + "\n", tag)
        self.feed.see("end")
        self.feed.configure(state="disabled")

    def _show_status(self, st):
        state = st.get("state")
        on = self.engine is not None and self.engine.running
        self.go.configure(text="Stop" if on else "Start", fg_color="#B42318" if on else ACCENT)
        if state == "connected":
            self.tile["ir"].configure(text="Connected", text_color=OK)
            self.tile["track"].configure(text=st.get("track") or "-")
            self.tile["car"].configure(text=(st.get("car") or "-") + ("  (hybrid)" if st.get("gtp") else ""))
            p = st.get("pos")
            self.tile["sess"].configure(text=(st.get("session") or "-") + (f"   P{p}" if p else ""))
            self.sub.configure(text="On the radio")
        else:
            self.tile["ir"].configure(text={"waiting": "Waiting...", "stopped": "Off", "error": "Problem"}.get(state, "-"),
                                      text_color=WARN if state == "waiting" else MUTED)
            for k in ("track", "car", "sess"):
                self.tile[k].configure(text="-")
            self.sub.configure(text="Waiting for iRacing" if state == "waiting" else "Off")

    def _boot(self):
        self.log("Race Engineer window open.")
        if self.s.autostart_engine:
            self.toggle()
        else:
            self._show_status({"state": "stopped"})

    def _make_engine(self):
        if self.engine is None:
            from .engine import Engine
            factory = self.engine_factory or Engine
            self.engine = factory(self.s, log=self.log,
                                  on_status=lambda st: self.q.put(("status", st)))

    def toggle(self):
        try:
            self._make_engine()
        except Exception as e:
            self.log(f"Couldn't start the engineer: {e}")
            return
        if self.engine.running:
            self.engine.stop()
        else:
            self.engine.start()
        self._show_status(self.engine.status if self.engine.running else {"state": "stopped"})

    def send(self):
        txt = self.ask.get().strip()
        if not txt:
            return
        self.ask.delete(0, "end")
        if self.engine:
            self.engine.ask(txt)

    def demo(self):
        self.demo_btn.configure(state="disabled", text="Playing...")
        def run():
            try:
                from .demo import run_demo
                from .engine import VOCAB, PRESET, LANDMARKS
                run_demo(VOCAB, PRESET, LANDMARKS, None, self.s.device or None, self.s.volume, self.log)
            except Exception as e:
                self.log(f"Demo problem: {e}")
            self.q.put(("fn", lambda: self.demo_btn.configure(state="normal", text="Play demo race")))
        threading.Thread(target=run, daemon=True).start()

    def set_volume(self, v, save=True):
        self.s.volume = round(float(v), 2)
        self.vol_lbl.configure(text=f"{int(self.s.volume * 100)}%")
        if save:
            self._changed()

    def set_radio(self, v, save=True):
        self.s.radio_strength = round(float(v), 2)
        x = self.s.radio_strength
        name = "Clean" if x < 0.15 else ("Light" if x < 0.8 else ("Your pick" if x <= 1.2 else ("Heavy" if x < 1.8 else "TV radio")))
        self.rad_lbl.configure(text=name)
        if save:
            self._changed()

    def set_device(self, name):
        self.s.device = "" if name == "Windows default" else name
        self.s.save()
        if self.engine:
            self.engine.set_device(self.s.device)

    def set_flag(self, attr, val):
        setattr(self.s, attr, val)
        self._changed()

    def _changed(self):
        self.s.save()
        if self.engine:
            self.engine.apply()

    def capture(self, attr):
        self.bind_lbl[attr].configure(text="Press the button now...", text_color=WARN)
        def got(name, btn):
            self.q.put(("fn", lambda: self.set_binding(attr, {"device": name, "button": btn})))
        self.buttons.capture = got

    def set_binding(self, attr, binding):
        setattr(self.s, attr, binding)
        self.s.save()
        self.bind_lbl[attr].configure(text=B.describe(binding), text_color=TEXT)

    def on_button(self, name, btn, down):
        if not down or not self.engine:
            return
        if B.matches(self.s.radio_button, name, btn):
            self.engine.voice.test_tone()
        elif B.matches(self.s.team_button, name, btn):
            if self.engine.brain:
                self.engine.brain.say("tb_standby", prio=1)

    def _refresh_ctrls(self):
        names = self.buttons.names if self.buttons.ok else []
        self.ctrl_lbl.configure(text="\n".join(names) if names else "No wheel or button box found. Plug it in, it shows up here.")
        self.after(3000, self._refresh_ctrls)

    def set_startup(self, on):
        self.s.start_with_windows = on
        self.s.save()
        try:
            folder = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup")
            path = os.path.join(folder, "Race Engineer.bat")
            if on:
                pyw = os.path.join(ROOT, "venv_eng", "Scripts", "pythonw.exe")
                open(path, "w").write(f'@echo off\r\ncd /d "{ROOT}"\r\nstart "" "{pyw}" -m engineer.gui\r\n')
            elif os.path.exists(path):
                os.remove(path)
        except Exception as e:
            self.log(f"Couldn't change Windows startup: {e}")

    def open_log(self):
        try:
            os.startfile(LOGF)
        except Exception:
            pass

    def on_close(self):
        if self.engine:
            self.engine.close()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()

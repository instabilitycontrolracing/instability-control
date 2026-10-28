"""Race mode (#353, 2026-10-27, request: "turn off all non essential background processes so I have ultimate performance").

When iRacing's sim starts, the engineer closes a short list of desktop apps that do nothing for racing, remembers which
ones it closed, and opens exactly those again when the sim closes. Closing is polite first (taskkill without /F, which
asks the window to close, like clicking X), forced only for apps that ignore it after a few seconds and are on the
"safe to force" list.

Never touched, whatever the list says (PROTECTED): the sim and iRacing UI, Steam / SteamVR / the headset driver,
Discord, Trading Paints, Voicemeeter, Apollo / Sunshine, Grandstand, the engineer itself (python), Claude, RustDesk,
NVIDIA's display driver containers, Windows itself - and the owner's standing rule: "do not touch the linux, do not touch
the docker, do not touch the home server, do not touch the AI node" (WSL / vmmem, Docker, node, ollama, anything with
"ab server" / "ai node" in its path).
"""
import os, subprocess, time

NO_WINDOW = 0x08000000

# image name (lower case) -> label. Only apps that are pure background / convenience while racing.
DEFAULT_LIST = [
    # MusicBee stays (10-27, request: "I use MusicBee to get in the zone... music between drives, sometimes while driving");
    # NVIDIA Broadcast was uninstalled 10-27 (nothing used it)
    "brave.exe",
    "googledrivefs.exe",              # Drive pauses during the race; the telemetry vault uploads after (it retries)
    "onedrive.exe", "onedrive.sync.service.exe",
    "widgetboard.exe", "widgets.exe", "microsoftstartfeedprovider.exe",
    "crossdeviceresume.exe", "phoneexperiencehost.exe",
    "spotify.exe",
    "epicgameslauncher.exe", "eadesktop.exe", "battle.net.exe",
]
FORCE_OK = {"widgetboard.exe", "widgets.exe", "microsoftstartfeedprovider.exe", "crossdeviceresume.exe",
            "phoneexperiencehost.exe"}

PROTECTED_NAMES = {
    "iracingsim64dx11.exe", "iracingui.exe", "iracingservice.exe", "iracingservice64.exe",
    "steam.exe", "steamwebhelper.exe", "vrserver.exe", "vrcompositor.exe", "vrmonitor.exe", "vrdashboard.exe",
    "vrwebhelper.exe", "client_utility.exe", "discord.exe", "trading paints.exe", "voicemeeter_x64.exe",
    "voicemeeter.exe", "voicemeeterpro.exe", "voicemeeter8x64.exe", "sunshine.exe", "apollo.exe",
    "apexhud.native.gpuhost.exe", "python.exe", "pythonw.exe", "claude.exe", "rustdesk.exe",
    "musicbee.exe", "nvdisplay.container.exe", "nvcontainer.exe", "explorer.exe", "dwm.exe", "csrss.exe", "winlogon.exe",
    "svchost.exe", "conhost.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "windowsterminal.exe",
    # the owner's standing rule (10-27): never the Linux, the Docker, the home server or the AI node
    "wsl.exe", "wslhost.exe", "wslservice.exe", "vmmem", "vmmemwsl", "vmwp.exe", "docker.exe", "docker desktop.exe",
    "com.docker.backend.exe", "com.docker.build.exe", "dockerd.exe", "node.exe", "ollama.exe", "ollama app.exe",
}
PROTECTED_PATH_WORDS = ("docker", "wsl", "ubuntu", "linux", "ollama", "ab server", "ab-server", "abserver",
                        "ai node", "ai-node", "ainode", "\\iracing\\", "crewchief", "instabilitycontrol")


def protected(name, path=""):
    n = (name or "").lower()
    p = (path or "").lower()
    return n in PROTECTED_NAMES or any(w in p for w in PROTECTED_PATH_WORDS)


def _procs():
    """[(image name lower, pid, exe path)] for this user's processes (one PowerShell call)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object { $_.Path } | ForEach-Object { $_.ProcessName + '.exe|' + $_.Id + '|' + $_.Path }"],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) == 3 and parts[1].isdigit():
            res.append((parts[0].lower(), int(parts[1]), parts[2]))
    return res


class RaceMode:
    def __init__(self, log=print, names=None):
        self.log = log
        self.names = [n.lower() for n in (names or DEFAULT_LIST)]
        self.closed = {}          # image name -> exe path to reopen

    def on_sim_start(self):
        procs = _procs()
        targets = {}
        for name, pid, path in procs:
            if name in self.names and not protected(name, path):
                targets.setdefault(name, path)
        if not targets:
            self.log("[race mode] nothing to close")
            return []
        for name in targets:
            subprocess.run(["taskkill", "/IM", name, "/T"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        time.sleep(5)
        left = {n for n, _, _ in _procs()}
        for name in targets:
            if name in left and name in FORCE_OK:
                subprocess.run(["taskkill", "/IM", name, "/T", "/F"], capture_output=True, timeout=15, creationflags=NO_WINDOW)
        left = {n for n, _, _ in _procs()}
        closed = [n for n in targets if n not in left]
        for n in closed:
            self.closed[n] = targets[n]
        still = [n for n in targets if n in left]
        self.log(f"[race mode] closed for the session: {', '.join(closed) or 'none'}"
                 + (f" - still open (they refused): {', '.join(still)}" if still else ""))
        return closed

    def on_sim_stop(self):
        if not self.closed:
            return []
        running = {n for n, _, _ in _procs()}
        opened = []
        for name, path in list(self.closed.items()):
            if name not in running and path and os.path.isfile(path):
                try:
                    subprocess.Popen([path], cwd=os.path.dirname(path), creationflags=0x00000008)   # DETACHED_PROCESS
                    opened.append(name)
                except OSError as e:
                    self.log(f"[race mode] couldn't reopen {name}: {e}")
        self.closed.clear()
        self.log(f"[race mode] reopened after the session: {', '.join(opened) or 'none'}")
        return opened

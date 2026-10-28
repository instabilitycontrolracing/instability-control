"""VR colour (#308, 2026-10-27): ReShade as an OpenXR layer for the headset, run from Settings > General.

What it does, and what it never does:
- Finds ReShade's OpenXR layer (C:\\ProgramData\\ReShade\\ReShade64_XR.json, registered under
  HKLM\\SOFTWARE\\Khronos\\OpenXR\\1\\ApiLayers\\Implicit - a DWORD named by the json path: 0 = on, 1 = off).
- Switches the layer on / off. That key is machine-wide, so Windows asks once per change (UAC, an elevated
  PowerShell that sets that one value). Never silently, and never while iRacing's sim is running: ReShade loads
  when the sim starts and saves its own ini when it closes, so every change here waits for iRacing to be closed.
- Picks the preset (Off / Day / Night) by writing PresetPath in ReShadeVR.ini in the iRacing folder. If that
  folder is write-protected the same one-time UAC prompt copies the file in. "Off" is an empty preset (Off.ini in
  the preset folder), so the layer can stay on while no effect runs.
- Sliders for the uniforms of the preset's effects that have a ui_min / ui_max in their .fx file (e.g. MyColor.fx).
- NVIDIA Digital Vibrance: applied through the owner's own NvAPI script (C:\\SimRacing\\Tools\\nv_vibrance.py).
- Never downloads or installs anything: for a PC without ReShade it only shows the official site's address.
"""
import os, re, shutil, subprocess, sys, tempfile, time

SITE = "https://reshade.me"
LAYER_DIR = r"C:\ProgramData\ReShade"
LAYER_JSON = LAYER_DIR + r"\ReShade64_XR.json"
LAYER_DLL = LAYER_DIR + r"\ReShade64.dll"
REG_PATH = r"SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit"
IRACING_DIRS = (r"C:\Program Files (x86)\iRacing", r"C:\Program Files\iRacing")
INI_NAME = "ReShadeVR.ini"
PRESET_DIR = r"C:\SimRacing\ReShade"
PRESETS = ("Off", "Day", "Night")
SIM_EXE = "iracingsim64dx11.exe"
VIBRANCE_SCRIPT = r"C:\SimRacing\Tools\nv_vibrance.py"
NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- ini files (ReShade's own format) ----------
def read_lines(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read().splitlines()


def parse_ini(lines):
    """{section: {key: value}}; keys before the first [section] are under ""."""
    out, sec = {"": {}}, ""
    for ln in lines:
        s = ln.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            sec = s[1:-1].strip(); out.setdefault(sec, {})
        elif "=" in s:
            k, v = s.split("=", 1)
            out.setdefault(sec, {})[k.strip()] = v.strip()
    return out


def ini_get(lines, section, key, default=None):
    return parse_ini(lines).get(section, {}).get(key, default)


def ini_set(lines, section, key, value):
    """A copy of `lines` with key=value in [section] (section "" = before the first section). Everything else -
    order, comments, other keys - stays exactly as it was."""
    lines, sec, start, end = list(lines), "", None, None
    if section == "":
        start = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if sec == section and start is not None and end is None:
                end = i
            sec = s[1:-1].strip()
            if sec == section and start is None:
                start = i + 1
            continue
        if sec == section and start is not None and end is None and "=" in s and s[0] not in ";#":
            if s.split("=", 1)[0].strip() == key:
                lines[i] = f"{key}={value}"
                return lines
    if start is None:                                # no such section yet: add it at the end
        if lines and lines[-1].strip():
            lines.append("")
        return lines + [f"[{section}]", f"{key}={value}"]
    if end is None:
        end = len(lines)
    at = end
    while at > start and not lines[at - 1].strip():  # keep the blank line before the next section
        at -= 1
    lines.insert(at, f"{key}={value}")
    return lines


def write_lines(path, lines):
    """Atomic write next to the file (no BOM, Windows line ends like ReShade writes them)."""
    tmp = path + ".ic_tmp"
    with open(tmp, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- effect uniforms -------------------------------
_UNI = re.compile(r"uniform\s+(float|int)\s+(\w+)\s*(?:<(.*?)>)?\s*=\s*([^;]+);", re.S)
_ANN = re.compile(r"(ui_\w+)\s*=\s*(\"[^\"]*\"|[^;]+);", re.S)


def parse_fx_uniforms(text):
    """Scalar float / int uniforms that have ui_min and ui_max: [{name, label, min, max, step, default, int}]."""
    text = re.sub(r"//[^\n]*", "", text)
    out = []
    for typ, name, ann, default in _UNI.findall(text):
        a = {k: v.strip().strip('"') for k, v in _ANN.findall(ann or "")}
        try:
            lo, hi = float(a["ui_min"].rstrip("f")), float(a["ui_max"].rstrip("f"))
            d = float(default.strip().rstrip("f"))
        except (KeyError, ValueError):
            continue
        st = a.get("ui_step")
        try:
            st = float(st.rstrip("f")) if st else (1.0 if typ == "int" else (hi - lo) / 100.0)
        except ValueError:
            st = (hi - lo) / 100.0
        out.append({"name": name, "label": a.get("ui_label") or name, "min": lo, "max": hi, "step": st,
                    "default": d, "int": typ == "int", "tip": a.get("ui_tooltip", "")})
    return out


def fx_search_dirs(ini_path, ini):
    """Where ReShade looks for .fx files: EffectSearchPaths (relative to the ini, "\\**" = with sub-folders),
    then the usual reshade-shaders\\Shaders next to the ini and in the preset folder."""
    base = os.path.dirname(ini_path) if ini_path else ""
    dirs = []
    for p in (ini.get("GENERAL", {}).get("EffectSearchPaths", "") or "").split(","):
        p = p.strip().strip('"')
        if not p:
            continue
        rec = p.endswith("**")
        p = p.rstrip("*").rstrip("\\/")
        p = p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
        dirs.append((p, rec))
    for b in (base, PRESET_DIR):
        if b:
            dirs.append((os.path.join(b, "reshade-shaders", "Shaders"), True))
            dirs.append((b, False))
    return dirs


def find_fx(name, dirs):
    for d, rec in dirs:
        if not os.path.isdir(d):
            continue
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
        if rec:
            for root, _, files in os.walk(d):
                if name in files:
                    return os.path.join(root, name)
    return None


def preset_effects(preset_lines):
    """'Techniques=MyColor@MyColor.fx,Vibrance@Vibrance.fx' -> ['MyColor.fx', 'Vibrance.fx']."""
    t = ini_get(preset_lines, "", "Techniques", "") or ""
    out = []
    for item in t.split(","):
        if "@" in item:
            fx = item.split("@", 1)[1].strip()
            if fx and fx not in out:
                out.append(fx)
    return out


def sliders(preset_path, ini_path=None, ini=None):
    """The adjustable uniforms of every effect in the preset, with the preset's current value."""
    try:
        pl = read_lines(preset_path)
    except OSError:
        return []
    cur = parse_ini(pl)
    dirs = fx_search_dirs(ini_path, ini or {})
    out = []
    for fx in preset_effects(pl):
        path = find_fx(fx, dirs)
        if not path:
            continue
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                unis = parse_fx_uniforms(f.read())
        except OSError:
            continue
        for u in unis:
            v = cur.get(fx, {}).get(u["name"])
            try:
                u["value"] = float(v) if v is not None else u["default"]
            except ValueError:
                u["value"] = u["default"]
            u["fx"] = fx
            out.append(u)
    return out


def fmt_value(v, is_int=False):
    return str(int(round(v))) if is_int else f"{float(v):.6f}"


# ---------------------------------------------------------------- the PC ------------------------------------------
def find_ini(dirs=IRACING_DIRS):
    for d in dirs:
        p = os.path.join(d, INI_NAME)
        if os.path.isfile(p):
            return p
    return None


def preset_path(name, folder=PRESET_DIR):
    return os.path.join(folder, f"{name}.ini")


def ensure_off_preset(folder=PRESET_DIR):
    """An empty preset: the layer stays loaded but runs nothing."""
    p = preset_path("Off", folder)
    if not os.path.isfile(p):
        os.makedirs(folder, exist_ok=True)
        write_lines(p, ["PreprocessorDefinitions=", "Techniques=", "TechniqueSorting="])
    return p


def preset_name(path, folder=PRESET_DIR):
    if not path:
        return ""
    for n in PRESETS:
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(preset_path(n, folder))):
            return n
    return os.path.splitext(os.path.basename(path))[0]


def _reg_layers():
    """{json path: dword} of every implicit OpenXR layer (64-bit registry), or None when it can't be read."""
    try:
        import winreg
        flags = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REG_PATH, 0, flags) as k:
            out, i = {}, 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[n] = v; i += 1
            return out
    except FileNotFoundError:
        return {}
    except Exception:
        return None


def layer_json(layers):
    """ReShade's own json: the registered one if there is one (other installs may use another folder)."""
    for n in (layers or {}):
        if "reshade" in os.path.basename(n).lower():
            return n
    return LAYER_JSON


def sim_running():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", f"IMAGENAME eq {SIM_EXE}"], capture_output=True,
                             text=True, timeout=8, creationflags=NO_WINDOW).stdout
        return SIM_EXE in out.lower()
    except Exception:
        return False


def status(running=None, ini_dirs=IRACING_DIRS, folder=PRESET_DIR):
    layers = _reg_layers()
    js = layer_json(layers)
    installed = os.path.isfile(js) and os.path.isfile(os.path.join(os.path.dirname(js), "ReShade64.dll"))
    if layers is None:
        layer = "unknown"
    elif js in layers:
        layer = "on" if layers[js] == 0 else "off"
    else:
        layer = "not registered"
    others = [{"name": os.path.splitext(os.path.basename(n))[0], "on": v == 0}
              for n, v in (layers or {}).items() if n != js]
    ini_path = find_ini(ini_dirs)
    cur, ini = "", {}
    if ini_path:
        try:
            ini = parse_ini(read_lines(ini_path))
            cur = ini.get("GENERAL", {}).get("PresetPath", "")
        except OSError:
            pass
    avail = [n for n in PRESETS if n == "Off" or os.path.isfile(preset_path(n, folder))]
    sl = sliders(cur, ini_path, ini) if cur and os.path.isfile(cur) else []
    keys = {}
    for k in ("KeyEffects", "KeyOverlay"):
        v = ini.get("INPUT", {}).get(k)
        if v:
            keys[k] = v
    keys["text"] = keys_text(ini)
    run = sim_running() if running is None else bool(running)
    return {"installed": installed, "json": js, "layer": layer, "others": others, "ini": ini_path or "",
            "preset_path": cur, "preset": preset_name(cur, folder), "presets": avail, "sliders": sl,
            "sim_running": run, "site": SITE, "keys": keys}


_VK = {145: "Scroll Lock", 36: "Home", 35: "End", 45: "Insert", 46: "Delete", 19: "Pause", 33: "Page Up", 34: "Page Down"}


def key_name(spec):
    """ReShade's 'vk,ctrl,shift,alt' -> 'Ctrl+Shift+D'."""
    try:
        p = [int(x) for x in str(spec).split(",")[:4]]
    except ValueError:
        return ""
    if not p or not p[0]:
        return ""
    vk = p[0]
    name = _VK.get(vk) or (chr(vk) if 48 <= vk <= 90 else f"F{vk - 111}" if 112 <= vk <= 135 else f"key {vk}")
    mods = [m for m, on in zip(("Ctrl", "Shift", "Alt"), (p + [0, 0, 0])[1:4]) if on]
    return "+".join(mods + [name])


def keys_text(ini):
    """What the keys in the headset do, from ReShadeVR.ini."""
    out = []
    eff = key_name(ini.get("INPUT", {}).get("KeyEffects", ""))
    if eff:
        out.append(f"{eff} turns the effects on/off")
    g = ini.get("GENERAL", {})
    ks = [x for x in (g.get("PresetShortcutKeys", "") or "").split(",") if x.strip()]
    ps = [x.strip() for x in (g.get("PresetShortcutPaths", "") or "").split(",") if x.strip()]
    for i in range(min(len(ks) // 4, len(ps))):
        n = key_name(",".join(ks[i * 4:i * 4 + 4]))
        if n:
            out.append(f"{n} = {os.path.splitext(os.path.basename(ps[i].replace(chr(92), '/')))[0]}")
    return "; ".join(out)


# ---------------------------------------------------------------- changes -----------------------------------------
def psq(s):
    return "'" + str(s).replace("'", "''") + "'"


def run_elevated(ps_body, log=print, timeout=120):
    """Run PowerShell lines as administrator after ONE Windows UAC prompt. Returns (ok, message).
    Declining the prompt changes nothing."""
    d = tempfile.mkdtemp(prefix="ic_reshade_")
    res = os.path.join(d, "result.txt")
    script = os.path.join(d, "do.ps1")
    with open(script, "w", encoding="utf-8-sig") as f:       # PowerShell 5 reads a BOM'd script as UTF-8
        f.write("$ErrorActionPreference = 'Stop'\r\ntry {\r\n" + "\r\n".join("  " + ln for ln in ps_body)
                + f"\r\n  'ok' | Out-File -Encoding ascii {psq(res)}\r\n}} catch {{\r\n"
                f"  $_.Exception.Message | Out-File -Encoding ascii {psq(res)}\r\n}}\r\n")
    inner = f'-NoProfile -ExecutionPolicy Bypass -File "{script}"'
    outer = ("try { $p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
             f"-ArgumentList {psq(inner)}; exit 0 }} catch {{ exit 1223 }}")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", outer], capture_output=True,
                           text=True, timeout=timeout, creationflags=NO_WINDOW)
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)
        return False, f"couldn't ask Windows: {e!r}"
    msg = ""
    try:
        with open(res, encoding="ascii", errors="replace") as f:
            msg = f.read().strip()
    except OSError:
        pass
    shutil.rmtree(d, ignore_errors=True)
    if r.returncode == 1223 and not msg:
        return False, "Windows permission was declined - nothing changed"
    if msg == "ok":
        return True, "done"
    return False, msg or f"didn't finish (code {r.returncode})"


class Busy(Exception):
    pass


def _guard(running):
    if running:
        raise Busy("Close iRacing first - ReShade can only be changed while the sim is closed")


def set_layer(on, running, log=print, elevate=run_elevated):
    """Switch the OpenXR layer on (0) or off (1). Never while the sim runs."""
    _guard(running)
    layers = _reg_layers()
    js = layer_json(layers)
    if on and not (os.path.isfile(js) and os.path.isfile(os.path.join(os.path.dirname(js), "ReShade64.dll"))):
        return False, "ReShade's OpenXR layer isn't installed on this PC"
    want = 0 if on else 1
    if layers is not None and js in layers and layers[js] == want:
        return True, "already " + ("on" if on else "off")
    ok, msg = elevate([f"New-ItemProperty -Path {psq('HKLM:' + chr(92) + REG_PATH)} -Name {psq(js)} -Value {want} "
                       "-PropertyType DWord -Force | Out-Null"], log)
    if ok:
        after = _reg_layers()
        if after is not None and after.get(js) != want:
            return False, "Windows said done but the layer didn't change"
        log(f"[reshade] OpenXR layer switched {'on' if on else 'off'}")
    else:
        log(f"[reshade] layer not changed: {msg}")
    return ok, ("ReShade " + ("on" if on else "off") + " for the headset") if ok else msg


def _write_protected(path, lines, log, elevate):
    """Write a file; if the folder is protected (Program Files), copy it in after one UAC prompt."""
    try:
        bak = path + ".before_ic"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
        write_lines(path, lines)
        return True, "saved"
    except PermissionError:
        pass
    tmp = os.path.join(tempfile.mkdtemp(prefix="ic_reshade_"), os.path.basename(path))
    write_lines(tmp, lines)
    bak = path + ".before_ic"
    ok, msg = elevate([f"if (-not (Test-Path -LiteralPath {psq(bak)})) {{ Copy-Item -LiteralPath {psq(path)} "
                       f"-Destination {psq(bak)} }}",
                       f"Copy-Item -LiteralPath {psq(tmp)} -Destination {psq(path)} -Force"], log)
    shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
    return ok, msg


def set_preset(name, running, ini_path=None, folder=PRESET_DIR, log=print, elevate=run_elevated):
    """Off / Day / Night: PresetPath in ReShadeVR.ini."""
    _guard(running)
    if name not in PRESETS:
        return False, "unknown preset"
    ini_path = ini_path or find_ini()
    if not ini_path:
        return False, f"{INI_NAME} not found in the iRacing folder"
    target = ensure_off_preset(folder) if name == "Off" else preset_path(name, folder)
    if not os.path.isfile(target):
        return False, f"{os.path.basename(target)} isn't in {folder}"
    lines = read_lines(ini_path)
    if os.path.normcase(ini_get(lines, "GENERAL", "PresetPath", "") or "") == os.path.normcase(target):
        return True, f"{name} already"
    ok, msg = _write_protected(ini_path, ini_set(lines, "GENERAL", "PresetPath", target), log, elevate)
    if ok:
        log(f"[reshade] preset -> {name}")
    return ok, (f"VR colour preset: {name}" if ok else msg)


def set_uniform(preset, fx, key, value, is_int, running, log=print, elevate=run_elevated):
    """One slider: the value in the preset file (the effect reads it the next time the sim starts)."""
    _guard(running)
    if not preset or not os.path.isfile(preset):
        return False, "no preset file"
    if not re.fullmatch(r"[\w.\-]+", fx or "") or not re.fullmatch(r"\w+", key or ""):
        return False, "bad name"
    v = fmt_value(float(value), is_int)
    lines = read_lines(preset)
    ok, msg = _write_protected(preset, ini_set(lines, fx, key, v), log, elevate)
    return ok, ("saved" if ok else msg)


# ---------------------------------------------------------------- NVIDIA Digital Vibrance ------------------------
def vibrance_args(script_text, level, display, template=""):
    """The command-line arguments for the owner's nv_vibrance.py. A template from the settings wins
    ("{level}", "{display}" filled in); else the script's own argparse flags are used when it has them
    (--level / --vibrance / --percent and --display / --monitor); else just the level."""
    if template:
        return [a.format(level=level, display=display) for a in template.split()]
    flags = re.findall(r"add_argument\(\s*['\"](--[\w-]+)['\"]", script_text or "")
    lv = next((f for f in flags if f.lstrip("-") in ("level", "vibrance", "percent", "value", "pct")), None)
    dp = next((f for f in flags if f.lstrip("-") in ("display", "monitor", "output", "name")), None)
    if lv:
        return [lv, str(level)] + ([dp, display] if dp and display else [])
    return [str(level)] + ([display] if display and re.search(r"argv\[2\]", script_text or "") else [])


def apply_vibrance(level, display="DISPLAY1", template="", script=VIBRANCE_SCRIPT, log=print):
    if not os.path.isfile(script):
        return False, "nv_vibrance.py not found"
    try:
        with open(script, encoding="utf-8-sig", errors="replace") as f:
            txt = f.read()
    except OSError as e:
        return False, repr(e)
    level = max(0, min(100, int(level)))
    py = sys.executable
    if py.lower().endswith("pythonw.exe"):
        cand = py[:-len("pythonw.exe")] + "python.exe"
        py = cand if os.path.isfile(cand) else py
    cmd = [py, script] + vibrance_args(txt, level, display, template)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
    except Exception as e:
        return False, repr(e)
    out = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    tail = out[-1] if out else ""
    if r.returncode == 0:
        log(f"[vibrance] {display} {level}%" + (f" ({tail})" if tail else ""))
        return True, f"Vibrance {level}% on {display}"
    log(f"[vibrance] failed ({r.returncode}): {tail}  cmd: {' '.join(cmd[1:])}")
    return False, tail or f"failed ({r.returncode})"

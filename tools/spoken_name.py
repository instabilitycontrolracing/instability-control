"""The driver's first name for rendering voice lines: ENGINEER_DRIVER_NAME, else the app's driver_name setting
(engineer_settings.json next to the program), else "Driver"."""
import json, os


def spoken_name():
    n = os.environ.get("ENGINEER_DRIVER_NAME", "").strip()
    if not n:
        try:
            p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engineer_settings.json")
            with open(p, encoding="utf-8-sig") as f:
                n = (json.load(f).get("driver_name") or "").strip()
        except (OSError, ValueError, AttributeError):
            n = ""
    return n or "Driver"


NAME = spoken_name()

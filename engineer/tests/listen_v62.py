"""Builds every new v62 line once with sample values (real library where recorded, stand-in voice otherwise)
and writes one wav to listen to: Desktop\\Engineer Voice - Listen\\v62 new calls.wav"""
import os, sys
import numpy as np, soundfile as sf
from engineer.engine import VOCAB, PRESET
from engineer.voice import Voice

SAMPLES = [
    ("limiter_on", {}), ("stall_close", {}), ("repair_long", {"n": 34}), ("repair_left", {"n": 10}), ("stop_go_go", {}),
    ("limiter_off", {}), ("b2_stop_time", {"n": 31}), ("pit_out_behind", {"P": 6, "car": "44"}),
    ("pit_out_ahead", {"P": 5, "car": "7"}), ("pit_rejoin_pos", {"P": 4}),
    ("req_tyres", {"_variant": 2}), ("req_tyres", {"_variant": 4}), ("req_fuel_add", {"n": 20, "fuel unit": 2}),
    ("req_fuel_end", {"n": 38, "fuel unit": 2}), ("req_press", {"dec": 0.5, "_variant": 2}), ("req_fast_repair", {"_variant": 1}),
    ("req_compound", {"_variant": 1}), ("req_clear", {}),
    ("sof", {"n": 2450}), ("drv_info", {"car": "44", "n": 2780, "lic": "A", "dec": 3.41}),
    ("irating_gain", {"n": 42, "_variant": 1}), ("irating_target", {"P": 7}), ("mark_ok", {"car": "91"}),
    ("marked_near", {"car": "91", "_variant": 1}), ("low_sr_near", {"car": "12", "_variant": 2}),
    ("watch_report", {"car": "44", "gap": 3.4, "time": 138.6}), ("car_lap", {"car": "7", "time": 137.9}),
    ("car_inc", {"car": "91", "n": 9}),
    ("engine_hot", {}), ("oil_low", {}), ("fuel_pressure", {}), ("damage_report", {"n": 12}), ("pedal_check", {}),
    ("b2_pit_window_opens", {}), ("fuel_target", {"dec": 3.1, "fuel unit": 2}), ("grid_low_fuel", {}),
    ("b2_car_on_push_lap_behind_you", {}), ("b2_push_lap_traffic_ahead", {}), ("b2_out_lap_find_space", {"gap": 2.1}),
    ("b2_track_getting_faster_rubber", {}), ("sector_off", {"sector": 2, "n": 4}), ("b2_push_lap_sector_good", {"sector": 1}),
    ("b2_track_temperature_rising", {}), ("track_temp", {"n": 34}), ("air_temp", {"n": 22}), ("wind_strong", {"n": 32}),
    ("b2_wear_report_one_tire_worn", {"tyre corner": "front left", "percent": 64}), ("tyres_critical", {"percent": 28}),
    ("tyres_left", {"percent": 61}), ("b2_repeat_last_message", {}), ("timer_set", {"n": 10, "_variant": 1}),
    ("timer_done", {}), ("time_now", {"time": 9 * 60 + 5}), ("chat_sent", {}),
]

v = Voice(VOCAB, PRESET, output=False, log=print)
v.fuel_metric = True
out, sr, bad = [], v.sr, []
for sid, f in SAMPLES:
    a, text = v.build(sid, dict(f))
    kind = "recorded" if sid in v.lines else "stand-in"
    if a is None:
        bad.append(sid); print(f"MISSING {sid}"); continue
    print(f"{kind:9} {sid:32} {text}")
    out += [a, np.zeros(int(0.5 * sr), np.float32)]
path = os.path.join(os.path.expanduser("~"), "Desktop", "Engineer Voice - Listen", "v62 new calls.wav")
os.makedirs(os.path.dirname(path), exist_ok=True)
sf.write(path, np.concatenate(out), sr)
print(f"saved {path}: {len(SAMPLES) - len(bad)} lines, missing {bad}")

"""Being towed back to the pits: flags, passes and gaps stay quiet; pit / damage lines still get through (2026-10-29)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engineer import voice


def test_tow_filter():
    for sid in ("blue_flag", "yellow_sector", "rc", "pos_pitting", "gaps_each_lap", "three_wide", "taking_lead"):
        assert not voice.tow_ok(sid), sid
    for sid in ("damage_report", "tb_pit_out", "req_fuel_add", "radio_check", "engine_hot", "fuel_target"):
        assert voice.tow_ok(sid), sid

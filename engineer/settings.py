"""Engineer settings, saved to settings.json next to the program."""
import json, os
from dataclasses import dataclass, asdict, field

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "engineer_settings.json")


@dataclass
class Settings:
    # sound
    volume: float = 1.0
    radio_strength: float = 1.0      # 0 = clean, 1 = radio test 2 (Angelo's pick), 2 = TV team radio
    device: str = ""                 # "" = Windows default output
    mic_device: str = ""             # "" = Windows default microphone
    # calls
    spotter: bool = True
    gaps: bool = True
    gaps_every: int = 2
    hold_in_corners: bool = True
    formation_brief: bool = True     # strategist rundown on the formation lap
    # v62 calls (DRE parity) - all on except the shift beep and the per-lap readout
    calls_pitlane: bool = True       # limiter, pit stall, repair countdown, release, where we come out
    calls_drivers: bool = True       # strength of field, marked drivers nearby
    low_sr_warn: bool = True         # low safety rating driver next to you in a race
    calls_health: bool = True        # engine temps / pressures, stall, damage, pedal checks
    shift_beep: bool = False         # short beep at the shift point
    shift_pitch: int = 1400          # Hz (Race Control page, 2026-10-24)
    shift_volume: float = 0.25       # 0..1, hard-capped in the player so it can never blast
    shift_point: float = 1.0         # x the car's shift-light RPM (0.95 = a bit earlier)
    shift_length: int = 60           # ms
    race_control: bool = True        # race director clips at session start / grid / formation / green
    race_control_volume: float = 0.8
    overlay_radio: bool = True       # show what the team says as captions on the Grandstand overlay
    # crowd (2026-10-24): trackside crowd (Race Control page), files in CrewChiefVoices\Trackside
    crowd_on: bool = True
    crowd_volume: float = 0.3        # master, 0..1
    crowd_max_db: float = -18.0      # hard output ceiling (dBFS peak), kept between -48 and -6
    crowd_mute: bool = False
    crowd_pa: bool = True            # track PA announcer near the start/finish
    crowd_heli: bool = True          # TV helicopters
    crowd_mute_pits: bool = True     # silent in the garage and the pit lane
    crowd_duck: bool = True          # quieter while anyone talks on the radio
    crowd_others: bool = True        # react to other drivers' passes near you
    crowd_intensity: int = 100       # 0 = polite clapping ... 100 = Le Mans at 3 a.m.
    crowd_max_voices: int = 6
    calls_fuel_extras: bool = True   # fuel window, fuel target per lap, low fuel on the grid
    calls_practice_traffic: bool = True
    calls_sectors: bool = True       # "sector two, four tenths off" / green sectors on a push lap
    calls_weather: bool = True       # track / air temperature changes, strong wind
    calls_tyres: bool = True
    calls_racecraft: bool = True     # striking distance, where to pass/defend, rival trouble, slow car ahead, projected finish...
    pit_tones: bool = True           # beeps while too fast into the pit lane; two pips when the limiter goes on
    hold_for_chat: bool = True       # hold non-urgent talk while someone is on iRacing voice chat
    net_warnings: bool = True        # "connection is bad" when lag spikes
    auto_telemetry: bool = True      # start/stop iRacing's .ibt recording when you get in / out of the car
    fuel_buffer_laps: float = 0.0    # extra fuel (in laps) added to every fill-to-the-end
    sig_overlap: bool = False        # tone when brake and throttle overlap
    sig_spray: bool = False          # pulses for a car close ahead in heavy rain spray
    sig_revlimit: bool = False       # beep at the shift-light blink RPM
    sig_launch: bool = False         # tone following the class leader's revs before a rolling start         # tyre wear report at stops, critical wear
    chat_enabled: bool = True        # "send good luck" types into iRacing's chat
    low_sr_below: float = 2.0        # warn about drivers under this safety rating
    low_sr_rookies: bool = False     # ...and rookie (R licence) drivers
    sector_alert: float = 0.35       # seconds slower than your usual before a sector call
    traffic_warn: float = 2.5        # practice: seconds behind you for a push-lap warning (ahead: +1.5)
    press_unit: str = "psi"          # "pressures up one" = one step in psi or kPa
    press_step: float = 1.0
    lap_readout: list = field(default_factory=list)   # read out every lap: "time", "position", "fuel", "gaps"
    binds: dict = field(default_factory=dict)          # wheel button -> radio command {"say_again": {"device", "button"}}
    spotter_voice: str = "Max"       # built-in spotter ("Max", "Jess", "Leo"); "" = the engineer calls traffic;
                                     # "cc:Clare" = a spotter from the user's own CrewChief install (optional)
    strat_voice: str = "chatterbox"  # strategist voice library: "chatterbox" (calm), "f5", "standin"
    # buttons: {"device": name, "button": index} or None
    radio_button: dict = None
    team_button: dict = None
    # testing: a replay of your own race drives the engineer as if live (off for normal use)
    replay_test: bool = False
    # driver
    driver_name: str = ""            # first name the team uses; recorded lines with another name are skipped  # beta (2026-10-24): was "Angelo"
    # general
    autostart_engine: bool = True    # start listening for iRacing as soon as the window opens
    start_with_windows: bool = False
    splash: bool = True              # play the intro
    # team AI (local model) - only runs when not driving
    team_enabled: bool = True
    team_in_pitbox: bool = False     # allow it while parked in the pit box in practice/qualifying
    team_gpu: str = ""               # "" = automatic
    team_debrief_auto: bool = True   # memory (2026-10-24): open the debrief in the Team tab after a race, once the car is stopped
    # team meeting by voice
    meet_voice: bool = True          # the team answers out loud
    meet_live: bool = False          # open mic (hands-free) in the Team tab
    # iPad / tablet (home Wi-Fi)
    remote_on: bool = True
    remote_port: int = 8770
    remote_token: str = ""
    # series prep
    prep_series: str = "imsa_open"
    prep_car: str = "bmwlmdh"
    prep_track: str = "lemans full"

    @classmethod
    def load(cls):
        s = cls()
        try:
            d = json.load(open(PATH, encoding="utf-8"))
            if "driver_name" not in d:       # beta (2026-10-24): a settings file from before the name setting existed is the
                d["driver_name"] = "Angelo"  # owner's own (the library was recorded with his name) - keep it as it was
            for k, v in d.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        return s

    def save(self):
        try:
            json.dump(asdict(self), open(PATH, "w", encoding="utf-8"), indent=1)
        except OSError:
            pass

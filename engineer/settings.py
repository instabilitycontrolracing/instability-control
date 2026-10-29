"""Engineer settings, saved to settings.json next to the program."""
import json, os, threading
from dataclasses import dataclass, field, asdict

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(os.path.dirname(HERE), "engineer_settings.json")
_SAVE_LOCK = threading.Lock()


@dataclass
class Settings:
    # sound
    volume: float = 1.0
    radio_strength: float = 1.0      # 0 = clean, 1 = radio test 2 (the default pick), 2 = TV team radio
    device: str = ""                 # "" = Windows default output
    mic_device: str = ""             # "" = Windows default microphone
    # calls
    spotter: bool = True
    # spotter timing (2026-10-26, DRE parity): iRacing decides "alongside"; these shape when it's called
    spot_call_ms: int = 120          # a new car-left / car-right must hold this long before it's called (no flicker chatter)
    spot_clear_ms: int = 350         # "clear" waits this long, so a wobble at the edge doesn't call clear-then-left again
    spot_still_s: float = 5.0        # "still there" after this long alongside
    spot_min_kmh: int = 30           # quiet below this speed (grid, pit exit crawl)
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
    shift_lead: float = 0.18         # seconds early: beep when the revs will hit the shift point this soon (2026-10-26)
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
    crowd_ambience: bool = True      # weather, night, bridges, pit stops (2026-10-26, #204-206)
    crowd_heli_cabin: bool = True    # helicopter camera: the sound from inside the chopper (2026-10-26, #41)
    crowd_mute_pits: bool = True     # silent in the garage and the pit lane
    crowd_duck: bool = True          # quieter while anyone talks on the radio
    crowd_others: bool = True        # react to other drivers' passes near you
    crowd_intensity: int = 100       # 0 = polite clapping ... 100 = Le Mans at 3 a.m.
    crowd_max_voices: int = 12
    crowd_cam_delay: float = 1.8     # replays: seconds the crowd waits after a camera change (the picture cuts late)  # crowd (2026-10-25)
    # sound mix (2026-10-25): Settings > Sound mix - Voicemeeter A1 (headphones) / B1 (TV stream) + Equalizer APO files
    snd_hp_eq: bool = True           # the Bose 700 correction on the headphones
    snd_hp_db: float = 0.0           # headphone level (Voicemeeter A1), -40..+6 dB
    snd_tv_db: float = 0.0           # TV stream level (Voicemeeter B1), -60..+6 dB
    snd_tv_game: bool = True         # game sound to the TV stream
    snd_tv_mute: bool = False
    bcast_on: bool = True            # 2026-10-29 (#515): TV + stream get their own, rougher, louder radio with key-ups
    bcast_grit: float = 1.0          # broadcast radio distortion 0..2
    bcast_db: float = 6.0            # broadcast radio loudness, 0..+12 dB (peak-limited)
    bcast_keyup: bool = True         # key-up click + squelch tail on the broadcast
    bcast_crowd: bool = True         # the crowd on the broadcast
    bcast_crowd_db: float = 0.0
    snd_tv_delay_ms: int = 0         # 2026-10-26 (#303): lip-sync - hold the TV sound back so it lines up with the picture
    snd_engine: int = 0              # car sound: engine body boost 0..100
    snd_detail: int = 0              # car sound: tyre / detail boost 0..100
    shaker_on: bool = False          # bass shaker (2026-10-26, #211)
    shaker_device: str = ""
    shaker_gain: float = 0.6
    shaker_engine: bool = True
    shaker_shifts: bool = True
    shaker_kerbs: bool = True
    shaker_abs: bool = True
    shaker_impacts: bool = True
    shaker_limiter: bool = True      # D10 (#248): pit limiter buzz
    radio_replay: bool = True        # W3 (#253): keep your engineer's radio and play it back in the replay
    radio_replay_mine_only: bool = True
    radio_replay_vol: float = 0.9
    fan_on: bool = False             # D12 / H4 (#250, #287): speed fan
    fan_kind: str = "url"            # url | hue
    fan_url: str = ""                # e.g. http://192.168.1.60/light/0?turn=on&brightness={pct}
    fan_plug: str = ""               # Hue smart plug id (fan_kind = hue)
    fan_from: int = 40               # km/h where it starts
    fan_full: int = 280              # km/h for full speed
    pedal_on: bool = False           # D11 (#249): a second transducer (pedals / haptic cushion)
    pedal_device: str = ""
    pedal_gain: float = 0.6
    pedal_engine: bool = False
    pedal_shifts: bool = False
    pedal_kerbs: bool = True
    pedal_abs: bool = True
    pedal_impacts: bool = False
    pedal_limiter: bool = True
    snd_per_car: bool = True         # remember the car sound per car (2026-10-26, #209)
    snd_car_profiles: dict = field(default_factory=dict)   # car path -> {"engine": 0..100, "detail": 0..100}
    snd_tv_ht: bool = True           # 2026-10-26: home-theatre 2.1 tuning on the TV while a replay plays
    radio_realism: bool = True       # team radio: more static in rain, dips on the far side of long tracks (2026-10-26, #210)
    snd_keep_default: bool = True    # keep Windows' default output on Voicemeeter Input (Apollo moves it to CABLE)
    radio_pitwall: bool = True
    cockpit_on: bool = True          # D1-D3 cockpit layer (#239-#241), only from your own recordings
    cockpit_volume: int = 50
    cockpit_wind: bool = True
    cockpit_rain: bool = True
    cockpit_heart: bool = False      # D2: heartbeat + breathing in tense moments (off by default)       # D6 (#244): the pit wall behind the engineer (needs the recording)
    audio_mode: str = "broadcast"    # driving (VR, fastest: straight to the Yeti) | broadcast (Voicemeeter + TV copy)
    lights_on: bool = False          # flag lights (#236)
    lights_kind: str = "hue"         # hue | wled | govee
    lights_host: str = ""            # the light's (or Hue bridge's) IP address
    lights_bri: int = 80             # flag brightness %
    lights_idle: int = 30            # calm room light between flags, % of that
    hue_user: str = ""               # the key the Hue bridge gives this app when paired
    hue_lights: str = ""
    hue_sync: bool = False           # the Hue rig (#239): the lights follow the race / the picture
    hue_left: str = ""               # light ids for each place
    hue_right: str = ""
    hue_desk: str = ""
    hue_left_job: str = "both"       # flags | picture | both | off
    hue_right_job: str = "both"
    hue_desk_job: str = "picture"
    hue_picture_fps: int = 4             # Hue light numbers to use, e.g. "1,2" (empty = all)
    hue_picture_fps_driving: int = 2     # 2026-10-29 (efficiency): screen samples a second while you drive (live, in the car)
    snd_trackside_space: bool = True
    snd_driving_space: bool = True   # D4/D5 (#242/#243): your car echoes off the pit wall, bridges and tunnels # trackside / TV cameras: the circuit's reflections on the game's cars (#229)
    crowd_helmet: bool = True
    crowd_hero: str = ""             # C1 (#283): car number the crowd cheers for everywhere (empty = just you)        # driving: the crowd through your helmet (#230)
    snd_tv_night: bool = False       # late-night mode on the TV: quiet bits up, loud bits held (2026-10-26, #208)
    snd_tv_ht_live: bool = True      # ...and while you drive too (2026-10-26, requested: "on all the time")
    calls_fuel_extras: bool = True   # fuel window, fuel target per lap, low fuel on the grid
    calls_practice_traffic: bool = True
    calls_sectors: bool = True       # "sector two, four tenths off" / green sectors on a push lap
    calls_weather: bool = True       # track / air temperature changes, strong wind
    calls_tyres: bool = True
    calls_fight_coach: bool = True   # in a fight: where the car ahead / behind is quicker, corner by corner, and what to change
    calls_racecraft: bool = True     # striking distance, where to pass/defend, rival trouble, slow car ahead, projected finish...
    race_mode: bool = False          # off by default for new installs (it closes other apps); #353 (2026-10-27): close non-essential apps while the sim runs, reopen them after (racemode.py)
    radio_beep: bool = True          # chirp when the radio button goes down / comes up (2026-10-26)
    pit_tones: bool = True           # beeps while too fast into the pit lane; two pips when the limiter goes on
    hold_for_chat: bool = True       # hold non-urgent talk while someone is on iRacing voice chat
    net_warnings: bool = True        # "connection is bad" when lag spikes
    auto_telemetry: bool = True      # iRacing's .ibt recording on whenever you're in the car (2026-10-27: left on after)
    # telemetry vault (2026-10-27, vault.py): every recording kept on this PC and in Google Drive
    vault_on: bool = True            # keep a checked copy of every recording in the archive folder
    vault_dir: str = ""              # "" = automatic (the drive with the most room, e.g. E:\RaceEngineer\telemetry)
    vault_drive_on: bool = False     # off by default for new installs (opt-in upload to your own Drive) ...and a packed copy + session summary in Google Drive
    vault_drive_dir: str = "G:\\My Drive\\Instability Control\\Telemetry"   # personal Drive - never H: (business)
    vault_drive_quota_gb: float = 8.0   # Drive cap; when full the oldest packed copies there make room
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
    launch_with_sim: list = field(default_factory=list)   # 2026-10-26: programs started when iRacing starts (paths)
    launch_with_sim_on: bool = True
    spotter_voice: str = "Max"       # built-in spotter ("Max", "Jess", "Leo"); "" = the engineer calls traffic;
                                     # "cc:Clare" = a spotter from the user's own CrewChief install (optional)
    strat_voice: str = "chatterbox"  # strategist voice library: "chatterbox" (calm), "f5", "standin"
    # buttons: {"device": name, "button": index} or None
    radio_button: dict = None
    team_button: dict = None
    # testing: a replay of your own race drives the engineer as if live (off for normal use)
    replay_test: bool = False
    # driver
    driver_name: str = ""            # first name the team uses; recorded lines with another name are skipped
    driver_name_say: str = ""        # #542: the name typed the way it sounds ("Ahn-JEH-lo"), for the voice; "" = as written
    # general
    autostart_engine: bool = True    # start listening for iRacing as soon as the window opens
    start_with_windows: bool = False
    splash: bool = True              # play the intro
    # VR colour (#308, 2026-10-27): ReShade itself lives in its own files (Settings > General > VR colour)
    vibrance_keep: bool = False      # put NVIDIA Digital Vibrance back at app start and whenever the sim starts
    vibrance_level: int = 70         # percent, as in the NVIDIA control panel
    vibrance_display: str = "DISPLAY1"
    vibrance_args: str = ""          # "" = work out nv_vibrance.py's arguments; else e.g. "--level {level} --display {display}"
    # team AI (local model) - only runs when not driving
    team_enabled: bool = True
    team_in_pitbox: bool = False     # allow it while parked in the pit box in practice/qualifying
    team_gpu: str = ""               # "" = automatic
    team_debrief_auto: bool = True   # memory (2026-10-24): open the debrief in the Team tab after a race, once the car is stopped
    fx_auto: bool = True             # forensics (2026-10-27): analyse new recordings in the background (never while driving)
    fx_hours: float = 18.0           # the night review takes the recordings of the last N hours (same car + track)
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
            with open(PATH, encoding="utf-8-sig") as f:       # #322: a file saved with a BOM must not load as defaults
                d = json.load(f)
            if "driver_name" not in d:       # beta (2026-10-24): a settings file from before the name setting existed:
                d["driver_name"] = ""        # no name set (the voice library's recorded name is worked out from the library)
            for k, v in d.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # #322: unreadable file - keep a copy before the next save writes defaults over the button bindings
            try:
                import shutil, time
                shutil.copy2(PATH, PATH[:-5] + time.strftime(".unreadable_%Y%m%d_%H%M%S.json"))
            except OSError:
                pass
        return s

    def save(self):
        """Write to a temp file and swap it in, so a crash mid-save never leaves a cut-off settings file
        (which would load as defaults next time and lose the button bindings - #322). No BOM."""
        tmp = PATH + ".tmp"
        with _SAVE_LOCK:
            self._save_to(tmp)

    def _save_to(self, tmp):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=1)
            os.replace(tmp, PATH)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            try:                                  # swap refused (file held open by a scanner): plain write as before
                with open(PATH, "w", encoding="utf-8") as f:
                    json.dump(asdict(self), f, indent=1)
            except OSError:
                pass

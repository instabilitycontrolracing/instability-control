import os, glob
D = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
BASE = os.path.join(D, "baseline")
OUTROOT = os.path.join(D, "engine_tests")
LINES = [
    "Box, box. Box this lap, box this lap.",
    "P3, P3. Car behind at 1.4.",
    "Gap to car ahead 1.2. He is struggling on exit of turn four.",
    "Full course yellow, full course yellow. Safety car out.",
    "Fuel is good to the end. No saving needed.",
    "Last lap, Angelo. Last lap. Keep pushing.",
    "P2, P2. Great job, Angelo.",
    "Black and white flag, black and white flag. Turn four.",
]
LINES = [(t, "en") for t in LINES] + [
    ("Sorpasso! Bellissimo!", "it"),
    ("Giro veloce! Giro veloce! Bravo, Angelo!", "it"),
    ("Vittoria! Vittoria, Angelo! Mamma mia, che gara! Grandissimo!", "it"),
    ("Abbiamo vinto! Abbiamo vinto! Sei il migliore, Angelo, il migliore!", "it"),
]
# single reference for one-sample engines (built by make_refs.py)
REF_WAV = os.path.join(D, "ref_single.wav")
# F5 needs the exact words spoken in its reference clip
F5_REF_WAV = os.path.join(D, "v3_sidon", "27.wav")
F5_REF_TEXT = "Hamilton behind with DRS. No moving under braking, turn four. No moving under braking for turn four."
BASELINE = sorted(glob.glob(os.path.join(BASE, "engineer_*.wav")))

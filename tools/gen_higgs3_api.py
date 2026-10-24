import os, sys, json, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__))
from test_lines import OUTROOT
key = open(os.path.join(os.path.dirname(__file__), "boson_key.txt")).read().strip()
VOICE = sys.argv[1] if len(sys.argv) > 1 else "oliver"
out = os.path.join(OUTROOT, f"higgs3_{VOICE}"); os.makedirs(out, exist_ok=True)
# same 12 lines, with acting tags written in
TAGGED = [
    "<|emotion:determination|>Box, box. <|prosody:pause|> Box this lap, box this lap.",
    "<|prosody:speed_fast|>P3, P3. Car behind at 1.4.",
    "<|emotion:contemplation|>Gap to car ahead 1.2. <|prosody:pause|> He is struggling on exit of turn four.",
    "<|emotion:determination|>Full course yellow, full course yellow. Pace car out.",
    "<|emotion:contentment|>Fuel is good to the end. No saving needed.",
    "<|emotion:determination|>Last lap, Angelo. Last lap. <|prosody:expressive_high|>Keep pushing.",
    "<|emotion:pride|>Checkered flag. P2, P2. <|emotion:elation|>Great job, Angelo.",
    "<|prosody:speed_fast|>Black and white flag, black and white flag. Turn four.",
    "<|emotion:elation|><|style:shouting|>Sorpasso! Bellissimo!",
    "<|emotion:enthusiasm|>Giro veloce! Giro veloce! Bravo, Angelo!",
    "<|emotion:elation|><|style:shouting|>Vittoria! Vittoria, Angelo! <|emotion:elation|>Mamma mia, che gara! Grandissimo!",
    "<|emotion:elation|><|style:shouting|>Abbiamo vinto! Abbiamo vinto! <|emotion:pride|>Sei il migliore, Angelo, il migliore!",
]
def call(text):
    body = json.dumps({"model": "higgs-tts-3", "input": text, "voice": VOICE}).encode()
    req = urllib.request.Request("https://api.boson.ai/v1/audio/speech", data=body, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    for attempt in range(8):
        try:
            return urllib.request.urlopen(req, timeout=120).read()
        except urllib.error.HTTPError as e:
            msg = e.read()[:300]
            if e.code == 429:
                time.sleep(10 * (attempt + 1)); continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
    raise RuntimeError("rate limited too many times")
for i, t in enumerate(TAGGED, 1):
    dst = os.path.join(out, f"{i:02d}.mp3")
    if os.path.exists(dst): continue
    try:
        open(dst, "wb").write(call(t)); print(VOICE, i, "ok", flush=True)
    except Exception as e:
        print(VOICE, i, "FAIL", e, flush=True)
    time.sleep(3)
print("ALL DONE", VOICE, flush=True)

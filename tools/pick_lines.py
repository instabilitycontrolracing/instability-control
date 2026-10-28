import json, os, sys
d = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices", "Engineer1")
items = json.load(open(os.path.join(d, "TVoice chop_transcript.json"), encoding="utf-8"))
keep = []
for i, it in enumerate(items):
    if it.get("spk") != "A" or it["end"] > 318:
        continue
    # skip lines whose neighbours (another speaker) start/end within 0.25s - likely overlap
    prev = items[i - 1] if i > 0 else None
    nxt = items[i + 1] if i + 1 < len(items) else None
    if prev and prev.get("spk") != "A" and it["start"] - prev["end"] < 0.25:
        continue
    if nxt and nxt.get("spk") != "A" and nxt["start"] - it["end"] < 0.25:
        continue
    if it["end"] - it["start"] < 2.0:
        continue
    keep.append(dict(start=it["start"], end=it["end"], text=it["text"]))
json.dump(keep, open(os.path.join(d, "engineer_lines.json"), "w", encoding="utf-8"), indent=1)
tot = sum(k["end"] - k["start"] for k in keep)
print(f"{len(keep)} lines kept, {tot:.1f}s total")
for k in keep:
    print(f"{k['start']:7.2f}-{k['end']:7.2f}  {k['text']}")

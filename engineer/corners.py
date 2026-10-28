"""Corner names from CrewChief's track map, matched to the clips we rendered."""
import json, re


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"


def _pretty(raw):
    n = raw.replace("_", " ").strip().title()
    n = re.sub(r"(\D)(\d+)$", r"\1 \2", n)
    n = {"Radillion": "Raidillon", "Lesmos 1": "Lesmo 1", "Lesmos 2": "Lesmo 2"}.get(n, n)
    return n.replace("Nascar", "NASCAR")


class Corners:
    def __init__(self, landmarks_path, corner_blocks, exists=None):
        self.data = {}
        self.blocks = corner_blocks  # key -> clip
        # exists(clip) -> is the clip rendered? A named corner listed in the manifest but not rendered yet (the render
        # list is rebuilt before the render runs) falls back to its "Turn N" clip instead of a silent hole.
        self.exists = exists or (lambda clip: True)
        try:
            d = json.load(open(landmarks_path, encoding="utf-8-sig"))
            for t in d.get("trackLandmarksData", []):
                if t.get("irTrackName"):
                    self.data[t["irTrackName"].lower()] = t.get("trackLandmarks", [])
        except Exception as e:
            print("[corners] no track map:", e)
        self.marks = []

    def set_track(self, track_name):
        """track_name = iRacing WeekendInfo.TrackName, e.g. 'spa up', 'lemans full'."""
        key = (track_name or "").lower().replace("_", " ")
        lms = self.data.get(key, [])
        self.marks = []
        for i, lm in enumerate(lms):
            names = lm.get("landmarkNames", [])
            pick = None
            for raw in names:  # a named corner we have a clip for
                if not re.match(r"(?i)^turn_?\d+", raw):
                    k = slug(_pretty(raw))
                    if k in self.blocks and self.exists(self.blocks[k]):
                        pick = k; break
            if not pick:
                for raw in names:
                    m = re.match(r"(?i)^turn_?(\d+)", raw)
                    tk = f"turn_{int(m.group(1))}" if m else None
                    if tk and tk in self.blocks and self.exists(self.blocks[tk]):
                        pick = tk; break
            if pick:
                self.marks.append((lm["distanceRoundLapStart"], lm["distanceRoundLapEnd"], pick))
        self.marks.sort()
        return len(self.marks)

    def at(self, dist_m, slack=60):
        """Corner the car is in (or just left), by lap distance in meters."""
        best = None
        for a, b, k in self.marks:
            if a - 20 <= dist_m <= b + slack:
                best = k
        return best

    def next_after(self, dist_m):
        for a, b, k in self.marks:
            if a > dist_m:
                return k
        return self.marks[0][2] if self.marks else None

    def nearest_behind(self, dist_m, within=400):
        """Last corner the car passed (used for 'black and white flag, [corner]' after the fact)."""
        best = None
        for a, b, k in self.marks:
            if a - 20 <= dist_m and dist_m - b <= within:
                best = k
        return best

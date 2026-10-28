"""Strategist (Chatterbox): spelled numbers for every library clip with a digit -> Strategist/chatterbox/say_numbers.json
and only_numbers.txt (render_strategist.py --say / --only). The library keeps the real wording.
Split out of overnight_prep.py (2026-10-28) so a render of new lines can run it without overnight_prep's one-off
engineer re-record step. usage: python tools/strat_say_numbers.py"""
import os, sys, json, re
R = os.path.join(os.environ["USERPROFILE"], "Documents", "CrewChiefVoices")


def main():
    sys.path.insert(0, R)
    from engineer.strat_lines import units, fill_values, EXAMPLE, CARRIER
    O = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    TT = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
    def w(n):
        n = int(n)
        if n < 20: return O[n]
        if n < 100: return TT[n // 10] + ("" if n % 10 == 0 else "-" + O[n % 10])
        if n < 1000: return O[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + w(n % 100))
        return " ".join(O[int(c)] for c in str(n))
    def spell(t):
        t = re.sub(r"\b(GT|LMP)(\d)", r"\1§\2", t)          # class names stay as they are
        t = re.sub(r"\bP(\d+)", lambda m: "P " + w(m.group(1)), t)
        t = re.sub(r"(\d+)\.(\d+)", lambda m: w(m.group(1)) + " point " + " ".join(w(c) for c in m.group(2)), t)
        t = re.sub(r"(?<!§)\d+", lambda m: w(m.group(0)), t)
        return t.replace("§", "")
    say = {}
    for key, sent in units():
        t = sent
        for f, ex in EXAMPLE.items(): t = t.replace(f"[{f}]", ex)
        if spell(t) != t: say[key] = spell(t)
    for kind, vals in fill_values().items():
        for v in vals:
            t = CARRIER[kind].format(v)
            if spell(t) != t: say[f"{kind}:{v}"] = spell(t)
    S = os.path.join(R, "Strategist", "chatterbox")
    json.dump(say, open(os.path.join(S, "say_numbers.json"), "w", encoding="utf-8"), indent=0)
    open(os.path.join(S, "only_numbers.txt"), "w", encoding="utf-8").write("\n".join(say))
    print(f"strategist: {len(say)} clips with numbers get spelled words")
    print("  e.g.", list(say.items())[:3])


if __name__ == "__main__":
    main()

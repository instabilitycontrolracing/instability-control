"""The rain brain's new engineer lines (#591, 2026-10-30) - PENDING THE OWNER'S APPROVAL.

Not on any render list and not in lines_new.py, so the stand-in voice never says them. engineer/rain_brain.py plays a
line only once it is rendered into the engineer's library; until then the answer is shown as text.
To approve: list the clip ids (or "all") in tools/rain_approved.txt, then render as usual (tools/vocab_spec.py).
Numbers are fills ([laps], [percent]) said as words by the number clips ("three laps", "forty percent").
"""

# (clip id, wording). [laps] = a number clip (spoken as a word: "three"), [percent] = a number clip.
# Not on any render list and not in lines_new (so the stand-in voice never says them): they play once rendered.
PENDING = [
    # will it rain any more?
    ("rb_more_heavier", "It's still raining, and it's getting heavier."),
    ("rb_more_easing", "It's still raining, but it's easing off."),
    ("rb_more_steady", "Still raining. About the same as before."),
    ("rb_more_stopped", "Rain has stopped for now. We don't get a live forecast, so I'll call it if it starts again."),
    ("rb_more_none_fc", "No rain now. The forecast for this race was [percent] percent."),
    ("rb_more_none", "No rain now. We don't get a live forecast, so I'll call it if it starts."),
    ("rb_more_static", "No change coming. The weather is fixed for this session."),
    # is it drying / getting wetter?
    ("rb_trend_drying", "The track is drying."),
    ("rb_trend_wetter", "The track is getting wetter."),
    ("rb_trend_steady", "The track is steady. Not drying, not getting wetter."),
    ("rb_trend_unsure", "Too early to say. Give me a couple more minutes."),
    # when do we go to slicks / wets?
    ("rb_slicks_now_box", "Slicks are faster now. Box this lap for slicks."),
    ("rb_slicks_now_stop", "Slicks are faster now. We take them at the stop."),
    ("rb_slicks_now_wait", "Slicks are just faster now, but not by enough to pay for a stop yet."),
    ("rb_slicks_next", "Slicks should be faster next lap."),
    ("rb_slicks_in", "Slicks should be faster in about [laps] laps."),
    ("rb_slicks_in_rough", "Rough guess, slicks in about [laps] laps. We don't have much data yet."),
    ("rb_slicks_not_stint", "Not this stint. Stay on the wets."),
    ("rb_slicks_not_yet", "Not yet. The track isn't drying. Stay on the wets."),
    ("rb_wets_now_wait", "Wets are faster now, but not by enough to pay for a stop yet."),
    ("rb_wets_next", "Wets should be faster next lap."),
    ("rb_wets_in", "Wets should be faster in about [laps] laps."),
    ("rb_wets_in_rough", "Rough guess, wets in about [laps] laps. We don't have much data yet."),
    ("rb_wets_not", "Stay on slicks. Wets aren't faster yet."),
    ("rb_unsure", "I can't call that yet. Not enough data."),
    # proactive calls
    ("rb_call_slicks_soon", "Track's drying. Slicks in about [laps] laps, get ready."),
    ("rb_call_slicks_now", "Crossover. Slicks are faster now."),
    ("rb_call_wets_soon", "Track's getting wetter. Wets in about [laps] laps, get ready."),
    ("rb_call_heavier", "Rain's getting heavier. Think about wets."),
]

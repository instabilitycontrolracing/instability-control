"""New engineer lines (v62, DRE-parity work). NOT rendered yet: until the owner approves the wording and they are
rendered into the Engineer1 library, the stand-in voice says them (voice.py falls back to these texts).

Same format as tools/vocab_spec.py: [fill] = live value, one entry per variant (variant numbers = order here).
tools/vocab_spec.py appends this list when the library is rendered, so the ids stay the same.
"""

NEW = [
    # ---- 2026-10-31 (#709, approved by Angelo: "I okay the formation calls"): pre-race countdown on the grid
    ("form_1min", "One minute to the formation lap."),
    ("form_30s", "Thirty seconds to formation. Get ready."),
    # ---- 1 Pit lane
    ("pit_out_behind", "If we box, we come out [P], behind car [car]."),
    ("pit_out_ahead", "If we box, we come out [P], ahead of car [car]."),
    ("stall_close", "Box coming up. Box coming up."),
    ("repair_long", "Long repair. [n] seconds. Stay calm, stay calm."),
    ("repair_left", "[n] seconds."),
    ("limiter_on", "Limiter, limiter!"),
    ("limiter_off", "Limiter off, limiter off!"),
    # ---- 1b A car ahead in class pits (2026-10-25)
    ("pit_jump", "Car [car] is boxing. We jump him while he stops. Push now."),
    ("pit_jump_close", "Car [car] is boxing. It will be close when he comes out. Push, push."),
    ("pit_jump_no", "Car [car] is boxing. He should come out about [gap] ahead."),
    ("pit_jumped", "Car [car] is behind us now. We jumped him in the stop."),
    ("pit_catch", "Car [car] is out, [gap] ahead. [dec] a lap and we catch him before the flag."),
    ("pit_catch_no", "Car [car] is out, [gap] ahead. Too far to catch on pace."),
    ("pit_cycle_undercut", "The undercut worked. That's [P]. Good job."),
    ("pit_cycle_overcut", "The overcut worked. We are [P] now."),
    # ---- 2 Pit requests by voice (readbacks; variant order matters)
    ("req_tyres", "Copy. Four tires."),
    ("req_tyres", "Copy. Left side tires."),
    ("req_tyres", "Copy. Right side tires."),
    ("req_tyres", "Copy. Front tires."),
    ("req_tyres", "Copy. Rear tires."),
    ("req_tyres", "Copy. No tires."),
    ("req_fuel_add", "Copy. [n] [fuel unit]."),
    ("req_fuel_end", "Copy. Fuel to the end. [n] [fuel unit]."),
    ("req_no_fuel", "Copy. No fuel."),
    ("req_fast_repair", "Copy. Fast repair on."),
    ("req_fast_repair", "Copy. Fast repair off."),
    ("req_tearoff", "Copy. Tear off."),
    ("req_tearoff", "Copy. No tear off."),
    ("req_press", "Copy. Pressures plus [dec]."),
    ("req_press", "Copy. Pressures minus [dec]."),
    ("req_clear", "Copy. Pit menu clear."),
    ("req_compound", "Copy. Wet tires."),
    ("req_compound", "Copy. Dry tires."),
    # ---- 3 Other drivers
    ("drv_info", "Car [car]. iRating [n]. Licence [lic] [dec]."),
    ("sof", "Strength of field [n]."),
    ("irating_gain", "Plus [n] iRating if we finish here."),
    ("irating_gain", "Minus [n] iRating if we finish here."),
    ("irating_even", "iRating is even at this position."),
    ("irating_target", "[P] to gain iRating."),
    ("mark_ok", "Copy. Car [car] marked."),
    ("unmark_ok", "Copy. Car [car] clear."),
    ("marked_near", "Marked car [car] behind. Careful."),
    ("marked_near", "Marked car [car] ahead. Careful."),
    ("low_sr_near", "Car [car] behind, low safety rating. Give space."),
    ("low_sr_near", "Car [car] ahead, low safety rating. Give space."),
    ("watch_ok", "Copy. We watch car [car]."),
    ("watch_report", "Car [car]. [gap]. Last lap [time]."),
    ("watch_off", "Copy. Updates off."),
    ("car_lap", "Car [car], last lap [time]."),
    ("car_inc", "Car [car] has [n] incidents."),
    ("car_inc", "Car [car] has one incident."),
    # ---- 4 Car health
    ("fuel_pressure", "Fuel pressure low. We are checking. We are checking."),
    ("damage_report", "Damage. Repairs [n] seconds."),
    ("pedal_check", "Throttle not at full. Check the calibration. Check the calibration."),
    ("pedal_stuck", "Brake is on with the throttle. Check the pedals."),
    # ---- 5 Fuel
    ("fuel_target", "Fuel target [dec] [fuel unit] per lap."),
    ("grid_low_fuel", "Check the fuel. We don't have fuel for the stint. Check the fuel."),
    # ---- 7 Weather and tyres
    ("air_temp", "Air is [n] degrees."),
    ("wind_strong", "Wind is strong. [n] [speed unit]. Careful on the brakes."),
    ("tyres_left", "Tires [percent] percent left."),
    ("tyres_critical", "Tires are critical. [percent] percent. Box soon, box soon."),
    # ---- 8 Radio
    ("timer_set", "Copy. Timer [n] minutes."),
    ("timer_set", "Copy. Reminder in [n] laps."),
    ("timer_done", "Timer, timer."),
    ("time_now", "It is [time]."),
    ("chat_sent", "Copy. Message sent."),
    # ---- 9 Racecraft round 2 (2026-10-24, DRE parity; awaiting the owner's approval of the wording)
    ("sd_catch", "You catch car [car] in [laps] laps."),
    ("sd_caught", "Car [car] catches you in [laps] laps."),
    ("sd_flat", "We're not catching the car ahead."),
    ("sd_safe", "The car behind isn't catching you."),
    ("sv_attack", "You're faster than car [car] in sector [sector]. Attack there."),
    ("sv_defend", "Car [car] is faster in sector [sector]. Defend there."),
    # ---- fight coaching, corner by corner (2026-10-25, #94): variant 1-4 the car ahead, 5-8 the car behind
    ("fc_lose", "The car ahead brakes later into [corner]. Brake later."),
    ("fc_lose", "The car ahead carries more speed through [corner]. More speed in the middle."),
    ("fc_lose", "The car ahead gets a better exit out of [corner]. Power on earlier."),
    ("fc_lose", "The car ahead is quicker through [corner]. Find time there."),
    ("fc_lose", "The car behind brakes later into [corner]. Brake later, protect the inside."),
    ("fc_lose", "The car behind carries more speed through [corner]. More speed in the middle."),
    ("fc_lose", "The car behind gets a better exit out of [corner]. Power on earlier."),
    ("fc_lose", "The car behind is quicker through [corner]. Watch him there."),
    ("fc_gain", "You're quicker than the car ahead through [corner]. Attack there."),
    ("sv_none", "No clear difference by sector."),
    ("tl_rival", "Car [car] ahead lost [n] seconds last lap."),
    ("tl_rival", "Car [car] behind lost [n] seconds last lap."),
    ("bf_box", "Black flag. Serve it this lap. Box, box."),
    ("slow_ahead", "Slow car ahead, [corner]. Careful."),
    ("slow_ahead", "Slow car ahead. Careful."),
    ("stopped_ahead", "Car stopped ahead, [corner]. Careful, careful."),
    ("stopped_ahead", "Car stopped ahead. Careful, careful."),
    ("rf_black", "Car [car] ahead has a black flag."),
    ("rf_black", "Car [car] behind has a black flag."),
    ("rf_meatball", "Car [car] ahead has the meatball. Damage."),
    ("rf_meatball", "Car [car] behind has the meatball. Damage."),
    ("proj_finish", "On this pace we finish [P]."),
    ("ql_on", "This lap is on for [P]. Keep going."),
    ("ql_abort", "This lap is gone. Back off, go again."),
    ("pit_out_near", "Car [car] and car [car] are close when we come out."),
    ("pos_fix", "Reposition the car. Too far left."),
    ("pos_fix", "Reposition the car. Too far right."),
    ("pos_fix", "Reposition the car. Too far forward."),
    ("pos_fix", "Reposition the car. Too far back."),
    ("pos_fix", "Straighten the car in the box."),
    ("wet_aids", "Track is getting wet. Go up on TC and ABS."),
    ("rt_compound", "Car [car] ahead is on wets now."),
    ("rt_compound", "Car [car] behind is on wets now."),
    ("rt_compound", "Car [car] ahead is back on slicks."),
    ("rt_compound", "Car [car] behind is back on slicks."),
    ("rt_stint", "Car [car] stopped [n] laps ago."),
    ("rt_nostop", "Car [car] hasn't stopped yet."),
    ("net_bad", "Connection is bad. Watch for lag."),
    ("net_ok", "Connection is back to normal."),
    ("dg_yes", "Car [car], be careful with him."),
    ("dg_no", "Car [car] looks clean."),
    ("pv_faster", "You're [gap] a lap faster than car [car]."),
    ("pv_slower", "Car [car] is [gap] a lap faster than you."),
    ("pv_same", "Same pace as car [car]."),
    ("calc", "That's [n]."),
    ("calc", "That's [dec]."),
    # ---- 10 Batch D (2026-10-24; awaiting approval)
    ("cn_free", "You're the lucky dog. Free pass, you get your lap back."),
    ("cn_wave", "Wave around. Pass the pace car, catch the back of the field."),
    ("cn_eol", "End of the line. Penalty, end of the line."),
    ("cn_hold", "Caution. Hold your position, no passing."),
    ("pc_gap", "Pace car [gap] ahead."),
    ("op_exit", "Car [car] coming out of the pits. Careful."),
    ("ld_class", "New class leader, car [car]."),
    ("ps_class", "Fastest in class, sector [sector]."),
    ("wh_car", "Car [car] is [P], [gap] ahead."),
    ("wh_car", "Car [car] is [P], [gap] behind."),
    ("wh_car", "Car [car] is in the pits."),
    ("ot_count", "That's [n] off tracks."),
    ("ot_count", "That's one off track."),
    ("est_inc", "Car [car] has been off [n] times."),
    ("eng_off", "Switch the engine off while we work."),
    # ---- 11 Minute calls with an update request + replies to the driver's answer (2026-10-24)
    ("minutes_ask", "[minutes] minutes. Tire phase update when you can. Brake shape update when you can."),
    ("fb_all_good", "Copy, all good. Keep it like that."),
    ("fb_tyres_good", "Copy, tires good. Keep pushing."),
    ("fb_tyres_bad", "Copy, tires going off. Smooth on the exits, look after them. We take tires at the stop."),
    ("fb_tyres_bad", "Copy, rears going off. Easy on the throttle out of the slow corners."),
    ("fb_tyres_bad", "Copy, fronts going off. Don't overdrive the entry."),
    ("fb_brakes_good", "Copy, brakes good."),
    ("fb_brakes_bad", "Copy, brakes fading. Brake a little earlier and cool them on the straights."),
    ("fb_brakes_lock", "Copy, locking. Ease the pressure at the top of the pedal."),
    # ---- 12 Batch E: the rest of DRE's voice questions (2026-10-24, request: "do everything")
    ("tm_left", "[minutes] minutes left on the timer."),
    ("tm_left", "[laps] laps left on the timer."),
    ("tm_none", "No timer running."),
    ("tm_off", "Copy. Timer cancelled."),
    ("tm_alarm", "Copy. Reminder at [time]."),
    ("ft_onoff", "Copy. Fuel target calls on."),
    ("ft_onoff", "Copy. Fuel target calls off."),
    ("ft_onoff", "Copy. Lap time calls off."),
    ("ft_cmp", "[dec] over the fuel target."),
    ("ft_cmp", "[dec] under the fuel target."),
    ("ft_cmp", "On the fuel target."),
    ("nt_none", "No notes."),
    ("nt_read", "Note. [txt]"),
    ("nt_clear", "Copy. Notes cleared."),
    ("ck_list", "Checklist. Tear off clear. Brake bias checked. TC and ABS set. Fuel checked. Radio good. We are ready."),
    ("dbr_none", "No debris reported. Watch for slow cars."),
    ("st_elapsed", "[minutes] minutes into the stint. [laps] laps."),
    ("st_end", "Stint ends in [minutes] minutes. Box on lap [n]."),
    ("st_total", "This stint is about [minutes] minutes. [laps] laps."),
    ("st_left", "Fuel for [minutes] more minutes. About [laps] laps."),
    ("fu_time", "Fuel for [minutes] minutes."),
    ("fu_rate", "[dec] [fuel unit] a minute."),
    ("fu_last", "Last lap used [dec] [fuel unit]."),
    ("fu_avg", "Average is [dec] [fuel unit] a lap."),
    ("fu_calc", "[laps] laps is [n] [fuel unit]."),
    ("fu_calc", "[minutes] minutes is [n] [fuel unit]."),
    ("fu_stops", "For [n] stops, save [dec] [fuel unit] a lap."),
    ("fu_stops", "[n] stops works. No saving needed."),
    ("fu_stops", "[n] stops is too far. We can't save that much."),
    ("fu_stops", "For one stop, save [dec] [fuel unit] a lap."),
    ("fu_stops", "One stop works. No saving needed."),
    ("fu_stops", "One stop is too far. We can't save that much."),
    ("fu_stops", "To make the end, save [dec] [fuel unit] a lap."),
    ("fu_stops", "We make the end without a stop. No saving needed."),
    ("fu_stops", "We can't make the end without a stop."),
    ("fw", "Yes, we are in the window. We can box any time."),
    ("fw", "Not yet. The window opens in [laps] laps."),
    ("fw", "No stop needed. We go to the end."),
    ("pm_fuel_only", "Copy. Fuel only."),
    ("pm_full", "Copy. Full service. Four tires and full fuel."),
    ("pm_max", "Copy. Full tank."),
    ("pm_less", "Copy. [n] [fuel unit] less."),
    ("ty_need", "Yes. Tires are done. Box for tires."),
    ("ty_need", "No. Tires are good to the end."),
    ("ty_need", "Tires are good for [laps] more laps."),
    ("ty_opt", "Slicks. Track is dry."),
    ("ty_opt", "Wets. Track is wet."),
    ("ty_opt", "It's the crossover. Slicks if you are comfortable, wets if it gets worse."),
    ("rn_now", "Yes, it's raining. [percent] percent."),
    ("rn_now", "No rain right now."),
    ("rn_fc", "Forecast is [percent] percent chance of rain."),
    ("rn_fc", "No rain in the forecast."),
    ("rn_fc", "We don't have a forecast for this session."),
    ("wx_hum", "Humidity [percent] percent."),
    ("wx_press", "Air pressure [n] hectopascals."),
    ("wx_sky", "Skies [skies]."),
    ("wx_wind", "Wind [n] [speed unit], from the [dir]."),
    ("wx_wind", "Wind from the [dir]."),
    ("wx_wind", "Wind [n] [speed unit]."),
    ("wx_delta", "Track is up [n] degrees since the start."),
    ("wx_delta", "Air is up [n] degrees since the start."),
    ("wx_delta", "Wind is up [n] [speed unit] since the start."),
    ("wx_delta", "Humidity is up [n] percent since the start."),
    ("wx_delta", "Track is down [n] degrees since the start."),
    ("wx_delta", "Air is down [n] degrees since the start."),
    ("wx_delta", "Wind is down [n] [speed unit] since the start."),
    ("wx_delta", "Humidity is down [n] percent since the start."),
    ("wx_delta", "Same as the start."),
    ("sb_overall", "Fastest lap overall is [time], car [car]."),
    ("psl", "Pit limit is [n] [speed unit]."),
    ("fr_left", "[n] fast repairs left."),
    ("fr_left", "No fast repairs left."),
    ("fr_left", "Fast repairs are unlimited."),
    ("fr_left", "One fast repair left."),
    ("ses_cars", "[n] cars in the race. [laps] in our class."),
    ("ses_cars", "[n] cars in the race."),
    ("tr_len", "Track is [dec] kilometers."),
    ("tr_len", "Track is [dec] miles."),
    ("setup_name", "Setup is [txt]."),
    ("fl_faster", "Last five laps, we are [dec] a lap faster than the car ahead."),     # 2026-10-25
    ("fl_slower", "Last five laps, we are [dec] a lap slower than the car ahead."),
    ("fl_same", "Last five laps, same pace as the car ahead."),
    ("ar_laps", "Car ahead [time]. Car behind [time]."),
    ("ar_laps", "Car ahead [time]."),
    ("ar_laps", "Car behind [time]."),
    ("my_start", "We started [P]."),
    ("oc_pos", "Car [car] is [P] overall."),
    ("oc_pos", "Car [car] is [P] in class."),
    ("oc_pos", "Car [car] started [P]."),
    ("oc_pos", "Car [car] qualified [P]."),
    ("oc_name", "Car [car] is [txt]."),
    ("oc_class", "Car [car] is in [class]."),
    ("oc_make", "Car [car] is driving the [txt]."),
    ("oc_num", "That's car [car]."),
    ("oc_best", "Car [car] best lap [time]."),
    ("oc_best", "Car [car] qualifying lap [time]."),
    ("oc_best", "Car [car] is averaging [time]."),
    ("oc_lap", "Car [car] is on lap [n]."),
    ("oc_where", "Car [car] is at [corner]."),
    ("oc_where", "Car [car] is in sector [sector]."),
    ("oc_gap", "Car [car] is [gap] ahead."),
    ("oc_gap", "Car [car] is [gap] behind."),
    ("oc_pitdiff", "Car [car] has stopped [n] more than us."),
    ("oc_pitdiff", "Car [car] has stopped [n] less than us."),
    ("oc_pitdiff", "Car [car] has the same stops as us."),
    ("oc_outlap", "Car [car] came out on lap [n]."),
    ("oc_pittime", "Car [car], last stop [n] seconds."),
    ("oc_pittime", "Car [car], [n] seconds in the pits in total."),
    ("oc_pitlap", "Car [car] last stopped on lap [n]."),
    ("oc_stops", "Car [car] has stopped [n] times."),
    ("oc_stops", "Car [car] has stopped once."),
    ("oc_tyrelaps", "Car [car] has [n] laps on the tires."),
    ("oc_comp", "Car [car] is on slicks."),
    ("oc_comp", "Car [car] is on wets."),
    ("oc_trend", "Car [car] is getting faster."),
    ("oc_trend", "Car [car] is getting slower."),
    ("oc_trend", "Car [car] is steady."),
    ("oc_delta", "Car [car] was [gap] faster last lap."),
    ("oc_delta", "Car [car] was [gap] slower last lap."),
    ("oc_delta", "Car [car] best is [gap] faster than ours."),
    ("oc_delta", "Car [car] best is [gap] slower than ours."),
    ("oc_delta", "Over five laps, car [car] is [gap] faster."),
    ("oc_delta", "Over five laps, car [car] is [gap] slower."),
    ("tr_txt", "Track is [txt]."),
    ("tr_txt", "Session is [txt]."),
    # ---- 13 In-car adjustments by voice + in-car coaching + app controls (2026-10-24, request: "keep going until these are all done")
    ("ic_set", "Copy. Brake bias [n] point [n]."),
    ("ic_set", "Copy. TC [n]."),
    ("ic_set", "Copy. TC two, [n]."),
    ("ic_set", "Copy. ABS [n]."),
    ("ic_set", "Copy. Front bar [n]."),
    ("ic_set", "Copy. Rear bar [n]."),
    ("ic_set", "Copy. Migration [n]."),
    ("ic_set", "Copy. Engine map [n]."),
    ("ic_set", "Copy. Fuel mix [n]."),
    ("ic_set", "Copy. Deploy mode [n]."),
    ("ic_set", "Copy. Regen [n]."),
    ("ic_msg", "Can't change it from here. iRacing has to be the window in front."),
    ("ic_msg", "This car doesn't have that."),
    ("ic_msg", "Wait, still changing the last one."),
    ("ic_msg", "No safe straight to do it. Ask me again."),
    ("ic_msg", "The keys didn't work. Check the black box keys in iRacing."),
    ("ic_msg", "That's already at the limit."),
    ("ic_tip", "Balance looks good. No change needed."),
    ("ic_tip", "Not enough laps yet. Give me two clean laps."),
    ("ic_tip", "We see understeer on entry."),
    ("ic_tip", "We see understeer mid-corner."),
    ("ic_tip", "We see understeer on exit."),
    ("ic_tip", "We see oversteer on entry."),
    ("ic_tip", "We see oversteer mid-corner."),
    ("ic_tip", "We see oversteer on exit."),
    ("ic_tip", "You're on the ABS a lot."),
    ("ic_tip", "The rears are locking."),
    ("ic_tip", "Nothing on the wheel fixes that. We look at the setup at the next stop."),
    ("ic_do", "Try brake bias forward one click."),
    ("ic_do", "Try brake bias back one click."),
    ("ic_do", "Try TC up one."),
    ("ic_do", "Try TC down one."),
    ("ic_do", "Try TC two up one."),
    ("ic_do", "Try TC two down one."),
    ("ic_do", "Try ABS up one."),
    ("ic_do", "Try ABS down one."),
    ("ic_do", "Try the front bar one stiffer."),
    ("ic_do", "Try the front bar one softer."),
    ("ic_do", "Try the rear bar one stiffer."),
    ("ic_do", "Try the rear bar one softer."),
    ("ic_do", "Try migration one click up."),
    ("ic_do", "Try migration one click down."),
    ("ic_style", "And release the brake a bit earlier. You trail brake a lot."),
    ("ic_style", "And be a bit softer on the throttle out of the slow corners."),
    ("ic_offer", "Say do it, and I change it."),
    ("ic_explain", "Front bar. Stiffer gives a lazier front and more understeer. Softer gives more front grip mid-corner and on exit. Go softer when the car pushes in the middle of the corner."),
    ("ic_explain", "Rear bar. Stiffer helps the car rotate, but the rear gets loose on exit. Softer calms the rear and helps traction. Go softer when the rear steps out mid-corner or on exit."),
    ("ic_explain", "Brake bias. Forward is more stable, but the fronts lock and the car pushes into the corner. Rearward helps it turn in, but the rear can lock and step out. As the fuel burns off, small moves keep it balanced."),
    ("ic_explain", "Migration, the brake shape. It moves the bias rearward as you come off the pedal. More helps the car rotate when you trail brake. Less keeps the rear calm. More when it pushes at turn-in, less when the rear is nervous on entry."),
    ("ic_explain", "TC. Higher stops wheelspin on exit and saves the rear tires, but costs drive. Lower is faster while the rears are good. Go up when the rears go off, or in the wet."),
    ("ic_explain", "TC two. The second traction setting, how much slip it allows. Up is safer on worn tires and in the wet, down gives more drive when the rears are fresh."),
    ("ic_explain", "ABS. Higher stops lockups sooner and is more stable. Lower lets you brake harder, but it's easier to lock. Go up when you lock the fronts, or in the wet."),
    ("ic_explain", "Engine map. Higher is more power and more fuel. Lower saves fuel. Use a lower map when we need a fuel save."),
    ("ic_explain", "Deploy mode. How much hybrid power you get on each straight. Higher is faster now, but the battery runs down. Lower saves the battery for later."),
    ("app_set", "Copy, that's off."),
    ("app_set", "Copy, that's on."),
    ("app_set", "Copy, louder."),
    ("app_set", "Copy, quieter."),
    ("app_set", "Copy, gaps every [laps] laps."),
    ("app_set", "Copy, gaps every lap."),
    ("app_set", "Copy, spotter changed."),
    ("ses_classes", "[n] classes in the race."),
    ("ses_classes", "[n] different cars in the race."),
    ("rd", "Speed [n] [speed unit]."),
    ("rd", "[n] RPM."),
    ("rd", "Throttle [percent] percent."),
    ("rd", "Brake [percent] percent."),
    ("rd", "Battery [dec] volts."),
    ("rd", "Oil level [dec] liters."),
    ("rd", "Water level [dec] liters."),
    ("rd", "Steering [n] degrees left."),
    ("rd", "Steering [n] degrees right."),
    ("rd", "Clutch [percent] percent."),
]

# new building blocks (kind, key, text) for the fills above
# licence classes in the phonetic alphabet so they can't be misheard (driver request 2026-10-24); "Pro" stays as it is
NEW_BLOCKS = [("lic", k, t) for k, t in (("R", "Rookie."), ("D", "Delta."), ("C", "Charlie."), ("B", "Bravo."), ("A", "Alpha."), ("P", "Pro."))] + [
    ("big", "thousand", "thousand."), ("big", "hundred", "hundred."),
] + [("dir", k, k.replace("_", "-") + ".") for k in ("north", "north_east", "east", "south_east", "south", "south_west", "west", "north_west")] + [
    ("skies", k, k.replace("_", " ") + ".") for k in ("clear", "partly_cloudy", "mostly_cloudy", "overcast")] + [
    ("speed_unit", "kph", "kilometers per hour."), ("speed_unit", "mph", "miles per hour."),
    ("word", "point", "point."),          # lap times read as ":35 point 3 9 1" (2026-10-25)
]


# Name-free variants (v62b) for lines where every recorded variant says the driver's name, so other drivers get a real
# recorded line instead of the stand-in voice. Rendered only once tools/v62b_approved.txt exists.
NAME_FREE = [
    ("five_min_leading", "it", "Five minutes. Possiamo vincere. Concentrato."),
    ("finish_good", "en", "[P], [P]. Great job. Mode formation. Mode formation."),
    ("finish_points", "en", "[P], [P]. Good points today. Good job."),
    ("podium", "it", "Podio! Podio! Che gara!"),
    ("win", "it", "Vittoria! Vittoria! Mamma mia, che gara! Grandissimo!"),
    ("b2_leading_the_class_italian", "it", "Primo di classe! Bravo, bravo!"),
    ("b2_class_win_at_the_finish", "it", "Vittoria di classe! Vittoria!"),
    ("b2_before_the_last_stint_italian", "it", "Ultimo stint. Dai, tutto adesso!"),
    ("b2_fan_of_the_team_moment", "it", "All the team is watching. Grande."),
    ("b2_general_good_debrief", "en", "Good race. We speak in the box."),
]


# 2026-10-28: approved by the owner ("new spoken lines approved", "all new voice lines i approve"). Unlike NEW above
# these are on the render list straight away (tools/vocab_spec.py adds them, no approval file needed); until they
# are rendered the stand-in voice says them.
# radio answers (#453, radio_line_proposals.md)
RADIO_1028 = [
    ("ans_say_again", "Say again?"),                          # a question nobody understood (was "Radio check?")
    ("ans_say_again", "Didn't get that, say again."),
    ("ans_which_gap", "Ahead or behind?"),                    # "what's the gap?" while fighting both ways
]
# wet-track tips by track (track_packs/engineer_line_proposals.md): engineer/rain.py speaks these (TRACK_WET)
WET_TRACK_LINES = {
    "autodromohermanosrodriguez": [
        ("wet_mexico_1", "Turn one comes at the end of the long straight. Brake early and off the rubbered line."),
        ("wet_mexico_2", "Stadium section is slow. Short shift and squeeze the throttle.")],
    "suzukainternationalracingcourse": [
        ("wet_suzuka_1", "S Curves in the wet. Smooth hands, no kerbs."),
        ("wet_suzuka_2", "Spoon and one-thirty R are fast. Lift earlier than you think.")],
    "silverstonecircuit": [
        ("wet_silverstone_1", "Maggotts and Becketts. Quick changes of direction, smooth hands."),
        ("wet_silverstone_2", "Stowe and Vale. Brake early and off the rubbered line.")],
    "autodromonazionalemonza": [
        ("wet_monza_1", "Big stops from top speed into the chicanes. Brake early, off the line."),
        ("wet_monza_2", "Chicane kerbs are ice when wet. Stay off them.")],
    # 2026-10-28 round 2 (approved by the owner: "all new voice lines i approve"): every Sports Car track with sourced
    # watch / wet notes in its research pack (sc_packs/out). Each tip = a sourced fact about the corner + the general
    # wet rule in rain.TIPS; where it was written from a pack wet note, that text note is left out of track_packs.PACK_WET.
    'adelaidestreetcircuit': [
        ('wet_adelaide_1', "Senna Chicane kerbs are ice when wet. Brake early, stay off them."),
        ('wet_adelaide_2', "Dequetteville Hairpin is a big stop. In the wet, brake early and off the line.")],
    'algarveinternationalcircuit': [
        ('wet_portimao_1', "Turn one is heavy downhill braking. Brake earlier and softer in the wet."),
        ('wet_portimao_2', "Torre VIP is at the bottom of a steep drop. Brake in a straight line.")],
    'autodromointernazionaledelmugello': [
        ('wet_mugello_1', "San Donato's braking zone is over a crest. Brake earlier in the wet."),
        ('wet_mugello_2', "Materassi is the sharpest stop. Brake early and off the line.")],
    'autodromointernazionaleenzoedinoferrari': [
        ('wet_imola_1', "Acque Minerali is downhill braking. In the wet, brake early, don't lock a front."),
        ('wet_imola_2', "Variante Alta kerbs are ice when wet. Stay off them.")],
    'autodromojosecarlospace': [
        ('wet_interlagos_1', "Turn three kerbs hold water. Stay off them in the wet."),
        ('wet_interlagos_2', "The weather turns fast here. Drizzle to downpour in minutes.")],
    'barbermotorsportspark': [
        ('wet_barber_1', "Water pools in the turn one compression. Keep it straight."),
        ('wet_barber_2', "Turn sixteen's off-camber exit is much worse in the wet. Easy on the throttle.")],
    'brandshatchcircuit': [
        ('wet_brands_1', "Druids exit run-off is very slippery in the wet. Stay on the track."),
        ('wet_brands_2', "Graham Hill Bend, the racing line is very slippery in the wet. Go off line.")],
    'cadwellparkcircuit': [
        ('wet_cadwell_1', "Park has a hump under braking. In the wet, brake earlier and softer.")],
    'canadiantiremotorsportspark': [
        ('wet_mosport_1', "Moss Corner is the slowest point. Short shift and squeeze the throttle out of it."),
        ('wet_mosport_2', "Fast blind corners all lap. Smooth hands in the wet.")],
    'charlottemotorspeedway': [
        ('wet_charlotte_1', "Backstretch chicane, brake early and off the line in the wet.")],
    'chicagostreetcourse': [
        ('wet_chicago_1', "Turn four is a big stop. In the wet, brake earlier and softer.")],
    'circuitdebarcelonacatalunya': [
        ('wet_barcelona_1', "Turn ten hairpin after the back straight. Brake early in the wet."),
        ('wet_barcelona_2', "Chicane sausage kerbs, stay off them in the wet.")],
    'circuitdeledenon': [
        ('wet_ledenon_1', "La Servie is a big stop. In the wet, brake earlier and softer."),
        ('wet_ledenon_2', "Virage du Camion is at the bottom of the big drop. Watch for standing water.")],
    'circuitdeneversmagnycours': [
        ('wet_magnycours_1', "Adelaide, brake in a straight line. In the wet, earlier and softer."),
        ('wet_magnycours_2', "Lycée chicane onto the straight. Squeeze the throttle in the wet.")],
    'circuitgillesvilleneuve': [
        ('wet_montreal_1', "Pont de la Concorde is tricky when it's damp. Smooth hands there."),
        ('wet_montreal_2', "Final chicane, braking from top speed. In the wet, brake early, mind the wall.")],
    'circuitodejerez': [
        ('wet_jerez_1', "Pedrosa hairpin is the biggest stop. Brake early in the wet."),
        ('wet_jerez_2', "Lorenzo, last corner, very tight. Short shift, squeeze the throttle out.")],
    'circuitoftheamericas': [
        ('wet_cota_1', "Big Red is a steep climb and a late stop. In the wet, brake earlier."),
        ('wet_cota_2', "Turn twelve, end of the back straight. Brake early and off the line.")],
    'circuitzandvoort': [
        ('wet_zandvoort_1', "Tarzan, end of the long run. Brake early and off the line."),
        ('wet_zandvoort_2', "Sea gusts can unsettle the car. Smooth hands in the wet.")],
    'circuitzolder': [
        ('wet_zolder_1', "Bolderbergbocht, slowest corner. Short shift and squeeze the throttle."),
        ('wet_zolder_2', "Jacky Ickx chicane, uphill exit. Hard to get traction in the wet.")],
    'daytonainternationalspeedway': [
        ('wet_daytona_1', "Bus Stop, braking from top speed. Brake early and off the line."),
        ('wet_daytona_2', "Horseshoe is bumpy. In the wet, brake earlier and softer.")],
    'detroitgrandprixatbelleisle': [
        ('wet_belleisle_1', "Concrete and asphalt patches change the grip. In the wet, smooth hands."),
        ('wet_belleisle_2', "Turn five, stay off the inside kerb. Kerbs are ice when wet.")],
    'doningtonparkracingcircuit': [
        ('wet_donington_1', "Craner Curves, standing water can make you aquaplane. Keep it straight."),
        ('wet_donington_2', "Hollywood is treacherous in the wet. Easy on the power.")],
    'fujiinternationalspeedway': [
        ('wet_fuji_1', "Rain and mist are common here. Expect low visibility, give more room."),
        ('wet_fuji_2', "TGR Corner after the long straight. Brake early and off the line.")],
    'hockenheimringbadenwurttemberg': [
        ('wet_hockenheim_1', "Spitzkehre, big stop after the Parabolika. Brake early in the wet."),
        ('wet_hockenheim_2', "Südkurve, downhill braking. Brake earlier and softer in the wet.")],
    'hungaroring': [
        ('wet_hungaroring_1', "Turn one hairpin, brake early and off the line in the wet."),
        ('wet_hungaroring_2', "You use the kerbs here in the dry. In the wet, stay off them.")],
    'indianapolismotorspeedway': [
        ('wet_indy_1', "Turn one is a big stop off the front straight. Brake early and off the line."),
        ('wet_indy_2', "Turns one and twelve, the grip changes between oval and infield. Careful in the wet.")],
    'knockhillracingcircuit': [
        ('wet_knockhill_1', "The weather here changes fast. Mixed conditions are a lottery, stay calm."),
        ('wet_knockhill_2', "Duffus Dip, downhill braking. Brake earlier in the wet.")],
    'lankebanen': [
        ('wet_hell_1', "Off-camber corners, the car goes light. Be patient on the throttle in the wet.")],
    'limerockpark': [
        ('wet_limerock_1', "Big Bend, brake in a straight line. Earlier and softer in the wet.")],
    'longbeachstreetcircuit': [
        ('wet_longbeach_1', "Turn one, hard braking off Shoreline. Brake early and off the line."),
        ('wet_longbeach_2', "Turn five, off-camber and bumpy. In the wet, easy on the throttle.")],
    'miamiinternationalautodrome': [
        ('wet_miami_1', "Turn seventeen, end of the longest straight. Brake early and off the line."),
        ('wet_miami_2', "Turns thirteen to sixteen are uneven. Smooth hands in the wet.")],
    'midohiosportscarcourse': [
        ('wet_midohio_1', "Carousel, brake hard. In the wet, brake earlier and softer."),
        ('wet_midohio_2', "Keyhole, throttle only at the second apex. Squeeze it in the wet.")],
    'misanoworldcircuitmarcosimoncelli': [
        ('wet_misano_1', "Sausage kerbs everywhere. Stay off them in the wet."),
        ('wet_misano_2', "Tramonto hairpin, big stop. Brake early and off the line.")],
    'mobilityresortmotegi': [
        ('wet_motegi_1', "Ninety Degree, big stop at the foot of the downhill. Brake early in the wet."),
        ('wet_motegi_2', "Lots of heavy braking into slow corners. Short shift on the way out.")],
    'motorsportarenaoschersleben': [
        ('wet_oschersleben_1', "Triple left, the car goes light. Smooth hands in the wet."),
        ('wet_oschersleben_2', "Long low-gear corners. Short shift and squeeze the throttle.")],
    'mountpanoramacircuit': [
        ('wet_bathurst_1', "Griffins Bend, big stop off Mountain Straight. Brake early in the wet."),
        ('wet_bathurst_2', "Conrod, brake early for The Chase. Even earlier in the wet.")],
    'newjerseymotorsportspark': [
        ('wet_njmp_1', "Track limits are white lines. They're ice when wet."),
        ('wet_njmp_2', "Jersey Devil, turns nine and ten. Smooth hands in the wet.")],
    'nurburgringcombined': [
        ('wet_nurburgring_1', "Schwedenkreuz is a real risk in the wet. Turn in carefully."),
        ('wet_nurburgring_2', "Bergwerk is the most dangerous spot in the wet. Brake early.")],
    'nurburgringgrandprixstrecke': [
        ('wet_nurburgringgp_1', "Turn one, big stop from the main straight. Brake early and off the line."),
        ('wet_nurburgringgp_2', "Mercedes Arena, keep two wheels inside the white line. Lines are ice when wet.")],
    'nurburgringnordschleife': [
        ('wet_nordschleife_1', "Eiskurve stays wet in the tree shade. Slippery as ice."),
        ('wet_nordschleife_2', "Klostertal is treacherous on wet tarmac. Be careful there.")],
    'okayamainternationalcircuit': [
        ('wet_okayama_1', "Hairpin at the end of the back straight. Brake early and off the line."),
        ('wet_okayama_2', "Walls close in the hills. In the wet, brake earlier and softer.")],
    'oranparkraceway': [
        ('wet_oranpark_1', "The surface is slippery already. In the wet, smooth hands."),
        ('wet_oranpark_2', "Blind crests and bumps at turn-in. Brake in a straight line.")],
    'oultonparkcircuit': [
        ('wet_oulton_1', "Island Bend is very fast. Lift earlier than you think in the wet."),
        ('wet_oulton_2', "Lodge, bumpy braking. In the wet, brake earlier and softer.")],
    'phillipislandcircuit': [
        ('wet_phillipisland_1', "Doohan, very fast entry. In the wet, lift earlier than you think."),
        ('wet_phillipisland_2', "Miller Corner, big braking. Brake early and off the line.")],
    'poconoraceway': [
        ('wet_pocono_1', "Turn three, heavy braking. Brake earlier and softer in the wet.")],
    'portlandinternationalraceway': [
        ('wet_portland_1', "Asphalt and concrete mix here. The grip changes between them, careful in the wet."),
        ('wet_portland_2', "Shelton Chicane at the end of the straight. Brake early and off the line.")],
    'qualcommcircuitnavalbasecoronado': [
        ('wet_coronado_1', "Crane tracks and patched pavement from turn four. Smooth hands in the wet.")],
    'redbullring': [
        ('wet_spielberg_1', "Remus, uphill braking locks wheels. Brake earlier and softer in the wet."),
        ('wet_spielberg_2', "Turn four, downhill stop. Brake early and off the line.")],
    'roadamerica': [
        ('wet_roadamerica_1', "The Kink, water runs across the track when it rains. Keep it straight."),
        ('wet_roadamerica_2', "Carousel in the wet, drive around the outside.")],
    'rudskogenmotorsenter': [
        ('wet_rudskogen_1', "Turn one is fast and tight. Brake earlier and softer in the wet.")],
    'sachsenring': [
        ('wet_sachsenring_1', "Turn eleven has less grip, the right tyre cools on the lefts. Careful in the wet."),
        ('wet_sachsenring_2', "Waldmann and Wasserfall, fast and blind with a steep drop. Lift earlier in the wet.")],
    'sandowninternationalmotorraceway': [
        ('wet_sandown_1', "Turn four kink, barely a corner in the dry. Slippery in the wet."),
        ('wet_sandown_2', "Dandenong Road, easy to lock up. Brake earlier and softer in the wet.")],
    'shellvpowermotorsportparkatthebend': [
        ('wet_thebend_1', "Turns four and five, the camber drops away. Smooth hands in the wet."),
        ('wet_thebend_2', "Turn twelve has no run-off. Careful in the wet.")],
    'snettertoncircuit': [
        ('wet_snetterton_1', "Agostini hairpin, don't power on too early. Squeeze it in the wet."),
        ('wet_snetterton_2', "Wilson hairpin, brake early and off the line.")],
    'sonomaraceway': [
        ('wet_sonoma_1', "Carousel, blind downhill entry. Roll on the throttle gently in the wet."),
        ('wet_sonoma_2', "Turn eleven hairpin after a bump. Brake early and off the line.")],
    'stpetersburggrandprix': [
        ('wet_stpete_1', "Turn ten at the end of the marina straight. Brake early, there's runoff if you need it."),
        ('wet_stpete_2', "Walls everywhere. In the wet, smooth hands.")],
    'summitpointraceway': [
        ('wet_summit_1', "Turn one is slippery in the wet. Run slightly wide of the dry line."),
        ('wet_summit_2', "Turn nine is very slick in the wet. Go easy on the throttle.")],
    'thruxtoncircuit': [
        ('wet_thruxton_1', "Club chicane, brake straight. Huge kerbs, stay off them in the wet."),
        ('wet_thruxton_2', "Church is fast with the apex on a crest. Lift earlier in the wet.")],
    'tsukubacircuit': [
        ('wet_tsukuba_1', "First Hairpin is tight. Short shift and squeeze the throttle out."),
        ('wet_tsukuba_2', "Final Corner is long and fast. Smooth hands in the wet.")],
    'virginiainternationalraceway': [
        ('wet_vir_1', "Turn one is downhill on a slippery surface. Brake earlier and softer in the wet."),
        ('wet_vir_2', "South Bend, fastest and most dangerous. Brake in a straight line.")],
    'watkinsgleninternational': [
        ('wet_watkinsglen_1', "The ninety, downhill stop. Brake early and off the line in the wet."),
        ('wet_watkinsglen_2', "Inner Loop kerbs unsettle the car. Stay off them in the wet.")],
    'weathertechracewayatlagunaseca': [
        ('wet_laguna_1', "Andretti Hairpin, downhill braking. In the wet, brake earlier and softer."),
        ('wet_laguna_2', "Turn six, the dip at the apex catches the rear. Smooth hands in the wet.")],
    'willowspringsinternationalraceway': [
        ('wet_willow_1', "Turn nine tightens. More spins there than anywhere. Careful in the wet."),
        ('wet_willow_2', "Monroe Ridge is on a crest, the car goes light. Smooth hands.")],
    'wintonmotorraceway': [
        ('wet_winton_1', "Advanced Petroleum is the bumpiest brake zone. Brake earlier and softer in the wet."),
        ('wet_winton_2', "Kitome, traction out of the hairpins. Short shift in the wet.")],
}
APPROVED_1028 = RADIO_1028 + [x for v in WET_TRACK_LINES.values() for x in v]


def table():
    """{sid: [text of variant 1, variant 2, ...]}"""
    out = {}
    for sid, text in NEW + APPROVED_1028:
        out.setdefault(sid, []).append(text)
    return out

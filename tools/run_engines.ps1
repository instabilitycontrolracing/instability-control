$r = "$env:USERPROFILE\Documents\CrewChiefVoices"
$plan = @(@('xtts','0'), @('chatterbox','1'), @('f5','0'))
foreach ($p in $plan) {
  $w = $p[0]; $env:CUDA_VISIBLE_DEVICES = $p[1]
  Start-Process -FilePath "$r\venv_$w\Scripts\python.exe" -ArgumentList "`"$r\tools\gen_engine.py`"", $w -RedirectStandardOutput "$r\tools\gen_$w.out.txt" -RedirectStandardError "$r\tools\gen_$w.err.txt" -WindowStyle Hidden
}
"launched"

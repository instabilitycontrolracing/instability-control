# Render lines added since the last render (2026-10-28): engineer (Higgs, both GPUs) -> strategist (Chatterbox).
# Same steps as overnight_voices.ps1 WITHOUT overnight_prep.py (its 2026-10-24 step deletes and re-records every
# number clip) and without the spotters. Only missing / changed clips are rendered; existing ones are kept.
$r = "$env:USERPROFILE\Documents\CrewChiefVoices"
$s4 = "$env:USERPROFILE\Desktop\Engineer Voice - Engine Test\_dev\strat4"
$log = "$env:USERPROFILE\Desktop\VOICE_RENDER_STATUS.txt"
$env:PYTHONIOENCODING = 'utf-8'; $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
"New-lines render started $(Get-Date)" | Out-File $log
"--- engineer $(Get-Date)" | Out-File $log -Append
# vocab_jobs.py (run inside vocab_run_all) rebuilds jobs.json + manifest.json, then Higgs renders what's missing
& powershell -NoProfile -ExecutionPolicy Bypass -File "$r\tools\vocab_run_all.ps1"
Get-Content "$r\Engineer1\vocab\STATUS.txt" | Out-File $log -Append
"--- strategist $(Get-Date)" | Out-File $log -Append
& python "$r\tools\strat_say_numbers.py" *>> $log
$env:CUDA_VISIBLE_DEVICES = '1'
& "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --say "$r\Strategist\chatterbox\say_numbers.json" 2>&1 | Select-String "clips|ALL DONE|Error" | Out-File $log -Append
Remove-Item Env:CUDA_VISIBLE_DEVICES
& "$r\venv_eng\Scripts\python.exe" "$s4\cut_strategist.py" chatterbox 2>&1 | Select-String "sentences|redo|Error" | Out-File $log -Append
$redo = "$r\Strategist\chatterbox\redo.txt"
if ((Test-Path $redo) -and (Get-Item $redo).Length -gt 0) {
  "--- strategist retry $(Get-Date)" | Out-File $log -Append
  $env:CUDA_VISIBLE_DEVICES = '1'
  & "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --only $redo --say "$r\Strategist\chatterbox\say_numbers.json" --seed 4242 2>&1 | Select-String "clips|ALL DONE" | Out-File $log -Append
  Remove-Item Env:CUDA_VISIBLE_DEVICES
  & "$r\venv_eng\Scripts\python.exe" "$s4\cut_strategist.py" chatterbox 2>&1 | Select-String "sentences|redo" | Out-File $log -Append
}
"ALL FINISHED $(Get-Date)" | Out-File $log -Append

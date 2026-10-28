# Overnight voice render (2026-10-24): engineer (Higgs, both GPUs) -> strategist (Chatterbox) -> spotters Jess + Leo
$r = "$env:USERPROFILE\Documents\CrewChiefVoices"
$s4 = "$env:USERPROFILE\Desktop\Engineer Voice - Engine Test\_dev\strat4"
$log = "$env:USERPROFILE\Desktop\VOICE_RENDER_STATUS.txt"
$env:PYTHONIOENCODING = 'utf-8'; $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
"Voice render started $(Get-Date)" | Out-File $log
& python "$r\tools\overnight_prep.py" *>> $log
"--- engineer $(Get-Date)" | Out-File $log -Append
& powershell -NoProfile -ExecutionPolicy Bypass -File "$r\tools\vocab_run_all.ps1"
Get-Content "$r\Engineer1\vocab\STATUS.txt" | Out-File $log -Append
"--- strategist: new lines $(Get-Date)" | Out-File $log -Append
$env:CUDA_VISIBLE_DEVICES = '1'
& "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --say "$r\Strategist\chatterbox\say_numbers.json" 2>&1 | Select-String "clips|ALL DONE|Error" | Out-File $log -Append
"--- strategist: spelled numbers $(Get-Date)" | Out-File $log -Append
& "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --only "$r\Strategist\chatterbox\only_numbers.txt" --say "$r\Strategist\chatterbox\say_numbers.json" 2>&1 | Select-String "clips|ALL DONE|Error" | Out-File $log -Append
Remove-Item Env:CUDA_VISIBLE_DEVICES
& "$r\venv_eng\Scripts\python.exe" "$s4\cut_strategist.py" chatterbox 2>&1 | Select-String "sentences|redo|Error" | Out-File $log -Append
# one retry pass with another seed for anything that didn't cut cleanly
$redo = "$r\Strategist\chatterbox\redo.txt"
if ((Test-Path $redo) -and (Get-Item $redo).Length -gt 0) {
  "--- strategist retry $(Get-Date)" | Out-File $log -Append
  $env:CUDA_VISIBLE_DEVICES = '1'
  & "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --only $redo --say "$r\Strategist\chatterbox\say_numbers.json" --seed 4242 2>&1 | Select-String "clips|ALL DONE" | Out-File $log -Append
  Remove-Item Env:CUDA_VISIBLE_DEVICES
  & "$r\venv_eng\Scripts\python.exe" "$s4\cut_strategist.py" chatterbox 2>&1 | Select-String "sentences|redo" | Out-File $log -Append
}
"--- spotters $(Get-Date)" | Out-File $log -Append
& powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Desktop\Engineer Voice - Engine Test\_dev\spot1\run.ps1"
Get-Content "$env:USERPROFILE\Desktop\Engineer Voice - Engine Test\_dev\spot1\run.log" -Tail 5 | Out-File $log -Append
# late additions: anything added to the line lists during the night (renders only what's missing)
"--- late additions $(Get-Date)" | Out-File $log -Append
if (Test-Path "$r\tools\late_ready.txt") {
  & powershell -NoProfile -ExecutionPolicy Bypass -File "$r\tools\vocab_run_all.ps1"
  Get-Content "$r\Engineer1\vocab\STATUS.txt" -Tail 3 | Out-File $log -Append
  $env:CUDA_VISIBLE_DEVICES = '1'
  & "$r\venv_chatterbox\Scripts\python.exe" "$s4\render_strategist.py" chatterbox --say "$r\Strategist\chatterbox\say_numbers.json" 2>&1 | Select-String "clips|ALL DONE" | Out-File $log -Append
  Remove-Item Env:CUDA_VISIBLE_DEVICES
  & "$r\venv_eng\Scripts\python.exe" "$s4\cut_strategist.py" chatterbox 2>&1 | Select-String "sentences|redo" | Out-File $log -Append
}
"ALL FINISHED $(Get-Date)" | Out-File $log -Append

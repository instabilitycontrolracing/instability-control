$r = "$env:USERPROFILE\Documents\CrewChiefVoices"
$t = "$r\tools"; $V = "$r\Engineer1\vocab"
$env:PYTHONIOENCODING = 'utf-8'; $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$status = "$V\STATUS.txt"
"Started $(Get-Date)" | Out-File $status
& python "$t\vocab_jobs.py" *>> $status
for ($round = 0; $round -le 3; $round++) {
  "Render round $round started $(Get-Date)" | Out-File $status -Append
  $env:CUDA_VISIBLE_DEVICES = '0,1'
  & "$r\venv_higgs2\Scripts\python.exe" "$t\vocab_render.py" $round *>> "$V\render_err.txt"
  Remove-Item Env:CUDA_VISIBLE_DEVICES
  "Verify round $round started $(Get-Date)" | Out-File $status -Append
  if ($round -eq 3) { $res = & python "$t\vocab_verify.py" final 2>> "$V\verify_err.txt" }
  else { $res = & python "$t\vocab_verify.py" 2>> "$V\verify_err.txt" }
  "Round $round : $res" | Out-File $status -Append
  if ($res -match 'bad 0$') { break }
}
"ALL DONE $(Get-Date)" | Out-File $status -Append

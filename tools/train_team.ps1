# Full pipeline: examples -> LoRA training on the 3080 Ti -> merge -> GGUF -> 4-bit -> race-team-q4.gguf
$c = "$env:USERPROFILE\Documents\CrewChiefVoices"
$llm = "$c\llm"
$st = "$llm\TRAIN_STATUS.txt"
"start $(Get-Date)" | Out-File $st
Set-Location $c
& "$c\venv_eng\Scripts\python.exe" -m engineer.dataset "$llm\team_train.jsonl" 2>&1 | Select-Object -Last 1 | Out-File $st -Append
$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
$env:CUDA_VISIBLE_DEVICES = "0"
& "$c\venv_train\Scripts\python.exe" -m engineer.train_team "$llm\team_train.jsonl" 2>&1 | Out-File "$llm\train_stdout.txt"
if (-not (Test-Path "$llm\race-team-merged\config.json")) { "TRAINING FAILED $(Get-Date)" | Out-File $st -Append; exit 1 }
"trained $(Get-Date)" | Out-File $st -Append
& "$c\venv_train\Scripts\python.exe" "$llm\src\convert_hf_to_gguf.py" "$llm\race-team-merged" --outfile "$llm\race-team-f16.gguf" --outtype f16 2>&1 | Out-File "$llm\convert_log.txt"
$q = Get-ChildItem "$llm\bin" -Recurse -Filter "llama-quantize.exe" | Select-Object -First 1
& $q.FullName "$llm\race-team-f16.gguf" "$llm\models\race-team-q4.gguf" Q4_K_M 2>&1 | Out-File "$llm\quantize_log.txt"
if (Test-Path "$llm\models\race-team-q4.gguf") {
  Remove-Item "$llm\race-team-f16.gguf"
  "DONE $(Get-Date) $([math]::Round((Get-Item "$llm\models\race-team-q4.gguf").Length/1MB))MB" | Out-File $st -Append
} else { "CONVERT FAILED $(Get-Date)" | Out-File $st -Append }

$c = "$env:USERPROFILE\Documents\CrewChiefVoices"; $llm = "$c\llm"
Get-Process curl -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item "$llm\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf" -ErrorAction SilentlyContinue
& "$c\venv_train\Scripts\python.exe" "$llm\src\convert_hf_to_gguf.py" "$llm\base\Qwen3-4B-Instruct-2507" --outfile "$llm\base-f16.gguf" --outtype f16 2>&1 | Out-File "$llm\convert_base_log.txt"
$q = Get-ChildItem "$llm\bin" -Recurse -Filter "llama-quantize.exe" | Select-Object -First 1
& $q.FullName "$llm\base-f16.gguf" "$llm\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf" Q4_K_M 2>&1 | Out-File "$llm\quantize_base_log.txt"
Remove-Item "$llm\base-f16.gguf" -ErrorAction SilentlyContinue
"BASE GGUF $(Get-Date) $([math]::Round((Get-Item "$llm\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf").Length/1MB))MB" | Out-File "$llm\download_log.txt" -Append

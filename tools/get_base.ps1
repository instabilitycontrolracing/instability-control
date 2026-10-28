$me = $PID
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.ProcessId -ne $me -and $_.CommandLine -like '*get_llm.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
$hf = "$env:USERPROFILE\Documents\CrewChiefVoices\llm\base\Qwen3-4B-Instruct-2507"
New-Item -ItemType Directory -Force $hf | Out-Null
$u = "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/main"
foreach ($f in "config.json","generation_config.json","tokenizer.json","tokenizer_config.json","vocab.json","merges.txt","model.safetensors.index.json","LICENSE") { curl.exe -L -s -o "$hf\$f" "$u/$f" }
$jobs = foreach ($f in "model-00001-of-00003.safetensors","model-00002-of-00003.safetensors","model-00003-of-00003.safetensors") {
  Start-Process curl.exe -PassThru -WindowStyle Hidden -ArgumentList '-L','-s','-o',"`"$hf\$f`"","$u/$f"
}
$jobs | Wait-Process
"BASE DONE $(Get-Date)" | Out-File "$env:USERPROFILE\Documents\CrewChiefVoices\llm\download_log.txt" -Append

$c = "$env:USERPROFILE\Documents\CrewChiefVoices"
$d = "$c\asr"; New-Item -ItemType Directory -Force $d | Out-Null
$log = "$d\setup_log.txt"
"start $(Get-Date)" | Out-File $log
& "$c\venv_eng\Scripts\python.exe" -m pip install -q sherpa-onnx 2>&1 | Out-File $log -Append
& "$c\venv_eng\Scripts\python.exe" -c "import sherpa_onnx; print('sherpa', sherpa_onnx.__version__)" 2>&1 | Out-File $log -Append
$name = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
curl.exe -L -s -o "$d\$name.tar.bz2" "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$name.tar.bz2"
"downloaded $((Get-Item "$d\$name.tar.bz2").Length) $(Get-Date)" | Out-File $log -Append
tar -xjf "$d\$name.tar.bz2" -C $d 2>&1 | Out-File $log -Append
Remove-Item "$d\$name.tar.bz2"
Get-ChildItem "$d\$name" | % { "$($_.Name) $($_.Length)" } | Out-File $log -Append
"DONE $(Get-Date)" | Out-File $log -Append

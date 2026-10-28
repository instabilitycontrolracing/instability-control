$root = "$env:USERPROFILE\Documents\CrewChiefVoices"
$log = "$root\tools\setup_log.txt"
"START $(Get-Date)" | Out-File $log
$py = "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path "$root\venv\Scripts\python.exe")) { & $py -m venv "$root\venv" *>> $log }
$vp = "$root\venv\Scripts\python.exe"
& $vp -m pip install --upgrade pip wheel setuptools *>> $log
"== TORCH ==" | Out-File $log -Append
& $vp -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128 *>> $log
"== SEPARATOR ==" | Out-File $log -Append
& $vp -m pip install "audio-separator[gpu]" soundfile numpy *>> $log
"== AUDIOSRONNX ==" | Out-File $log -Append
& $vp -m pip install audiosronnx onnxruntime-gpu *>> $log
"== CHECK ==" | Out-File $log -Append
& $vp -c "import torch;print('TORCH',torch.__version__,torch.cuda.is_available(),[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])" *>> $log
& $vp -c "import onnxruntime as o;print('ORT',o.get_available_providers())" *>> $log
"DONE $(Get-Date)" | Out-File $log -Append

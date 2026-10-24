$root = "$env:USERPROFILE\Documents\CrewChiefVoices"
$log = "$root\tools\fix2_log.txt"
"START $(Get-Date)" | Out-File $log
$vp = "$root\venv\Scripts\python.exe"
& $vp -m pip install --force-reinstall --no-deps "onnxruntime-gpu==1.22.0" *>> $log
& $vp -m pip install --no-deps resemble-enhance *>> $log
& $vp -m pip install celluloid omegaconf rich resampy tabulate pandas matplotlib *>> $log
"== CHECK ==" | Out-File $log -Append
& $vp -c "import torch, onnxruntime as o;print('ORT',o.__version__,o.get_available_providers())" *>> $log
& $vp -c "import torch;print('TORCH',torch.__version__,torch.cuda.is_available())" *>> $log
& $vp -c "from resemble_enhance.enhancer.inference import denoise, enhance;print('RE ok')" *>> $log
"DONE $(Get-Date)" | Out-File $log -Append

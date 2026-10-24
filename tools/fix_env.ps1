$root = "$env:USERPROFILE\Documents\CrewChiefVoices"
$log = "$root\tools\fix_log.txt"
"START $(Get-Date)" | Out-File $log
$vp = "$root\venv\Scripts\python.exe"
& $vp -m pip install --force-reinstall --no-deps "torch==2.11.0" "torchaudio==2.11.0" "torchvision==0.26.0" --index-url https://download.pytorch.org/whl/cu128 *>> $log
& $vp -m pip uninstall -y onnxruntime *>> $log
& $vp -m pip install --force-reinstall --no-deps onnxruntime-gpu *>> $log
& $vp -m pip install --pre --upgrade --no-deps audiosronnx *>> $log
& $vp -m pip install nvidia-cudnn-cu12 nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 nvidia-cufft-cu12 nvidia-curand-cu12 *>> $log
"== CHECK ==" | Out-File $log -Append
& $vp -c "import torch;print('TORCH',torch.__version__,torch.cuda.is_available(),[torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])" *>> $log
& $vp -c "import torch, onnxruntime as o;print('ORT',o.__version__,o.get_available_providers())" *>> $log
& $vp -c "import audiosronnx,importlib.metadata as m;print('SR',m.version('audiosronnx'),[x for x in dir(audiosronnx) if not x.startswith('_')])" *>> $log
& $vp -c "import audio_separator;print('SEP ok')" *>> $log
"DONE $(Get-Date)" | Out-File $log -Append

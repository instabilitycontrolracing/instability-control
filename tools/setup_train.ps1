$c = "$env:USERPROFILE\Documents\CrewChiefVoices"
$log = "$c\llm\train_setup_log.txt"
"start $(Get-Date)" | Out-File $log
& "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\python.exe" -m venv "$c\venv_train" 2>&1 | Out-File $log -Append
$py = "$c\venv_train\Scripts\python.exe"
& $py -m pip install -q --upgrade pip 2>&1 | Out-File $log -Append
& $py -m pip install -q torch --index-url https://download.pytorch.org/whl/cu128 2>&1 | Out-File $log -Append
& $py -m pip install -q "transformers>=4.51,<5" peft accelerate safetensors sentencepiece "gguf>=0.10" numpy pyyaml pyirsdk 2>&1 | Out-File $log -Append
& $py -c "import torch, transformers, peft; print('torch', torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0)); print('transformers', transformers.__version__, 'peft', peft.__version__)" 2>&1 | Out-File $log -Append
# llama.cpp's converter script (HF -> GGUF), matching our runtime build
curl.exe -L -s -o "$c\llm\convert_hf_to_gguf.py" "https://raw.githubusercontent.com/ggml-org/llama.cpp/b11826/convert_hf_to_gguf.py"
"DONE $(Get-Date)" | Out-File $log -Append

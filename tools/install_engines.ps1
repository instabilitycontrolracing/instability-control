param([string]$which)
$root = "$env:USERPROFILE\Documents\CrewChiefVoices"
$py = "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\python.exe"
$log = "$root\tools\inst_$which.txt"
"START $(Get-Date)" | Out-File $log
$venv = "$root\venv_$which"
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv *>> $log }
$vp = "$venv\Scripts\python.exe"
& $vp -m pip install -q --upgrade pip wheel setuptools *>> $log
switch ($which) {
  "xtts" {
    & $vp -m pip install "torch==2.8.0" "torchaudio==2.8.0" --index-url https://download.pytorch.org/whl/cu128 *>> $log
    & $vp -m pip install coqui-tts soundfile *>> $log
    & $vp -c "import torch,TTS;print('CHECK',torch.__version__,torch.cuda.is_available(),TTS.__version__)" *>> $log
  }
  "chatterbox" {
    & $vp -m pip install "torch==2.6.0" "torchaudio==2.6.0" --index-url https://download.pytorch.org/whl/cu124 *>> $log
    & $vp -m pip install chatterbox-tts soundfile *>> $log
    & $vp -c "import torch;from chatterbox.tts import ChatterboxTTS;print('CHECK',torch.__version__,torch.cuda.is_available())" *>> $log
  }
  "f5" {
    & $vp -m pip install "torch==2.8.0" "torchaudio==2.8.0" --index-url https://download.pytorch.org/whl/cu128 *>> $log
    & $vp -m pip install f5-tts soundfile *>> $log
    & $vp -c "import torch;from f5_tts.api import F5TTS;print('CHECK',torch.__version__,torch.cuda.is_available())" *>> $log
  }
}
"DONE $(Get-Date)" | Out-File $log -Append

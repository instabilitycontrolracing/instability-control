$root = "$env:USERPROFILE\Documents\CrewChiefVoices"
$log = "$root\tools\inst_higgs2.txt"
"START $(Get-Date)" | Out-File $log
$py = "$env:USERPROFILE\AppData\Local\Programs\Python\Python312\python.exe"
$venv = "$root\venv_higgs2"
if (-not (Test-Path "$venv\Scripts\python.exe")) { & $py -m venv $venv *>> $log }
$vp = "$venv\Scripts\python.exe"
& $vp -m pip install -q --upgrade pip wheel "setuptools<81" *>> $log
& $vp -m pip install "torch==2.8.0" "torchaudio==2.8.0" "torchvision==0.23.0" --index-url https://download.pytorch.org/whl/cu128 *>> $log
# get the Higgs Audio code (zip, no git needed)
$src = "$root\higgs-audio"
if (-not (Test-Path "$src\setup.py")) {
  Invoke-WebRequest -Uri "https://github.com/boson-ai/higgs-audio/archive/refs/heads/main.zip" -OutFile "$root\higgs.zip"
  Expand-Archive "$root\higgs.zip" -DestinationPath "$root\higgs_tmp" -Force
  Move-Item "$root\higgs_tmp\higgs-audio-main" $src
  Remove-Item "$root\higgs_tmp" -Recurse -Force
}
& $vp -m pip install "transformers>=4.45.1,<4.47.0" descript-audio-codec librosa dacite json_repair pandas pydantic vector_quantize_pytorch loguru pydub omegaconf click langid jieba "accelerate>=0.26.0" bitsandbytes soundfile *>> $log
& $vp -m pip install --no-deps -e $src *>> $log
"== CHECK ==" | Out-File $log -Append
& $vp -c "import torch,transformers,bitsandbytes;print('CHECK',torch.__version__,torch.cuda.is_available(),transformers.__version__,bitsandbytes.__version__)" *>> $log
& $vp -c "from boson_multimodal.serve.serve_engine import HiggsAudioServeEngine;print('ENGINE ok')" *>> $log
"DONE $(Get-Date)" | Out-File $log -Append

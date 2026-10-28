$ErrorActionPreference = "Stop"
$c = "$env:USERPROFILE\Documents\CrewChiefVoices"
$llm = "$c\llm"; New-Item -ItemType Directory -Force "$llm\bin", "$llm\models" | Out-Null
$log = "$llm\download_log.txt"
"start $(Get-Date)" | Out-File $log
$ProgressPreference = "SilentlyContinue"
# 1) llama.cpp runtime (Vulkan: NVIDIA, AMD and Intel)
$zip = "$llm\llama-vulkan.zip"
Invoke-WebRequest "https://github.com/ggml-org/llama.cpp/releases/download/b11826/llama-b11826-bin-win-vulkan-x64.zip" -OutFile $zip
Expand-Archive $zip -DestinationPath "$llm\bin" -Force; Remove-Item $zip
"runtime ok $(Get-Date)" | Out-File $log -Append
# 2) base model, 4-bit (for the app until our fine-tuned one is ready)
curl.exe -L -s -o "$llm\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf" "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
"gguf ok $(Get-Date) $((Get-Item "$llm\models\Qwen3-4B-Instruct-2507-Q4_K_M.gguf").Length)" | Out-File $log -Append
# 3) full-precision weights for fine-tuning
$hf = "$llm\base\Qwen3-4B-Instruct-2507"; New-Item -ItemType Directory -Force $hf | Out-Null
foreach ($f in "config.json","generation_config.json","tokenizer.json","tokenizer_config.json","vocab.json","merges.txt","model.safetensors.index.json","model-00001-of-00003.safetensors","model-00002-of-00003.safetensors","model-00003-of-00003.safetensors","LICENSE") {
  curl.exe -L -s -o "$hf\$f" "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/resolve/main/$f"
}
"base ok $(Get-Date)" | Out-File $log -Append
"DONE" | Out-File $log -Append

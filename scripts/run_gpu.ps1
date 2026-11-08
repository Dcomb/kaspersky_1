param($Image = 'vllm/vllm-openai:v0.27.0')

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$tokenFile = Join-Path $env:TEMP 'api-token.txt'
$cache = Join-Path $repo 'models\gpu-hf-cache'
$app = Join-Path $repo 'app'

if (-not (Test-Path -LiteralPath $tokenFile)) {
    throw "API token file not found: $tokenFile"
}

# The official CUDA image is large. Keep host-disk headroom for extraction.
$localImages = @(docker image ls --format '{{.Repository}}:{{.Tag}}')
if ($LASTEXITCODE -ne 0) {
    throw 'Could not list local Docker images'
}
if ($Image -notin $localImages) {
    $drive = [IO.DriveInfo]::new((Get-Item -LiteralPath $repo).PSDrive.Root)
    if ($drive.AvailableFreeSpace -lt 30GB) {
        throw "Only $([math]::Round($drive.AvailableFreeSpace / 1GB, 1)) GiB free on $($drive.Name). Free at least 30 GiB before pulling the CUDA image."
    }
    if ($drive.AvailableFreeSpace -lt 45GB) {
        Write-Warning "Only $([math]::Round($drive.AvailableFreeSpace / 1GB, 1)) GiB free on $($drive.Name). The CUDA image is large; monitor free disk space during the pull."
    }
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
$env:VLLM_API_KEY = [IO.File]::ReadAllText($tokenFile).Trim()
if (-not $env:VLLM_API_KEY) {
    throw 'API token file is empty'
}

try {
    docker run --rm --name inference-gpu `
        --gpus all --user 2000:0 `
        --security-opt no-new-privileges --cap-drop ALL `
        --memory 6g --shm-size 512m `
        --publish 127.0.0.1:8000:8000 `
        --env VLLM_API_KEY `
        --env VLLM_USE_V2_MODEL_RUNNER=0 `
        --env PYTHONPATH=/opt/service `
        --env HF_HOME=/home/vllm/.cache/huggingface `
        --mount "type=bind,source=$app,target=/opt/service/app,readonly" `
        --mount "type=bind,source=$cache,target=/home/vllm/.cache/huggingface" `
        --entrypoint vllm $Image `
        serve Qwen/Qwen2.5-0.5B-Instruct `
        --revision 7ae557604adf67be50417f59c2c2f167def9a775 `
        --served-model-name Qwen/Qwen2.5-0.5B-Instruct `
        --host 0.0.0.0 --port 8000 `
        --dtype bfloat16 --max-model-len 1024 `
        --max-num-seqs 1 --max-num-batched-tokens 1024 `
        --gpu-memory-utilization 0.5 `
        --middleware app.middleware.audit_and_auth `
        --no-enable-log-requests --no-enable-log-outputs `
        --disable-uvicorn-access-log --uvicorn-log-level warning
    if ($LASTEXITCODE -ne 0) {
        throw "GPU container exited with code $LASTEXITCODE"
    }
}
finally {
    Remove-Item Env:VLLM_API_KEY -ErrorAction SilentlyContinue
}

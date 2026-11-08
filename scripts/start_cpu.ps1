param([switch]$RebuildImages)

$repo = Split-Path -Parent $PSScriptRoot
$k8s = Join-Path $repo 'k8s'
$apiFile = Join-Path $env:TEMP 'api-token.txt'
$hfFile = Join-Path $env:TEMP 'hf-token.txt'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is not installed or is not on PATH'
}
if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) {
    throw 'Minikube is not installed or is not on PATH'
}

docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running' }
$gpuContainers = @(docker ps --filter 'name=inference-gpu' --format '{{.Names}}')
if ($LASTEXITCODE -ne 0) { throw 'Could not check running Docker containers' }
if ('inference-gpu' -in $gpuContainers) {
    throw 'Stop the GPU container before starting the memory-intensive CPU cluster'
}

minikube start --driver=docker --cpus=4 --memory=6500 --disk-size=25g
if ($LASTEXITCODE -ne 0) { throw 'Minikube failed to start' }

$clusterImages = @(minikube image ls --format short)
if ($LASTEXITCODE -ne 0) { throw 'Could not list Minikube images' }
$localImages = @(docker image ls --format '{{.Repository}}:{{.Tag}}')
if ($LASTEXITCODE -ne 0) { throw 'Could not list Docker images' }

$images = @(
    @{ Name = 'vllm-cpu-private:0.1.0'; File = 'Dockerfile' },
    @{ Name = 'vllm-downloader:0.1.0'; File = 'Dockerfile.downloader' }
)
foreach ($item in $images) {
    $name = $item.Name
    $present = @($clusterImages | Where-Object {
        $_ -match ('(^|/)' + [regex]::Escape($name) + '$')
    }).Count -gt 0
    if ($RebuildImages -or -not $present) {
        if ($RebuildImages -or $name -notin $localImages) {
            Write-Host "Building $name (this can take a while)..."
            docker build -t $name -f (Join-Path $repo $item.File) $repo
            if ($LASTEXITCODE -ne 0) { throw "Could not build $name" }
        }
        Write-Host "Loading $name into Minikube..."
        minikube image load $name --overwrite
        if ($LASTEXITCODE -ne 0) { throw "Could not load $name into Minikube" }
    }
}

minikube kubectl -- get secret inference-secrets -o name 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    if (-not (Test-Path -LiteralPath $apiFile)) {
        [IO.File]::WriteAllText($apiFile, ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')))
    }
    if (-not (Test-Path -LiteralPath $hfFile)) {
        [IO.File]::WriteAllText($hfFile, '')
    }
    minikube kubectl -- create secret generic inference-secrets --from-file="hf-token=$hfFile" --from-file="api-token=$apiFile"
    if ($LASTEXITCODE -ne 0) { throw 'Could not create inference-secrets' }
} elseif (-not (Test-Path -LiteralPath $apiFile)) {
    throw "The cluster Secret exists but the local API token file is missing: $apiFile"
}

minikube kubectl -- apply -k $k8s
if ($LASTEXITCODE -ne 0) { throw 'Could not apply Kubernetes manifests' }
minikube kubectl -- scale deployment/inference-api --replicas=1
if ($LASTEXITCODE -ne 0) { throw 'Could not scale inference-api' }
if ($RebuildImages) {
    minikube kubectl -- rollout restart deployment/inference-api
    if ($LASTEXITCODE -ne 0) { throw 'Could not restart inference-api' }
}
minikube kubectl -- rollout status deployment/inference-api --timeout=20m
if ($LASTEXITCODE -ne 0) { throw 'Inference API did not become ready' }

Write-Host 'Inference API is ready at http://127.0.0.1:8000. Keep this window open for port-forward.'
minikube kubectl -- port-forward service/inference-api 8000:8000

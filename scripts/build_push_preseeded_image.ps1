Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Setting {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Default = ""
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $Default
    }
    return $value
}

function Run-Docker {
    param([string[]]$DockerArgs)

    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker command failed: docker $($DockerArgs -join ' ')"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker was not found. Install Docker Desktop or Docker Engine and retry."
    exit 1
}

$imageName = Resolve-Setting -Name "IMAGE_NAME" -Default "ghcr.io/wenjun-mao/ebook2m4b"
$imageTag = Resolve-Setting -Name "IMAGE_TAG" -Default "latest"
$push = Resolve-Setting -Name "PUSH" -Default "1"
$platform = Resolve-Setting -Name "PLATFORM" -Default "linux/amd64"
$dockerfilePath = Resolve-Setting -Name "DOCKERFILE_PATH" -Default (Join-Path $repoRoot "Dockerfile")

$kokoroModelId = Resolve-Setting -Name "KOKORO_MODEL_ID" -Default "hexgrad/Kokoro-82M"
$kokoroModelRevision = Resolve-Setting -Name "KOKORO_MODEL_REVISION" -Default "f3ff3571791e39611d31c381e3a41a3af07b4987"
$preseedKokoro = Resolve-Setting -Name "PRESEED_KOKORO" -Default "1"

if (-not (Test-Path -LiteralPath $dockerfilePath)) {
    Write-Error "Dockerfile not found at $dockerfilePath"
    exit 1
}

$ghcrToken = Resolve-Setting -Name "GHCR_TOKEN" -Default ""
if ($imageName.StartsWith("ghcr.io/") -and -not [string]::IsNullOrWhiteSpace($ghcrToken)) {
    $defaultUser = $imageName.Substring("ghcr.io/".Length).Split("/")[0]
    $ghcrUsername = Resolve-Setting -Name "GHCR_USERNAME" -Default $defaultUser

    Write-Host "Logging in to ghcr.io as $ghcrUsername ..."
    $ghcrToken | docker login ghcr.io -u $ghcrUsername --password-stdin
    if ($LASTEXITCODE -ne 0) {
        throw "docker login to ghcr.io failed"
    }
}

$tags = @("$imageName`:$imageTag")

Write-Host "Building preseeded image with:"
Write-Host "  Image: $imageName"
Write-Host "  Tag: $imageTag"
Write-Host "  Platform: $platform"
Write-Host "  Kokoro model: $kokoroModelId@$kokoroModelRevision"
Write-Host "  Preseed Kokoro: $preseedKokoro"

$buildArgs = @(
    "--build-arg", "KOKORO_MODEL_ID=$kokoroModelId",
    "--build-arg", "KOKORO_MODEL_REVISION=$kokoroModelRevision",
    "--build-arg", "PRESEED_KOKORO=$preseedKokoro"
)

$tagArgs = @()
foreach ($tag in $tags) {
    $tagArgs += @("--tag", $tag)
}

& docker buildx version *> $null
$hasBuildx = $LASTEXITCODE -eq 0

if ($hasBuildx) {
    $modeFlag = if ($push -eq "1") { "--push" } else { "--load" }

    $dockerArgs = @(
        "buildx", "build",
        "--platform", $platform,
        "--file", $dockerfilePath
    ) + $buildArgs + $tagArgs + @($modeFlag, $repoRoot)

    Run-Docker -DockerArgs $dockerArgs
} else {
    $dockerArgs = @("build", "--file", $dockerfilePath) + $buildArgs + $tagArgs + @($repoRoot)
    Run-Docker -DockerArgs $dockerArgs

    if ($push -eq "1") {
        foreach ($tag in $tags) {
            Run-Docker -DockerArgs @("push", $tag)
        }
    }
}

Write-Host "Done. Built image tags:"
foreach ($tag in $tags) {
    Write-Host "  $tag"
}

Write-Host ""
Write-Host "Suggested runtime env (already defaulted in compose.yaml):"
Write-Host "  EBOOK2M4B_HF_HOME=/opt/huggingface"
Write-Host "  EBOOK2M4B_TRANSFORMERS_CACHE=/opt/huggingface"
Write-Host "  EBOOK2M4B_NLTK_DATA=/opt/nltk_data"
Write-Host "  EBOOK2M4B_HF_HUB_OFFLINE=1"

Write-Host ""
Write-Host "If you want to pull this image on another host, set:"
Write-Host "  IMAGE_NAME=$imageName"
Write-Host "  IMAGE_TAG=$imageTag"

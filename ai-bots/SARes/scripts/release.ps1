param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$Framework = "net8.0-windows10.0.19041.0"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir
$publishRoot = Join-Path $repoRoot "release"
$publishDir = Join-Path $publishRoot "publish"
$distDir = Join-Path $repoRoot "dist"

Write-Host "Cleaning previous outputs..."
Remove-Item -LiteralPath $publishRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $distDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Publishing SARes ($Configuration/$Runtime)..."
$publishArgs = @(
    "publish",
    "$repoRoot\SARes.csproj",
    "--configuration", $Configuration,
    "--runtime", $Runtime,
    "/p:PublishSingleFile=true",
    "/p:IncludeNativeLibrariesForSelfExtract=true",
    "/p:IncludeAllContentForSelfExtract=true",
    "/p:SelfContained=true",
    "/p:TrimUnusedDependencies=false",
    "-o", $publishDir
)
dotnet @publishArgs

Write-Host "Copying assets..."
Copy-Item -Path (Join-Path $repoRoot "assets") -Destination (Join-Path $publishDir "assets") -Recurse -Force

Write-Host "Preparing distribution bundle..."
New-Item -ItemType Directory -Path $distDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMddHHmm"
$zipName = "SARes-$timestamp.zip"
$zipPath = Join-Path $distDir $zipName

Write-Host "Creating $zipName..."
Compress-Archive -Path (Join-Path $publishDir "*") -DestinationPath $zipPath -Force

Write-Host "Release bundle ready at: $zipPath"

$ErrorActionPreference = "Stop"

$project = Join-Path $PSScriptRoot "DiskInsight.csproj"
$output = Join-Path $PSScriptRoot "publish\Release\net8.0-windows"
$staging = Join-Path $PSScriptRoot "publish\.staging\Release\net8.0-windows"

if (Test-Path $staging)
{
  Remove-Item -Recurse -Force $staging
}

dotnet publish $project -c Release -f net8.0-windows -o $staging
if ($LASTEXITCODE -ne 0)
{
  throw "dotnet publish failed (exit code: $LASTEXITCODE)"
}

$null = New-Item -ItemType Directory -Force -Path $output
robocopy $staging $output /E /COPY:DAT /R:120 /W:1 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8)
{
  throw "robocopy failed (exit code: $LASTEXITCODE). If DiskInsight is running, close it and rerun publish.ps1."
}

Write-Host "Published to: $output"

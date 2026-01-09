param(
  [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$project = Join-Path $PSScriptRoot "DiskInsight.csproj"
$output = Join-Path $PSScriptRoot ("publish\\{0}\\net8.0-windows" -f $Configuration)

dotnet publish $project -c $Configuration -o $output

Write-Host "Published to: $output"

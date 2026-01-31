param(
  [string]$InputMarkdown = (Join-Path $PSScriptRoot "PainRadar-HowItWorks.md"),
  [string]$OutputPdf = (Join-Path $PSScriptRoot "PainRadar-HowItWorks.pdf")
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $InputMarkdown)) {
  throw "Markdown not found: $InputMarkdown"
}

$md = Get-Content $InputMarkdown -Raw

if (Get-Command pandoc -ErrorAction SilentlyContinue) {
  pandoc $InputMarkdown -o $OutputPdf 2>$null
  if (Test-Path $OutputPdf) {
    Write-Host "Wrote PDF: $OutputPdf"
    exit 0
  }
}

# Prefer a self-contained .NET generator (no Edge/Chrome required)
$toolProject = Join-Path $PSScriptRoot "..\\tools\\PainRadarDocsToPdf\\PainRadarDocsToPdf.csproj"
if (Test-Path $toolProject) {
  dotnet run --project $toolProject -- -i $InputMarkdown -o $OutputPdf
  if (Test-Path $OutputPdf) {
    Write-Host "Wrote PDF: $OutputPdf"
    exit 0
  }
}

throw "Unable to generate PDF. Ensure the docs tool exists at: $toolProject"

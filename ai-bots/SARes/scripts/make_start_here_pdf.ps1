$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$assetsDir = Join-Path $repoRoot "assets"
$helpDir = Join-Path $assetsDir "help"
$cssDir = Join-Path $assetsDir "css"

$md = Join-Path $helpDir "start_here.md"
$css = Join-Path $cssDir "help.css"
$outPdf = Join-Path $helpDir "start_here.pdf"

if (!(Test-Path $md)) { throw "Missing markdown source: $md" }
if (!(Test-Path $css)) { throw "Missing CSS: $css" }

$pandoc = (Get-Command pandoc -ErrorAction SilentlyContinue)?.Source
if (!$pandoc) { throw "pandoc not found on PATH. Install pandoc first." }

$wk = (Get-Command wkhtmltopdf -ErrorAction SilentlyContinue)?.Source
if (!$wk) { throw "wkhtmltopdf not found on PATH. Install wkhtmltopdf first." }

Write-Host "pandoc: $pandoc"
Write-Host "wkhtmltopdf: $wk"
Write-Host "Rendering: $md -> $outPdf"

& $pandoc "`"$md`"" `
  --standalone `
  --from=gfm `
  "--css=`"$css`"" `
  "--pdf-engine=`"$wk`"" `
  -o "`"$outPdf`""

if (!(Test-Path $outPdf)) { throw "Failed to create: $outPdf" }
Write-Host "Done: $outPdf"


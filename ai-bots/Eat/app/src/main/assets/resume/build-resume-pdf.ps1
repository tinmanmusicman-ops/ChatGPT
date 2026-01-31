param(
    [switch]$Watch
)

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Definition
$resumeMd = Join-Path $scriptDirectory "resume.md"
$northPdf = Join-Path $scriptDirectory "resume-north.pdf"
$darkCss = Join-Path $scriptDirectory "dark.css"
$darkPdf = Join-Path $scriptDirectory "resume-dark.pdf"

function Get-ToolPath {
    param(
        [string]$Name,
        [string]$Potential
    )
    $resolved = (Get-Command $Name -ErrorAction SilentlyContinue)?.Source
    if ($resolved) {
        return $resolved
    }
    if ($Potential -and (Test-Path $Potential)) {
        return $Potential
    }
    return $null
}

$pandocPath = Get-ToolPath -Name "pandoc" -Potential (Join-Path $env:LOCALAPPDATA "Pandoc\pandoc.exe")
$wkhtmlPath = Get-ToolPath -Name "wkhtmltopdf" -Potential "C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"

if (-not (Test-Path $resumeMd)) {
    Write-Error "Missing source Markdown at $resumeMd"
    exit 1
}

if (-not $pandocPath) {
    Write-Error "Pandoc executable not found. Install it or add it to PATH."
    exit 1
}

if (-not $wkhtmlPath) {
    Write-Error "wkhtmltopdf executable not found. Install it or add it to PATH."
    exit 1
}

function Invoke-Conversion {
    param(
        [string]$OutputPath,
        [string]$CssFile
    )

    $arguments = @(
        $resumeMd,
        "-o",
        $OutputPath,
        "--pdf-engine",
        $wkhtmlPath
    )
    if ($CssFile -and (Test-Path $CssFile)) {
        $arguments += "--css"
        $arguments += $CssFile
    }

    Write-Host "Rendering $OutputPath..."
    $process = Start-Process -FilePath $pandocPath -ArgumentList $arguments -NoNewWindow -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "Pandoc failed with exit code $($process.ExitCode)."
    }
}

function ConvertAll {
    Invoke-Conversion -OutputPath $northPdf -CssFile $null
    Invoke-Conversion -OutputPath $darkPdf -CssFile $darkCss
}

ConvertAll

if ($Watch) {
    Write-Host "Watching $resumeMd and dark.css for changes. Press Ctrl+C to stop."
    $watcher = New-Object System.IO.FileSystemWatcher
    $watcher.Path = $scriptDirectory
    $watcher.IncludeSubdirectories = $false
    $watcher.NotifyFilter = [System.IO.NotifyFilters]'LastWrite, FileName'
    $watcher.Filter = "*.*"
    $action = {
        $path = $Event.SourceEventArgs.FullPath
        if ($path -in $resumeMd, $darkCss) {
            Start-Sleep -Milliseconds 200
            ConvertAll
        }
    }
    $registrations = @()
    $registrations += Register-ObjectEvent -InputObject $watcher -EventName Changed -Action $action
    $registrations += Register-ObjectEvent -InputObject $watcher -EventName Created -Action $action
    $registrations += Register-ObjectEvent -InputObject $watcher -EventName Renamed -Action $action
    $registrations += Register-ObjectEvent -InputObject $watcher -EventName Deleted -Action $action
    $watcher.EnableRaisingEvents = $true
    try {
        while ($true) {
            Start-Sleep -Seconds 1
        }
    } finally {
        foreach ($registration in $registrations) {
            Unregister-Event -SourceIdentifier $registration.SourceIdentifier -ErrorAction SilentlyContinue
            Remove-Job -Name $registration.Name -ErrorAction SilentlyContinue
        }
        $watcher.Dispose()
    }
}

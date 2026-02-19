param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [int]$Tail = 50,

    [switch]$NoWait
)

$ErrorActionPreference = "Stop"

try {
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    Write-Host "Tailing file: $resolved"
    if ($NoWait) {
        Write-Host "Showing last $Tail lines."
        Get-Content -LiteralPath $resolved -Tail $Tail
    }
    else {
        Write-Host "Showing last $Tail lines. Press Ctrl+C to stop."
        Get-Content -LiteralPath $resolved -Tail $Tail -Wait
    }
}
catch {
    Write-Error "Tail failed: $($_.Exception.Message)"
    exit 1
}

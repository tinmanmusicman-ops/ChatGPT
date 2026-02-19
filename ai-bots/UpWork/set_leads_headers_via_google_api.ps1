param(
  [Parameter(Mandatory = $true)]
  [string]$AccessToken,

  [string]$SpreadsheetId = "1y1bvxJIiJB-XhdJAJkFH1ngyOrWB29RwJeiFALiQCWw",
  [string]$SheetName = "Leads",
  [switch]$FillRowNumbers
)

$ErrorActionPreference = "Stop"

$HeadersRow = @(
  "rowNumber",
  "company",
  "website",
  "industry",
  "country",
  "notes",
  "status",
  "eligibility",
  "icp_classification",
  "tier",
  "confidence_score",
  "reasoning",
  "enriched_website",
  "manual_review",
  "manual_review_reason",
  "error_code",
  "processed_at_utc",
  "request_id"
)

function Invoke-GoogleApi {
  param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("GET", "PUT", "POST")]
    [string]$Method,

    [Parameter(Mandatory = $true)]
    [string]$Uri,

    [object]$Body
  )

  $requestHeaders = @{
    Authorization = "Bearer $AccessToken"
  }

  if ($null -ne $Body) {
    $jsonBody = $Body | ConvertTo-Json -Depth 20 -Compress
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $requestHeaders -ContentType "application/json" -Body $jsonBody
  }

  return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $requestHeaders
}

try {
  $headerRange = "$SheetName!A1:R1"
  $headerRangeEncoded = [uri]::EscapeDataString($headerRange)
  $headerUri = "https://sheets.googleapis.com/v4/spreadsheets/$SpreadsheetId/values/$headerRangeEncoded?valueInputOption=RAW"

  $headerPayload = @{
    range = $headerRange
    majorDimension = "ROWS"
    values = @(@($HeadersRow))
  }

  Invoke-GoogleApi -Method PUT -Uri $headerUri -Body $headerPayload | Out-Null
  Write-Output "Headers written to $headerRange"

  if ($FillRowNumbers) {
    # Count active lead rows using column B (company), starting row 2.
    $companyRange = "$SheetName!B2:B"
    $companyRangeEncoded = [uri]::EscapeDataString($companyRange)
    $companyReadUri = "https://sheets.googleapis.com/v4/spreadsheets/$SpreadsheetId/values/$companyRangeEncoded"
    $companyRead = Invoke-GoogleApi -Method GET -Uri $companyReadUri

    $rowCount = 0
    if ($companyRead.values) {
      $rowCount = @($companyRead.values).Count
    }

    if ($rowCount -gt 0) {
      $lastRow = $rowCount + 1
      $rowRange = "$SheetName!A2:A$lastRow"
      $rowRangeEncoded = [uri]::EscapeDataString($rowRange)
      $rowUri = "https://sheets.googleapis.com/v4/spreadsheets/$SpreadsheetId/values/$rowRangeEncoded?valueInputOption=RAW"

      $rowValues = @()
      for ($r = 2; $r -le $lastRow; $r++) {
        $rowValues += ,@($r)
      }

      $rowPayload = @{
        range = $rowRange
        majorDimension = "ROWS"
        values = $rowValues
      }

      Invoke-GoogleApi -Method PUT -Uri $rowUri -Body $rowPayload | Out-Null
      Write-Output "rowNumber values written to $rowRange"
    } else {
      Write-Output "No existing data rows found in column B; skipped FillRowNumbers."
    }
  }

  Write-Output "Done."
}
catch {
  Write-Error ("FAIL-FAST: " + $_.Exception.Message)
  exit 1
}

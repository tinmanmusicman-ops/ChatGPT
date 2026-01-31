# PainRadar Phase 1 — Core Extraction (net8.0)

Goal: extract a platform-neutral core library for a future standalone mobile app, while keeping the existing WPF desktop app building and behaving the same.

## What was added
- `C:\ChatGPT\ai-bots\PainRadar.Core\PainRadar.Core.csproj` (class library targeting `net8.0`)
- `C:\ChatGPT\ai-bots\PainRadar.CoreHarness\PainRadar.CoreHarness.csproj` (console harness to prove the core runs headlessly)
- Minimal logging abstraction: `PainRadar.Infrastructure.IPainRadarLogger` in `C:\ChatGPT\ai-bots\PainRadar.Core\Infrastructure\IPainRadarLogger.cs`

## What was moved into the core library
- `Models/*`
- `Infrastructure/ObservableObject.cs`
- Portable services (HttpClient + pure logic):
  - `Services/PainAnalyzer.cs`
  - `Services/ScanOrchestrator.cs`
  - `Services/IJobSource.cs`
  - `Services/TextSanitizer.cs`
  - `Services/AppHttpClient.cs`
  - `Services/RemotiveJobSource.cs`
  - `Services/RemoteOkJobSource.cs`
  - `Services/MuseJobSource.cs`
  - `Services/RedditSearchService.cs`
  - `Services/GooglePlacesService.cs`
  - `Services/CompanySmbFilter.cs`

## Desktop behavior preservation
- WPF app now references the core via project reference: `C:\ChatGPT\ai-bots\PainRadar\PainRadar.csproj`
- Core logging is routed back to the existing desktop log file via adapter:
  - `C:\ChatGPT\ai-bots\PainRadar\Infrastructure\AppLoggerAdapter.cs`
  - wired in `C:\ChatGPT\ai-bots\PainRadar\App.xaml.cs`

## Deferred (explicitly)
- MAUI project creation
- Android/iOS UI
- Google Sheets export (remains desktop-only)
- Background execution work

## Build verification
- `dotnet build -c Release` succeeds for:
  - `C:\ChatGPT\ai-bots\PainRadar.Core\PainRadar.Core.csproj`
  - `C:\ChatGPT\ai-bots\PainRadar.CoreHarness\PainRadar.CoreHarness.csproj`
  - `C:\ChatGPT\ai-bots\PainRadar\PainRadar.csproj`


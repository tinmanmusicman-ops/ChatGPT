# PainRadar — How It Works (Detailed)

PainRadar is a Windows desktop (WPF) application that aggregates “operational pain” signals about companies from public job feeds and optional enrichment sources, scores them, and lets you explore the results interactively.

The app is intentionally “lightweight MVVM”: it uses a small ViewModel layer, async services, and WPF bindings—without a heavy DI framework or third‑party UI libraries.

---

## What You See (User Experience)

### Main Window Layout

The UI is split into three major areas:

1. **Top Command Bar**
   - Search box (filters results live)
   - Minimum Total Score slider (filters results live)
   - Toggles for each data source:
     - Remotive
     - RemoteOK
     - The Muse
     - Reddit (enrichment)
     - Google Reviews (enrichment)
   - Buttons:
     - **Scan**: starts an async scan
     - **Cancel**: cancels the current scan

2. **Center Content**
   - **Left: DataGrid (table)** showing all signals, sortable by columns
   - **Right: Detail Panel** showing expanded information for the selected row

3. **Bottom Status Bar**
   - Progress bar (0–100%)
   - Status text (“Fetching jobs…”, “Scoring job text…”, etc.)

### DataGrid Columns

Each row represents one “signal” (a job posting + enrichment) with computed scores:

- **TotalScore**: sum of PainScore + GrowthScore + RedditScore + GoogleScore
- **Company**
- **JobTitle** (clickable hyperlink)
- **Location**
- **Source** (Remotive / RemoteOK / TheMuse)
- **PainScore**
- **GrowthScore**
- **RedditScore**
- **GoogleScore**

### Clickable Hyperlinks

- **JobTitle** opens the job posting URL in your default browser.
- In the **detail panel**, “Source URLs” lists:
  - the job posting link
  - matching Reddit post links (when Reddit enrichment is enabled)
  - the Google Place URL (when Google enrichment is enabled and a place is found)

### Detail Panel Contents

When you select a row, the right panel shows:

- Company name
- Job title
- Score breakdown (Total / Pain / Growth / Reddit / Google)
- Matched keywords “chips”
- Source URLs (hyperlinks)
- Full job description (plain text, non-editable)

---

## Where the Data Comes From

PainRadar pulls from a combination of “job signals” and “enrichment signals”.

### Job Signal Sources (Primary)

These sources create the initial row set.

#### 1) Remotive Jobs (public API)
- Endpoint: `https://remotive.com/api/remote-jobs`
- Optional search: `?search=<term>`
- Parsed fields:
  - `title`
  - `company_name`
  - `candidate_required_location`
  - `url`
  - `description` (HTML → plain text)
- Code: `ai-bots/PainRadar/Services/RemotiveJobSource.cs`

#### 2) RemoteOK (public JSON feed)
- Endpoint: `https://remoteok.com/api`
- Feed includes a “legal” object; those entries are skipped.
- Parsed fields:
  - `position`
  - `company`
  - `location`
  - `url`
  - `description` (HTML → plain text)
- Code: `ai-bots/PainRadar/Services/RemoteOkJobSource.cs`

#### 3) The Muse (public jobs API)
- Endpoint: `https://www.themuse.com/api/public/jobs?page=<n>`
- The Muse API is paginated; PainRadar will page up to 10 pages or until it has enough results.
- Parsed fields:
  - job name: `name`
  - landing page: `refs.landing_page`
  - company: `company.name`
  - first location: `locations[0].name`
  - contents: `contents` (HTML → plain text)
- Code: `ai-bots/PainRadar/Services/MuseJobSource.cs`

### Enrichment Sources (Optional)

Enrichment does not create new rows; it adds additional signals to companies already found from job posts.

#### 4) Reddit Search (public JSON, no auth)
- Endpoint: `https://www.reddit.com/search.json?...`
- Query pattern:
  - `"CompanyName" (manual OR workaround OR broken OR coordination OR follow-up OR disorganized OR inefficient OR scaling OR ambiguity)`
- Returns search results (“posts”); PainRadar inspects:
  - post title
  - post selftext
  - permalink (used to create clickable URLs)
- Code: `ai-bots/PainRadar/Services/RedditSearchService.cs`

#### 5) Google Places Reviews (optional; requires API key)
Two-step process:

1) **Text Search** to find a `place_id`
   - `https://maps.googleapis.com/maps/api/place/textsearch/json?query=<company>&key=<key>`
2) **Place Details** to fetch review text
   - `https://maps.googleapis.com/maps/api/place/details/json?place_id=<id>&fields=name,url,reviews&key=<key>`

PainRadar scans each returned review’s `text` for pain keywords and scores matches.

Code: `ai-bots/PainRadar/Services/GooglePlacesService.cs`

---

## Text Normalization (HTML → Plain Text)

Job APIs often return descriptions as HTML. PainRadar converts those to plain text before analysis so keyword matching is predictable and the description reads cleanly in the UI.

Key behaviors:

- Replaces common breaks (`<br>`, `</p>`, `</li>`) with whitespace/newlines
- Strips remaining tags via regex
- HTML-decodes entities (`&amp;`, etc.)
- Collapses repeated whitespace

Code: `ai-bots/PainRadar/Services/TextSanitizer.cs`

---

## Pain Detection + Growth/Chaos Detection

PainRadar assigns scores by matching phrases in job titles and job descriptions, then optionally boosts per-company scores using Reddit and Google reviews.

### Keyword Sets

#### Operational Pain Keywords (high weight in job text, high weight in Google)

From code (`PainAnalyzer.PainKeywords`):

- manual
- workaround
- broken
- coordination
- follow-up
- multiple systems
- high volume
- disorganized
- inefficient

#### Growth / Chaos Keywords (bonus)

From code (`PainAnalyzer.GrowthKeywords`):

- fast-paced / fast paced
- wear many hats / wearing many hats
- scaling
- ambiguity
- ownership

Code: `ai-bots/PainRadar/Services/PainAnalyzer.cs`

### Matching Behavior

The analyzer lowercases the combined text:

- `title + "\n" + description`

Then checks whether each keyword appears as a substring.

This is intentionally simple:

- fast and explainable
- no external NLP dependencies
- deterministic results

Tradeoffs:

- substring matching can create false positives (“manual” in an unrelated context)
- not token-aware (doesn’t check word boundaries)

---

## Scoring Model (What the Numbers Mean)

All scores are additive and visible per row.

### Job Text Scoring (per row)

Computed in `PainAnalyzer.AnalyzeJob()`:

- **PainScore** = (number of matched pain keywords) × 20
- **GrowthScore** = (number of matched growth keywords) × 5

### Reddit Scoring (per company; applied to all rows for that company)

Computed in `RedditSearchService.SearchCompanyAsync()`:

- For each Reddit result, if a pain keyword appears in title/selftext:
  - add that keyword to matched list
  - add **+5** points per keyword match

This is a “medium weight” signal: enough to matter, but generally not overpowering job-text pain.

### Google Reviews Scoring (per company; applied to all rows for that company)

Computed in `GooglePlacesService.GetCompanyReviewSignalsAsync()`:

- For each Place Review `text`, if a pain keyword appears:
  - add that keyword to matched list
  - add **+10** points per keyword match

This is treated as a “high weight” signal because reviews can capture real operational dysfunction.

### TotalScore

Computed per row in `SignalItem.TotalScore`:

```
TotalScore = PainScore + GrowthScore + RedditScore + GoogleScore
```

---

## Deduplication (Avoiding Repeated Rows)

After fetching jobs from all enabled sources, PainRadar deduplicates rows using:

- Company + JobTitle + JobUrl

This prevents (most) duplicates when different sources point to the same posting.

Code: `ai-bots/PainRadar/Services/ScanOrchestrator.cs` (private `Deduplicate`)

---

## Enrichment Strategy (Performance + Relevance)

PainRadar does not enrich every company found. Instead it:

1) Groups rows by company
2) Ranks companies by their best (PainScore + GrowthScore)
3) Takes the top N companies (configurable)
4) Runs enrichment concurrently (configurable concurrency)
5) Applies the resulting per-company enrichment to all rows belonging to that company

This keeps scans fast and limits external API calls.

Key options:

- `MaxCompaniesToEnrich`
- `MaxEnrichmentConcurrency`
- `RedditSearchLimit`

Code: `ai-bots/PainRadar/Services/ScanOrchestrator.cs`

---

## Async, Cancellation, and Progress (Engineering Behavior)

### Async/Await Everywhere

All network calls use `HttpClient` with async APIs:

- `GetAsync(...)`
- `ReadAsStreamAsync(...)`
- `JsonDocument.ParseAsync(...)`

### CancellationToken Support

The scan is cancellable from the UI:

- `MainViewModel` creates a `CancellationTokenSource` when scanning starts
- Cancel button calls `Cancel()`
- The orchestrator and services accept and pass through `CancellationToken`

On cancel:

- An `OperationCanceledException` is thrown
- UI status becomes “Canceled”

### Progress Reporting

PainRadar reports progress via `IProgress<ScanProgress>`:

Stages include:

- Fetching jobs
- Scoring job text
- Enriching companies
- Applying enrichment

UI binds:

- `ProgressPercent` to a progress bar
- `StatusText` to the status bar text

Code:

- `ai-bots/PainRadar/ViewModels/MainViewModel.cs`
- `ai-bots/PainRadar/Models/ScanProgress.cs`

---

## Error Handling (Graceful Failure)

PainRadar is designed to continue when a source is unavailable:

- Each job source fetch is wrapped so a failure does not crash the scan.
- Each enrichment call is isolated so a failure does not stop other companies from enriching.

Net effect:

- If one API is down, you still get results from other sources.
- Errors are not spammed into the UI; the scan completes with partial coverage.

Code: `ai-bots/PainRadar/Services/ScanOrchestrator.cs`

---

## Configuration and Secrets (How the App Reads Keys Safely)

PainRadar loads configuration from a JSON file that includes a `PainRadar` section.

### Config File Discovery

The app checks config in this order:

1) If `PAINRADAR_CONFIG_PATH` env var is set, it uses that path first.
2) Otherwise, it walks up parent directories starting from the app base directory and looks for:
   - `<dir>\shared\global.json`
   - `<dir>\global.json`

This allows you to keep secrets in a shared, non-git-tracked file:

- Example shared path:
  - `C:\ChatGPT\ai-bots\shared\global.json`

Code:

- `ai-bots/PainRadar/Configuration/AppConfigLoader.cs`
- `ai-bots/PainRadar/App.xaml.cs`

### Recommended `PainRadar` Section Example

Do **not** commit API keys; keep them only in the shared config.

```json
{
  "PainRadar": {
    "GooglePlacesApiKey": "YOUR_KEY_HERE",
    "EnableGoogleReviews": true,
    "MaxResultsPerSource": 100,
    "MaxCompaniesToEnrich": 25,
    "MaxEnrichmentConcurrency": 4,
    "RedditSearchLimit": 10,
    "UserAgent": "PainRadar/1.0 (contact: local)"
  }
}
```

Notes:

- If `GooglePlacesApiKey` is empty/missing, Google enrichment is automatically disabled.
- `EnableGoogleReviews` is still a UI toggle; the key must exist for calls to occur.

---

## Code Map (Where Things Live)

### Entry + Composition Root

- `ai-bots/PainRadar/App.xaml.cs`
  - Loads config
  - Creates `HttpClient`
  - Instantiates services
  - Creates `MainViewModel`
  - Shows `MainWindow`

### Models

- `ai-bots/PainRadar/Models/SignalItem.cs`
  - Row model + computed `TotalScore`
  - Holds matched keywords + source URLs
- `ai-bots/PainRadar/Models/ScanOptions.cs`
  - Feature toggles and limits for a scan
- `ai-bots/PainRadar/Models/ScanProgress.cs`
  - Stage and percent helpers
- `ai-bots/PainRadar/Models/SourceLink.cs`
  - Label + URL for detail panel links

### ViewModels

- `ai-bots/PainRadar/ViewModels/MainViewModel.cs`
  - Scan / Cancel commands
  - Filtering logic for DataGrid
  - Selected row state
  - Status + progress properties
- `ai-bots/PainRadar/ViewModels/AsyncRelayCommand.cs`
- `ai-bots/PainRadar/ViewModels/RelayCommand.cs`

### Services

- Job sources:
  - `RemotiveJobSource`
  - `RemoteOkJobSource`
  - `MuseJobSource`
- Enrichment:
  - `RedditSearchService`
  - `GooglePlacesService`
- Scoring and orchestration:
  - `PainAnalyzer`
  - `ScanOrchestrator`
- Utility:
  - `AppHttpClient`
  - `TextSanitizer`

### Views

- `ai-bots/PainRadar/MainWindow.xaml`
  - WPF layout, bindings, and dark theme styles
- `ai-bots/PainRadar/MainWindow.xaml.cs`

---

## Running and Debugging

### Run from source

From `C:\ChatGPT\ai-bots\PainRadar`:

```powershell
dotnet run
```

### Publish

```powershell
dotnet publish .\PainRadar.csproj -c Release -o .\bin\Release\net8.0-windows
```

Run the published app:

```powershell
.\bin\Release\net8.0-windows\PainRadar.exe
```

### VS Code Debug

The workspace includes a separate launch entry for PainRadar:

- `Launch PainRadar (WPF)`

It also sets:

- `PAINRADAR_CONFIG_PATH=${workspaceFolder}/ai-bots/shared/global.json`

Files:

- `C:\ChatGPT\.vscode\launch.json`
- `C:\ChatGPT\.vscode\tasks.json`

---

## Troubleshooting

### “No results”

Try:

- Turn on multiple sources (Remotive + RemoteOK + The Muse)
- Remove the minimum score filter (set slider to 0)
- Clear the search box
- Run again

### “Reddit doesn’t add anything”

Reddit enrichment depends on:

- company name quality in job feeds
- relevant posts in the last year
- public availability (rate limiting can happen)

If you see rows but RedditScore = 0, it can simply mean no posts matched the keywords.

### “GoogleReviews doesn’t add anything”

Common reasons:

- `GooglePlacesApiKey` missing/invalid
- text search didn’t find a matching place for the company name
- reviews don’t include the keyword list

### “Cancel doesn’t stop immediately”

Cancellation is cooperative:

- It will stop between awaited operations
- Some HTTP calls may take a short moment to return/cancel

---

## Limitations and Safe-Use Notes

- The app uses **public APIs** / documented endpoints and does not attempt to bypass blocked sites.
- Keyword matching is intentionally simple; it’s a “radar” to surface candidates, not a definitive truth engine.
- Google Places usage may incur billing depending on your Google Cloud setup; keep `MaxCompaniesToEnrich` conservative.


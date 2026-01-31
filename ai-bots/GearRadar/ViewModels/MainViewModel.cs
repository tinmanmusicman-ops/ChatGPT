using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.Windows.Data;
using System.Windows.Input;
using PainRadar.Configuration;
using PainRadar.Infrastructure;
using PainRadar.Models;
using PainRadar.Services;

namespace PainRadar.ViewModels;

public sealed class MainViewModel : ObservableObject
{
    private readonly AppConfig _config;
    private readonly ScanOrchestrator _orchestrator;
    private readonly CsvMatchLogService? _csvLog;
    private CancellationTokenSource? _cts;

    public MainViewModel(AppConfig config, ScanOrchestrator orchestrator, PainRadarUiSettings? uiSettings = null, CsvMatchLogService? csvLog = null)
    {
        _config = config;
        _orchestrator = orchestrator;
        _csvLog = csvLog;

        if (uiSettings is not null)
        {
            _searchTerm = uiSettings.SearchTerm ?? "";
            _minTotalScore = uiSettings.MinTotalScore;
            _enableReddit = uiSettings.EnableReddit;
            _enableCraigslist = uiSettings.EnableCraigslist;
            _requireIntentAndGearMatch = uiSettings.RequireIntentAndGearMatch;
            _uiFontSize = Math.Clamp(uiSettings.UiFontSize, 10, 28);
        }
        else
        {
            _searchTerm = "";
            _minTotalScore = 0;
            _enableReddit = true;
            _enableCraigslist = true;
            _requireIntentAndGearMatch = config.RequireIntentAndGearMatchDefault;
            _uiFontSize = 14;
        }

        ItemsView = CollectionViewSource.GetDefaultView(Items);
        ItemsView.SortDescriptions.Add(new SortDescription(nameof(GearSignalItem.TotalScore), ListSortDirection.Descending));
        ItemsView.Filter = FilterItem;

        ScanCommand = new AsyncRelayCommand(_ => ScanAsync(), _ => !IsScanning && (EnableReddit || EnableCraigslist));
        CancelCommand = new RelayCommand(_ => _cts?.Cancel(), _ => IsScanning);
        OpenUrlCommand = new RelayCommand(p => OpenUrl(p?.ToString()));
        ResetFiltersCommand = new RelayCommand(_ => ResetFilters());

        UpdateViewStats("Init");
    }

    public PainRadarUiSettings ToUiSettings() =>
        new(
            UiFontSize: UiFontSize,
            SearchTerm: SearchTerm ?? "",
            MinTotalScore: MinTotalScore,
            EnableReddit: EnableReddit,
            EnableCraigslist: EnableCraigslist,
            RequireIntentAndGearMatch: RequireIntentAndGearMatch
        );

    public ObservableCollection<GearSignalItem> Items { get; } = new();
    public ICollectionView ItemsView { get; }

    private GearSignalItem? _selectedItem;
    public GearSignalItem? SelectedItem
    {
        get => _selectedItem;
        set => SetProperty(ref _selectedItem, value);
    }

    private string _searchTerm = "";
    public string SearchTerm
    {
        get => _searchTerm;
        set
        {
            if (SetProperty(ref _searchTerm, value))
                RefreshViewAndStats("SearchTerm changed");
        }
    }

    private double _minTotalScore;
    public double MinTotalScore
    {
        get => _minTotalScore;
        set
        {
            if (SetProperty(ref _minTotalScore, value))
                RefreshViewAndStats("MinTotalScore changed");
        }
    }

    private bool _enableReddit;
    public bool EnableReddit
    {
        get => _enableReddit;
        set
        {
            if (SetProperty(ref _enableReddit, value))
                CommandManager.InvalidateRequerySuggested();
        }
    }

    private bool _enableCraigslist;
    public bool EnableCraigslist
    {
        get => _enableCraigslist;
        set
        {
            if (SetProperty(ref _enableCraigslist, value))
                CommandManager.InvalidateRequerySuggested();
        }
    }

    private bool _requireIntentAndGearMatch;
    public bool RequireIntentAndGearMatch
    {
        get => _requireIntentAndGearMatch;
        set => SetProperty(ref _requireIntentAndGearMatch, value);
    }

    public string ModeLabel =>
        RequireIntentAndGearMatch
            ? "Mode: Require intent + gear match"
            : "Mode: Show all scraped posts";

    private bool _isScanning;
    public bool IsScanning
    {
        get => _isScanning;
        private set
        {
            if (SetProperty(ref _isScanning, value))
            {
                CommandManager.InvalidateRequerySuggested();
            }
        }
    }

    private string _statusText = "Ready";
    public string StatusText
    {
        get => _statusText;
        private set => SetProperty(ref _statusText, value);
    }

    private double _uiFontSize;
    public double UiFontSize
    {
        get => _uiFontSize;
        set
        {
            var v = Math.Clamp(value, 10, 28);
            if (SetProperty(ref _uiFontSize, v))
            {
                OnPropertyChanged(nameof(UiFontSizeSm));
                OnPropertyChanged(nameof(UiFontSizeLg));
                OnPropertyChanged(nameof(UiFontSizeXl));
            }
        }
    }

    public double UiFontSizeSm => Math.Max(10, UiFontSize - 2);
    public double UiFontSizeLg => UiFontSize + 2;
    public double UiFontSizeXl => UiFontSize + 6;

    private double _progressPercent;
    public double ProgressPercent
    {
        get => _progressPercent;
        private set => SetProperty(ref _progressPercent, value);
    }

    public ICommand ScanCommand { get; }
    public ICommand CancelCommand { get; }
    public ICommand OpenUrlCommand { get; }
    public ICommand ResetFiltersCommand { get; }

    private int _totalResults;
    public int TotalResults
    {
        get => _totalResults;
        private set => SetProperty(ref _totalResults, value);
    }

    private int _visibleResults;
    public int VisibleResults
    {
        get => _visibleResults;
        private set => SetProperty(ref _visibleResults, value);
    }

    public string FilterSummary
    {
        get
        {
            var s = (SearchTerm ?? "").Trim();
            var parts = new List<string>();
            if (!string.IsNullOrWhiteSpace(s))
                parts.Add($"Search=\"{s}\"");
            if (MinTotalScore > 0)
                parts.Add($"MinTotal={MinTotalScore:0}");
            return parts.Count == 0 ? "No filters" : string.Join(" | ", parts);
        }
    }

    private async Task ScanAsync()
    {
        if (IsScanning)
            return;

        if (!EnableReddit && !EnableCraigslist)
        {
            StatusText = "Enable at least one source (Reddit or Craigslist) before scanning.";
            AppLogger.Warn("Scan blocked: no sources enabled");
            return;
        }

        _cts?.Dispose();
        _cts = new CancellationTokenSource();

        IsScanning = true;
        StatusText = "Starting scan...";
        ProgressPercent = 0;

        AppLogger.Info($"Scan starting. SearchTerm=\"{(SearchTerm ?? "").Trim()}\" Sources=[Reddit={EnableReddit}, Craigslist={EnableCraigslist}] RequireIntentAndGear={RequireIntentAndGearMatch} Limits=[MaxResultsPerSource={_config.MaxResultsPerSource}, RedditPerSub={_config.RedditLimitPerSubreddit}, CraigslistPerSite={_config.CraigslistLimitPerSite}]");

        string lastStage = "";
        var progress = new Progress<ScanProgress>(p =>
        {
            StatusText = $"{p.Stage} ({p.Completed}/{p.Total})";
            ProgressPercent = p.Percent;
            if (!string.Equals(lastStage, p.Stage, StringComparison.Ordinal))
            {
                lastStage = p.Stage;
                AppLogger.Info($"Progress: {p.Stage} total={p.Total}");
            }
        });

        try
        {
            var options = new ScanOptions(
                SearchTerm: SearchTerm ?? "",
                EnableReddit: EnableReddit,
                EnableCraigslist: EnableCraigslist,
                RequireIntentAndGearMatch: RequireIntentAndGearMatch,
                MaxResultsPerSource: _config.MaxResultsPerSource,
                RedditLimitPerSubreddit: _config.RedditLimitPerSubreddit,
                CraigslistLimitPerSite: _config.CraigslistLimitPerSite
            );

            var results = await _orchestrator.ScanAsync(options, progress, _cts.Token);

            Items.Clear();
            foreach (var item in results)
            {
                Items.Add(item);
            }

            var matches = results.Where(i => i.MatchedIntentPhrases.Count > 0 && i.MatchedGear.Count > 0).ToArray();
            var newlyLogged = _csvLog?.AppendNewMatches(matches) ?? Array.Empty<GearSignalItem>();
            foreach (var item in newlyLogged.Where(i => i.ConfidenceScore >= _config.AlertMinConfidence).OrderByDescending(i => i.ConfidenceScore))
                WriteConsoleAlert(item);

            SelectedItem = Items.FirstOrDefault();
            RefreshViewAndStats("Scan completed");
            var loggedNote = newlyLogged.Count == 0 ? "" : $" | Logged {newlyLogged.Count} new matches to CSV";
            StatusText = $"Done: {VisibleResults}/{TotalResults} results ({FilterSummary}){loggedNote}";
            ProgressPercent = 100;
            AppLogger.Info($"Scan done. Total={TotalResults} Visible={VisibleResults} Filter=({FilterSummary}) LoggedNew={newlyLogged.Count}");
        }
        catch (OperationCanceledException)
        {
            StatusText = "Canceled";
            AppLogger.Info("Scan canceled");
        }
        catch (Exception ex)
        {
            StatusText = $"Error: {ex.Message}";
            AppLogger.Exception(ex, "ScanAsync failed");
        }
        finally
        {
            IsScanning = false;
        }
    }

    private static void WriteConsoleAlert(GearSignalItem item)
    {
        try
        {
            var gear = item.MatchedGearDisplay;
            var buyer = string.IsNullOrWhiteSpace(item.Buyer) ? "unknown" : item.Buyer;
            var when = string.IsNullOrWhiteSpace(item.PostedAtDisplay) ? "" : $" | {item.PostedAtDisplay}";
            Console.WriteLine($"[GEARRADAR] {item.Platform} | {buyer}{when} | Score={item.ConfidenceScore} | {gear} | {item.Title} | {item.Url}");
        }
        catch
        {
        }
    }

    private bool FilterItem(object obj)
    {
        if (obj is not GearSignalItem item)
            return false;

        if (item.TotalScore < MinTotalScore)
            return false;

        var s = (SearchTerm ?? "").Trim();
        if (s.Length == 0)
            return true;

        return item.Platform.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Buyer.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Title.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Body.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.MatchedGearDisplay.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.MatchedIntentPhrasesDisplay.Contains(s, StringComparison.OrdinalIgnoreCase);
    }

    private void ResetFilters()
    {
        SearchTerm = "";
        MinTotalScore = 0;
        RefreshViewAndStats("Reset filters");
        StatusText = TotalResults == 0 ? "Ready" : $"Showing {VisibleResults}/{TotalResults} ({FilterSummary})";
    }

    private void RefreshViewAndStats(string reason)
    {
        try
        {
            ItemsView.Refresh();
        }
        catch (Exception ex)
        {
            AppLogger.Exception(ex, $"ItemsView.Refresh failed ({reason})");
        }

        UpdateViewStats(reason);
    }

    private void UpdateViewStats(string reason)
    {
        try
        {
            TotalResults = Items.Count;
            VisibleResults = ItemsView.Cast<object>().Count();
            OnPropertyChanged(nameof(FilterSummary));
            CommandManager.InvalidateRequerySuggested();
        }
        catch (Exception ex)
        {
            AppLogger.Exception(ex, $"UpdateViewStats failed ({reason})");
            TotalResults = Items.Count;
            VisibleResults = Items.Count;
            OnPropertyChanged(nameof(FilterSummary));
            CommandManager.InvalidateRequerySuggested();
        }
    }

    private static void OpenUrl(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
            return;

        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true
            });
        }
        catch
        {
        }
    }
}

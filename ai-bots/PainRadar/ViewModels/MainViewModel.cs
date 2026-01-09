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
    private readonly GoogleSheetsExportService? _sheetsExport;
    private CancellationTokenSource? _cts;

    public MainViewModel(AppConfig config, ScanOrchestrator orchestrator, PainRadarUiSettings? uiSettings = null, GoogleSheetsExportService? sheetsExport = null)
    {
        _config = config;
        _orchestrator = orchestrator;
        _sheetsExport = sheetsExport;

        if (uiSettings is not null)
        {
            _searchTerm = uiSettings.SearchTerm ?? "";
            _minTotalScore = uiSettings.MinTotalScore;
            _enableRemotive = uiSettings.EnableRemotive;
            _enableRemoteOk = uiSettings.EnableRemoteOk;
            _enableMuse = uiSettings.EnableMuse;
            _enableReddit = uiSettings.EnableReddit;
            _enableGoogleReviews = uiSettings.EnableGoogleReviews;
            _includeEnterprises = uiSettings.IncludeEnterprises;
            _uiFontSize = Math.Clamp(uiSettings.UiFontSize, 10, 28);
        }
        else
        {
            _searchTerm = "";
            _minTotalScore = 0;
            _enableRemotive = true;
            _enableRemoteOk = true;
            _enableMuse = true;
            _enableReddit = true;
            _enableGoogleReviews = config.EnableGoogleReviews;
            _includeEnterprises = false;
            _uiFontSize = 14;
        }

        ItemsView = CollectionViewSource.GetDefaultView(Items);
        ItemsView.SortDescriptions.Add(new SortDescription(nameof(SignalItem.TotalScore), ListSortDirection.Descending));
        ItemsView.Filter = FilterItem;

        ScanCommand = new AsyncRelayCommand(_ => ScanAsync(), _ => !IsScanning && (EnableRemotive || EnableRemoteOk || EnableMuse));
        CancelCommand = new RelayCommand(_ => _cts?.Cancel(), _ => IsScanning || IsExporting);
        OpenUrlCommand = new RelayCommand(p => OpenUrl(p?.ToString()));
        ResetFiltersCommand = new RelayCommand(_ => ResetFilters());
        ExportToSheetsCommand = new AsyncRelayCommand(_ => ExportToSheetsAsync(), _ => CanExportSelected);
        SelectAllForExportCommand = new RelayCommand(_ => SetExportSelectionForAll(true), _ => Items.Count > 0);
        SelectNoneForExportCommand = new RelayCommand(_ => SetExportSelectionForAll(false), _ => Items.Count > 0);
        SelectVisibleForExportCommand = new RelayCommand(_ => SetExportSelectionForVisible(true), _ => VisibleResults > 0);

        UpdateViewStats("Init");
    }

    public PainRadarUiSettings ToUiSettings() =>
        new(
            UiFontSize: UiFontSize,
            IncludeEnterprises: IncludeEnterprises,
            SearchTerm: SearchTerm ?? "",
            MinTotalScore: MinTotalScore,
            EnableRemotive: EnableRemotive,
            EnableRemoteOk: EnableRemoteOk,
            EnableMuse: EnableMuse,
            EnableReddit: EnableReddit,
            EnableGoogleReviews: EnableGoogleReviews
        );

    public ObservableCollection<SignalItem> Items { get; } = new();
    public ICollectionView ItemsView { get; }

    public int SelectedForExportCount => Items.Count(i => i.IsSelectedForExport);
    public string ExportSelectionLabel => $"Export: {SelectedForExportCount} selected";
    public bool CanExportSelected => !IsScanning && !IsExporting && SelectedForExportCount > 0;
    public string ExportSelectedToolTip =>
        CanExportSelected
            ? $"Exports the checked rows to the {GoogleSheetsExportService.DefaultSheetTitle} tab (overwrites it)."
            : "Select one or more rows (Sel) to enable export.";

    private SignalItem? _selectedItem;
    public SignalItem? SelectedItem
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

    private bool _enableRemotive;
    public bool EnableRemotive
    {
        get => _enableRemotive;
        set
        {
            if (SetProperty(ref _enableRemotive, value))
                CommandManager.InvalidateRequerySuggested();
        }
    }

    private bool _enableRemoteOk;
    public bool EnableRemoteOk
    {
        get => _enableRemoteOk;
        set
        {
            if (SetProperty(ref _enableRemoteOk, value))
                CommandManager.InvalidateRequerySuggested();
        }
    }

    private bool _enableMuse;
    public bool EnableMuse
    {
        get => _enableMuse;
        set
        {
            if (SetProperty(ref _enableMuse, value))
                CommandManager.InvalidateRequerySuggested();
        }
    }

    private bool _enableReddit;
    public bool EnableReddit
    {
        get => _enableReddit;
        set => SetProperty(ref _enableReddit, value);
    }

    private bool _enableGoogleReviews;
    public bool EnableGoogleReviews
    {
        get => _enableGoogleReviews;
        set => SetProperty(ref _enableGoogleReviews, value);
    }

    private bool _includeEnterprises;
    public bool IncludeEnterprises
    {
        get => _includeEnterprises;
        set
        {
            if (SetProperty(ref _includeEnterprises, value))
                OnPropertyChanged(nameof(ModeLabel));
        }
    }

    public string ModeLabel =>
        IncludeEnterprises
            ? "Mode: All companies (SMB filter OFF)"
            : "SMB mode: 5-200 employees (enterprises excluded)";

    private bool _isScanning;
    public bool IsScanning
    {
        get => _isScanning;
        private set
        {
            if (SetProperty(ref _isScanning, value))
            {
                CommandManager.InvalidateRequerySuggested();
                OnPropertyChanged(nameof(CanExportSelected));
                OnPropertyChanged(nameof(ExportSelectedToolTip));
            }
        }
    }

    private bool _isExporting;
    public bool IsExporting
    {
        get => _isExporting;
        private set
        {
            if (SetProperty(ref _isExporting, value))
            {
                CommandManager.InvalidateRequerySuggested();
                OnPropertyChanged(nameof(CanExportSelected));
                OnPropertyChanged(nameof(ExportSelectedToolTip));
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
    public ICommand ExportToSheetsCommand { get; }
    public ICommand SelectAllForExportCommand { get; }
    public ICommand SelectNoneForExportCommand { get; }
    public ICommand SelectVisibleForExportCommand { get; }

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

        if (!EnableRemotive && !EnableRemoteOk && !EnableMuse)
        {
            StatusText = "Enable at least one job source (Remotive/RemoteOK/The Muse) before scanning.";
            AppLogger.Warn("Scan blocked: no job sources enabled");
            return;
        }

        _cts?.Dispose();
        _cts = new CancellationTokenSource();

        IsScanning = true;
        var isGoogleEnabled = EnableGoogleReviews && !string.IsNullOrWhiteSpace(_config.GooglePlacesApiKey);
        StatusText = isGoogleEnabled ? "Starting scan..." : "Starting scan... (Google disabled: missing API key)";
        ProgressPercent = 0;

        AppLogger.Info($"Scan starting. SearchTerm=\"{(SearchTerm ?? "").Trim()}\" Sources=[Remotive={EnableRemotive}, RemoteOK={EnableRemoteOk}, TheMuse={EnableMuse}] Enrich=[Reddit={EnableReddit}, Google={EnableGoogleReviews}] Limits=[PerSource={_config.MaxResultsPerSource}, EnrichCompanies={_config.MaxCompaniesToEnrich}]");

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
                EnableRemotive: EnableRemotive,
                EnableRemoteOk: EnableRemoteOk,
                EnableMuse: EnableMuse,
                EnableReddit: EnableReddit,
                EnableGoogleReviews: EnableGoogleReviews,
                IncludeEnterprises: IncludeEnterprises,
                MaxResultsPerSource: _config.MaxResultsPerSource,
                MaxCompaniesToEnrich: _config.MaxCompaniesToEnrich,
                MaxEnrichmentConcurrency: _config.MaxEnrichmentConcurrency,
                RedditSearchLimit: _config.RedditSearchLimit
            );

            var results = await _orchestrator.ScanAsync(options, progress, _cts.Token);

            foreach (var old in Items)
                old.PropertyChanged -= OnItemPropertyChanged;
            Items.Clear();
            foreach (var item in results)
            {
                item.PropertyChanged += OnItemPropertyChanged;
                Items.Add(item);
            }
            OnPropertyChanged(nameof(SelectedForExportCount));
            OnPropertyChanged(nameof(ExportSelectionLabel));
            OnPropertyChanged(nameof(CanExportSelected));
            OnPropertyChanged(nameof(ExportSelectedToolTip));

            SelectedItem = Items.FirstOrDefault();
            RefreshViewAndStats("Scan completed");
            StatusText = $"Done: {VisibleResults}/{TotalResults} signals ({FilterSummary})";
            ProgressPercent = 100;
            AppLogger.Info($"Scan done. Total={TotalResults} Visible={VisibleResults} Filter=({FilterSummary})");
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

    private async Task ExportToSheetsAsync()
    {
        if (IsScanning || IsExporting)
            return;

        if (_sheetsExport is null)
        {
            StatusText = "Sheets export is unavailable in this build.";
            AppLogger.Warn("Sheets export requested but service was not provided.");
            return;
        }

        var rows = Items.Where(i => i.IsSelectedForExport).ToList();
        if (rows.Count == 0)
        {
            StatusText = "No rows selected. Check the rows you want, then export.";
            return;
        }

        if (!_sheetsExport.IsConfigured)
        {
            StatusText = "Sheets export isn't configured. Add spreadsheet_id + service account fields to shared global.json.";
            AppLogger.Warn("Sheets export blocked: not configured.");
            return;
        }

        _cts?.Dispose();
        _cts = new CancellationTokenSource();

        IsExporting = true;
        ProgressPercent = 0;
        StatusText = $"Exporting {rows.Count} rows to Sheets...";

        var title = GoogleSheetsExportService.DefaultSheetTitle;

        try
        {
            var (_, sheetTitle) = await _sheetsExport.ExportToFixedSheetAsync(title, rows, _cts.Token);
            StatusText = $"Exported {rows.Count} rows to Sheets tab (overwritten): {sheetTitle}";
            ProgressPercent = 100;
            AppLogger.Info($"Sheets export done. rows={rows.Count} sheetTitle=\"{sheetTitle}\"");
        }
        catch (OperationCanceledException)
        {
            StatusText = "Export canceled";
            AppLogger.Info("Sheets export canceled");
        }
        catch (Exception ex)
        {
            StatusText = $"Export error: {ex.Message}";
            AppLogger.Exception(ex, "Sheets export failed");
        }
        finally
        {
            IsExporting = false;
        }
    }

    private void OnItemPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SignalItem.IsSelectedForExport))
        {
            CommandManager.InvalidateRequerySuggested();
            OnPropertyChanged(nameof(SelectedForExportCount));
            OnPropertyChanged(nameof(ExportSelectionLabel));
            OnPropertyChanged(nameof(CanExportSelected));
            OnPropertyChanged(nameof(ExportSelectedToolTip));
        }
    }

    private void SetExportSelectionForAll(bool isSelected)
    {
        foreach (var item in Items)
            item.IsSelectedForExport = isSelected;

        CommandManager.InvalidateRequerySuggested();
        OnPropertyChanged(nameof(SelectedForExportCount));
        OnPropertyChanged(nameof(ExportSelectionLabel));
        OnPropertyChanged(nameof(CanExportSelected));
        OnPropertyChanged(nameof(ExportSelectedToolTip));
    }

    private void SetExportSelectionForVisible(bool isSelected)
    {
        foreach (var item in ItemsView.Cast<object>().OfType<SignalItem>())
            item.IsSelectedForExport = isSelected;

        CommandManager.InvalidateRequerySuggested();
        OnPropertyChanged(nameof(SelectedForExportCount));
        OnPropertyChanged(nameof(ExportSelectionLabel));
        OnPropertyChanged(nameof(CanExportSelected));
        OnPropertyChanged(nameof(ExportSelectedToolTip));
    }

    private bool FilterItem(object obj)
    {
        if (obj is not SignalItem item)
            return false;

        if (item.TotalScore < MinTotalScore)
            return false;

        var s = (SearchTerm ?? "").Trim();
        if (s.Length == 0)
            return true;

        return item.Company.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.JobTitle.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Location.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Source.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.Description.Contains(s, StringComparison.OrdinalIgnoreCase)
            || item.MatchedKeywordsDisplay.Contains(s, StringComparison.OrdinalIgnoreCase);
    }

    private void ResetFilters()
    {
        SearchTerm = "";
        MinTotalScore = 0;
        RefreshViewAndStats("Reset filters");
        StatusText = TotalResults == 0 ? "Ready" : $"Showing {VisibleResults}/{TotalResults} ({FilterSummary})";
        OnPropertyChanged(nameof(SelectedForExportCount));
        OnPropertyChanged(nameof(ExportSelectionLabel));
        OnPropertyChanged(nameof(CanExportSelected));
        OnPropertyChanged(nameof(ExportSelectedToolTip));
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

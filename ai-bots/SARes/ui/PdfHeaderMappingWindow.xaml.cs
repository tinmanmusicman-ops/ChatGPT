using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Windows;
using System.Windows.Input;
using SARes.engine;

namespace SARes.ui;

public partial class PdfHeaderMappingWindow : Window
{
    private readonly ObservableCollection<HeaderRule> _customHeaders;
    private readonly Dictionary<string, IReadOnlyList<string>> _presetMap;
    private readonly Dictionary<string, IReadOnlyList<string>> _bulletizePresetMap;
    private readonly ObservableCollection<string> _presetNames;
    private readonly Action<string, IReadOnlyList<string>, IReadOnlyList<string>> _savePreset;
    private bool _suppressPresetSelection;

    public PdfHeaderMappingWindow(
        AppSettings settings,
        IEnumerable<string> initialHeaders,
        Action<string, IReadOnlyList<string>, IReadOnlyList<string>> savePreset,
        string confirmButtonText = "Run Import")
    {
        InitializeComponent();
        RunImportButton.Content = confirmButtonText;

        _presetMap = settings.PdfHeaderPresets.ToDictionary(
            kv => kv.Key,
            kv => (IReadOnlyList<string>)kv.Value.ToArray(),
            StringComparer.OrdinalIgnoreCase);

        _bulletizePresetMap = settings.PdfBulletizePresets.ToDictionary(
            kv => kv.Key,
            kv => (IReadOnlyList<string>)kv.Value.ToArray(),
            StringComparer.OrdinalIgnoreCase);

        _presetNames = new ObservableCollection<string>(_presetMap.Keys.Count > 0
            ? _presetMap.Keys
            : ResumeParserDefaults.HeaderPresets.Keys);

        PresetComboBox.ItemsSource = _presetNames;
        PresetComboBox.SelectionChanged += (_, _) =>
        {
            if (_suppressPresetSelection)
                return;
            if (PresetComboBox.SelectedItem is string preset)
                LoadPreset(preset);
        };

        _savePreset = savePreset;

        LayoutComboBox.ItemsSource = new[]
        {
            new LayoutChoice("Single column (top-to-bottom)", PdfLayoutMode.SingleColumn),
            new LayoutChoice("2 columns (left then right)", PdfLayoutMode.TwoColumnsLeftToRight),
            new LayoutChoice("2 columns (right then left)", PdfLayoutMode.TwoColumnsRightToLeft),
        };
        LayoutComboBox.DisplayMemberPath = nameof(LayoutChoice.Label);
        LayoutComboBox.SelectedValuePath = nameof(LayoutChoice.Mode);
        LayoutComboBox.SelectedValue = settings.SelectedPdfLayoutMode;

        // Always start from the selected/default preset headers.
        // (User can edit/reorder and optionally save as a named preset.)
        var cleanedInitial = (initialHeaders ?? Enumerable.Empty<string>())
            .Select(h => (h ?? "").Trim())
            .Where(h => h.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var list = new List<string>(cleanedInitial);

        var bulletize = settings.GetPdfBulletizePreset(settings.SelectedPdfHeaderPresetName);
        _customHeaders = new ObservableCollection<HeaderRule>(list.Select(t => new HeaderRule(t, bulletize.Any(b => b.Equals(t, StringComparison.OrdinalIgnoreCase)))));
        CustomHeadersListBox.ItemsSource = _customHeaders;

        var targetPreset = settings.SelectedPdfHeaderPresetName ?? _presetNames.FirstOrDefault();
        if (targetPreset is not null)
        {
            _suppressPresetSelection = true;
            PresetComboBox.SelectedItem = targetPreset;
            _suppressPresetSelection = false;
        }

        AddHeaderButton.Click += (_, _) => AddHeader();
        EditHeaderButton.Click += (_, _) => EditSelectedHeader();
        RemoveHeaderButton.Click += (_, _) => RemoveSelectedHeader();
        MoveUpButton.Click += (_, _) => MoveSelectedHeader(-1);
        MoveDownButton.Click += (_, _) => MoveSelectedHeader(1);
        ResetButton.Click += (_, _) => ResetHeaders();
        SavePresetButton.Click += (_, _) => SaveCurrentPreset();
        RunImportButton.Click += (_, _) => { DialogResult = true; };

        NewHeaderTextBox.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter)
            {
                AddHeader();
                e.Handled = true;
            }
        };

        CustomHeadersListBox.SelectionChanged += (_, _) => SyncSelectedHeader();
    }

    public IReadOnlyList<string> ConfirmedHeaders => _customHeaders.Select(h => h.Title).ToList();
    public IReadOnlyList<string> BulletizedSectionTitles => _customHeaders.Where(h => h.ForceBullets).Select(h => h.Title).ToList();
    public string? SelectedPresetName => PresetComboBox.SelectedItem as string;
    public PdfLayoutMode SelectedLayoutMode => (LayoutComboBox.SelectedItem as LayoutChoice)?.Mode ?? PdfLayoutMode.SingleColumn;

    private void LoadPreset(string preset)
    {
        if (!_presetMap.TryGetValue(preset, out var headers))
            return;

        _customHeaders.Clear();
        var bulletize = _bulletizePresetMap.TryGetValue(preset, out var b) ? b : Array.Empty<string>();
        foreach (var header in headers)
            _customHeaders.Add(new HeaderRule(header, bulletize.Any(x => x.Equals(header, StringComparison.OrdinalIgnoreCase))));
        PresetNameTextBox.Text = preset;
    }

    private void AddHeader()
    {
        var text = (NewHeaderTextBox.Text ?? "").Trim();
        if (text.Length == 0)
            return;

        if (_customHeaders.Any(h => string.Equals(h.Title, text, StringComparison.OrdinalIgnoreCase)))
            return;

        var rule = new HeaderRule(text, ForceBulletsCheckBox.IsChecked == true);
        _customHeaders.Add(rule);
        NewHeaderTextBox.Clear();
        ForceBulletsCheckBox.IsChecked = false;
        CustomHeadersListBox.ScrollIntoView(rule);
    }

    private void EditSelectedHeader()
    {
        if (CustomHeadersListBox.SelectedItem is not HeaderRule header)
            return;

        var text = (NewHeaderTextBox.Text ?? "").Trim();
        if (text.Length == 0)
            return;

        var index = _customHeaders.IndexOf(header);
        if (index < 0)
            return;

        _customHeaders[index] = new HeaderRule(text, ForceBulletsCheckBox.IsChecked == true);
        CustomHeadersListBox.SelectedItem = _customHeaders[index];
        NewHeaderTextBox.Clear();
        ForceBulletsCheckBox.IsChecked = false;
    }

    private void RemoveSelectedHeader()
    {
        if (CustomHeadersListBox.SelectedItem is not HeaderRule header)
            return;

        _customHeaders.Remove(header);
    }

    private void MoveSelectedHeader(int direction)
    {
        if (CustomHeadersListBox.SelectedItem is not HeaderRule header)
            return;

        var index = _customHeaders.IndexOf(header);
        if (index < 0)
            return;

        var target = index + direction;
        if (target < 0 || target >= _customHeaders.Count)
            return;

        _customHeaders.Move(index, target);
        CustomHeadersListBox.SelectedIndex = target;
    }

    private void ResetHeaders()
    {
        var preset = PresetComboBox.SelectedItem as string ?? _presetNames.FirstOrDefault();
        if (preset is not null)
        {
            LoadPreset(preset);
            return;
        }

        _customHeaders.Clear();
        foreach (var header in ResumeParserDefaults.SectionTitles)
            _customHeaders.Add(new HeaderRule(header, false));
    }

    private void SelectPreset(string presetName, bool loadHeaders)
    {
        if (string.IsNullOrWhiteSpace(presetName))
            return;

        var actualPreset = _presetNames.FirstOrDefault(name => string.Equals(name, presetName, StringComparison.OrdinalIgnoreCase));
        if (actualPreset is null)
            return;

        _suppressPresetSelection = true;
        PresetComboBox.SelectedItem = actualPreset;
        _suppressPresetSelection = false;

        if (loadHeaders)
            LoadPreset(actualPreset);
        else
            PresetNameTextBox.Text = actualPreset;
    }

    private void SyncSelectedHeader()
    {
        if (CustomHeadersListBox.SelectedItem is HeaderRule header)
        {
            NewHeaderTextBox.Text = header.Title;
            ForceBulletsCheckBox.IsChecked = header.ForceBullets;
        }
    }

    private void SaveCurrentPreset()
    {
        var presetName = (PresetNameTextBox.Text ?? "").Trim();
        if (presetName.Length == 0)
        {
            System.Windows.MessageBox.Show("Preset name is required to save.", "Save preset", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        var headers = ConfirmedHeaders;
        var bulletize = BulletizedSectionTitles;
        _savePreset(presetName, headers, bulletize);

        if (!_presetMap.ContainsKey(presetName))
        {
            _presetMap[presetName] = headers;
            _presetNames.Add(presetName);
        }
        else
        {
            _presetMap[presetName] = headers;
        }

        _bulletizePresetMap[presetName] = bulletize;
        PresetComboBox.SelectedItem = presetName;
        System.Windows.MessageBox.Show("Preset saved.", "Save preset", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private sealed record LayoutChoice(string Label, PdfLayoutMode Mode);

    private sealed class HeaderRule(string title, bool forceBullets) : INotifyPropertyChanged
    {
        private string _title = title;
        private bool _forceBullets = forceBullets;

        public string Title
        {
            get => _title;
            set
            {
                if (string.Equals(_title, value, StringComparison.Ordinal))
                    return;
                _title = value;
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(Title)));
            }
        }

        public bool ForceBullets
        {
            get => _forceBullets;
            set
            {
                if (_forceBullets == value)
                    return;
                _forceBullets = value;
                PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(nameof(ForceBullets)));
            }
        }

        public event PropertyChangedEventHandler? PropertyChanged;
    }
}

using System.Windows;
using SARes.engine;

namespace SARes.ui;

public partial class EditSummaryPresetWindow : Window
{
    private AppSettings _updated;
    private readonly string _presetName;

    public EditSummaryPresetWindow(AppSettings settings, string presetName)
    {
        InitializeComponent();
        _updated = settings;
        _presetName = (presetName ?? "").Trim();

        PresetNameText.Text = $"Summary version: {_presetName}";
        SummaryTextBox.Text = _updated.GetPresetSummary(_presetName);

        SaveButton.Click += (_, _) => Save();
        CloseButton.Click += (_, _) => Close();

        StatusText.Text = "Ready";
    }

    public AppSettings UpdatedSettings => _updated;

    private void Save()
    {
        try
        {
            var text = (SummaryTextBox.Text ?? "").Trim();
            if (text.Length == 0)
            {
                System.Windows.MessageBox.Show("Summary is required.", "SARes", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            _updated = _updated.UpsertPreset(_presetName, text);
            _updated = _updated with { SelectedPresetName = _presetName };
            AppSettingsStore.Save(_updated);
            StatusText.Text = "Saved.";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Save failed: " + ex.Message;
        }
    }
}


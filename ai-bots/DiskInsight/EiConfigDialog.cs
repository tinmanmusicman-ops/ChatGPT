using System;
using System.Drawing;
using System.Windows.Forms;

namespace DiskInsight;

internal sealed class EiConfigDialog : Form
{
    private readonly TextBox _endpoint;
    private readonly TextBox _apiKey;

    public string Endpoint => _endpoint.Text.Trim();
    public string ApiKey => _apiKey.Text.Trim();

    public EiConfigDialog(string? initialEndpoint, string? initialApiKey)
    {
        Text = "Configure EI";
        StartPosition = FormStartPosition.CenterParent;
        Width = 700;
        Height = 240;
        MinimizeBox = false;
        MaximizeBox = false;
        FormBorderStyle = FormBorderStyle.FixedDialog;

        var label1 = new Label { Text = "EI Endpoint (URL)", AutoSize = true, Left = 12, Top = 16 };
        _endpoint = new TextBox { Left = 12, Top = 38, Width = 650, Text = initialEndpoint ?? string.Empty };

        var label2 = new Label { Text = "EI API Key (not saved)", AutoSize = true, Left = 12, Top = 74 };
        _apiKey = new TextBox { Left = 12, Top = 96, Width = 650, UseSystemPasswordChar = true, Text = initialApiKey ?? string.Empty };

        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, Width = 100, Height = 28 };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, Width = 100, Height = 28 };

        ok.Left = Width - ok.Width - cancel.Width - 40;
        ok.Top = 140;
        cancel.Left = Width - cancel.Width - 28;
        cancel.Top = 140;

        AcceptButton = ok;
        CancelButton = cancel;

        Controls.Add(label1);
        Controls.Add(_endpoint);
        Controls.Add(label2);
        Controls.Add(_apiKey);
        Controls.Add(ok);
        Controls.Add(cancel);

        Font = new Font(Font.FontFamily, 9f);
    }
}


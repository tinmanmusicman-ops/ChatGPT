using System.IO;
using System.Text.Json;
using Google.Apis.Auth.OAuth2;
using Google.Apis.Services;
using Google.Apis.Sheets.v4;
using Google.Apis.Sheets.v4.Data;
using PainRadar.Infrastructure;
using PainRadar.Models;

namespace PainRadar.Services;

public sealed class GoogleSheetsExportService
{
    private readonly string? _configPath;

    public GoogleSheetsExportService(string? configPath)
    {
        _configPath = configPath;
    }

    public const string DefaultSheetTitle = "PainRadar";

    public bool IsConfigured
    {
        get
        {
            try
            {
                _ = LoadGoogleSheetsCredentialJsonAndSpreadsheetId();
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    public async Task<(string SpreadsheetId, string SheetTitle)> ExportToFixedSheetAsync(
        string? sheetTitle,
        IReadOnlyList<SignalItem> rows,
        CancellationToken cancellationToken)
    {
        var (credentialJson, spreadsheetId) = LoadGoogleSheetsCredentialJsonAndSpreadsheetId();

        var serviceAccount = CredentialFactory.FromJson<ServiceAccountCredential>(credentialJson);
        var credential = serviceAccount.ToGoogleCredential().CreateScoped(SheetsService.Scope.Spreadsheets);
        var service = new SheetsService(new BaseClientService.Initializer
        {
            HttpClientInitializer = credential,
            ApplicationName = "PainRadar"
        });

        var resolvedTitle = SanitizeSheetTitle(string.IsNullOrWhiteSpace(sheetTitle) ? DefaultSheetTitle : sheetTitle);
        var sheetId = await EnsureSheetAsync(service, spreadsheetId, resolvedTitle, cancellationToken);

        var values = BuildValues(rows);
        var endCol = ColumnName(Math.Max(1, values[0].Count));
        var clearRange = $"'{EscapeA1(resolvedTitle)}'!A:{endCol}";
        try
        {
            await service.Spreadsheets.Values.Clear(new ClearValuesRequest(), spreadsheetId, clearRange).ExecuteAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            AppLogger.Exception(ex, "Sheets export: clear failed (continuing)");
        }

        var range = $"'{EscapeA1(resolvedTitle)}'!A1";
        var vr = new ValueRange { Values = values };

        var update = service.Spreadsheets.Values.Update(vr, spreadsheetId, range);
        update.ValueInputOption = SpreadsheetsResource.ValuesResource.UpdateRequest.ValueInputOptionEnum.RAW;
        var updateResp = await update.ExecuteAsync(cancellationToken);

        AppLogger.Info($"Sheets export: wrote sheet=\"{resolvedTitle}\" updatedCells={updateResp.UpdatedCells} updatedRows={updateResp.UpdatedRows}");

        // Formatting (force dark theme so data is readable regardless of the user's Google Sheets theme)
        try
        {
            var bg = new Color { Red = 0f, Green = 0f, Blue = 0f, Alpha = 1f };
            var fg = new Color { Red = 1f, Green = 1f, Blue = 1f, Alpha = 1f };
            var headerBg = new Color { Red = 0.07f, Green = 0.09f, Blue = 0.14f, Alpha = 1f };

            var fmt = new BatchUpdateSpreadsheetRequest
            {
                Requests = new List<Request>
                {
                    new()
                    {
                        UpdateSheetProperties = new UpdateSheetPropertiesRequest
                        {
                            Properties = new SheetProperties
                            {
                                SheetId = sheetId,
                                GridProperties = new GridProperties { FrozenRowCount = 1 }
                            },
                            Fields = "gridProperties.frozenRowCount"
                        }
                    },
                    new()
                    {
                        RepeatCell = new RepeatCellRequest
                        {
                            Range = new GridRange { SheetId = sheetId },
                            Cell = new CellData
                            {
                                UserEnteredFormat = new CellFormat
                                {
                                    BackgroundColor = bg,
                                    TextFormat = new TextFormat { ForegroundColor = fg },
                                    WrapStrategy = "WRAP"
                                }
                            },
                            Fields = "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.foregroundColor,userEnteredFormat.wrapStrategy"
                        }
                    },
                    new()
                    {
                        RepeatCell = new RepeatCellRequest
                        {
                            Range = new GridRange
                            {
                                SheetId = sheetId,
                                StartRowIndex = 0,
                                EndRowIndex = 1
                            },
                            Cell = new CellData
                            {
                                UserEnteredFormat = new CellFormat
                                {
                                    BackgroundColor = headerBg,
                                    TextFormat = new TextFormat { Bold = true, ForegroundColor = fg }
                                }
                            },
                            Fields = "userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold,userEnteredFormat.textFormat.foregroundColor"
                        }
                    },
                    new()
                    {
                        AutoResizeDimensions = new AutoResizeDimensionsRequest
                        {
                            Dimensions = new DimensionRange
                            {
                                SheetId = sheetId,
                                Dimension = "COLUMNS",
                                StartIndex = 0,
                                EndIndex = values.Count > 0 ? values[0].Count : 10
                            }
                        }
                    }
                }
            };
            await service.Spreadsheets.BatchUpdate(fmt, spreadsheetId).ExecuteAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            AppLogger.Exception(ex, "Sheets export: formatting failed");
        }

        return (spreadsheetId, resolvedTitle);
    }

    private static async Task<int> EnsureSheetAsync(
        SheetsService service,
        string spreadsheetId,
        string sheetTitle,
        CancellationToken cancellationToken)
    {
        var ss = await service.Spreadsheets.Get(spreadsheetId).ExecuteAsync(cancellationToken);
        var existing = ss.Sheets?.FirstOrDefault(s =>
            string.Equals(s.Properties?.Title, sheetTitle, StringComparison.OrdinalIgnoreCase));
        if (existing?.Properties?.SheetId is int id)
            return id;

        AppLogger.Info($"Sheets export: creating fixed sheet title=\"{sheetTitle}\"");
        var addSheetRequest = new BatchUpdateSpreadsheetRequest
        {
            Requests = new List<Request>
            {
                new()
                {
                    AddSheet = new AddSheetRequest
                    {
                        Properties = new SheetProperties
                        {
                            Title = sheetTitle,
                            GridProperties = new GridProperties { FrozenRowCount = 1 }
                        }
                    }
                }
            }
        };
        var batch = service.Spreadsheets.BatchUpdate(addSheetRequest, spreadsheetId);
        var batchResp = await batch.ExecuteAsync(cancellationToken);
        var addedSheetId = batchResp.Replies?.FirstOrDefault()?.AddSheet?.Properties?.SheetId;
        if (addedSheetId is null)
            throw new InvalidOperationException("Sheets export: AddSheet did not return a SheetId.");
        return addedSheetId.Value;
    }

    private (string CredentialJson, string SpreadsheetId) LoadGoogleSheetsCredentialJsonAndSpreadsheetId()
    {
        var envCredJson = Environment.GetEnvironmentVariable("PAINRADAR_SHEETS_CREDENTIAL_JSON");
        var envSpreadsheetId = Environment.GetEnvironmentVariable("PAINRADAR_SHEETS_SPREADSHEET_ID");
        if (!string.IsNullOrWhiteSpace(envSpreadsheetId) && !string.IsNullOrWhiteSpace(envCredJson))
        {
            var sid = envSpreadsheetId.Trim();
            return (envCredJson.Trim(), sid);
        }

        if (string.IsNullOrWhiteSpace(_configPath) || !File.Exists(_configPath))
            throw new InvalidOperationException("Sheets export is not configured (missing config path).");

        using var stream = File.OpenRead(_configPath);
        using var doc = JsonDocument.Parse(stream);
        var root = doc.RootElement;

        var spreadsheetId = !string.IsNullOrWhiteSpace(envSpreadsheetId)
            ? envSpreadsheetId.Trim()
            : GetSpreadsheetId(root);
        if (string.IsNullOrWhiteSpace(spreadsheetId))
            throw new InvalidOperationException("Missing spreadsheet_id in shared global.json.");

        var serviceAccountJson2 = !string.IsNullOrWhiteSpace(envCredJson)
            ? envCredJson.Trim()
            : GetServiceAccountJson(root);
        return (serviceAccountJson2, spreadsheetId);
    }

    private static string GetSpreadsheetId(JsonElement root)
    {
        if (TryGetStringIgnoreCase(root, out var s, "spreadsheet_id", "spreadsheetId", "SpreadsheetId") && !string.IsNullOrWhiteSpace(s))
            return s;

        if (TryGetObjectIgnoreCase(root, "PainRadar", out var pr))
        {
            if (TryGetStringIgnoreCase(pr, out s, "SheetsSpreadsheetId", "GoogleSheetsSpreadsheetId", "spreadsheet_id", "spreadsheetId", "SpreadsheetId") && !string.IsNullOrWhiteSpace(s))
                return s;

            if (TryGetObjectIgnoreCase(pr, "GoogleSheets", out var gs) || TryGetObjectIgnoreCase(pr, "Sheets", out gs))
            {
                if (TryGetStringIgnoreCase(gs, out s, "spreadsheet_id", "spreadsheetId", "SpreadsheetId") && !string.IsNullOrWhiteSpace(s))
                    return s;
            }
        }

        return "";
    }

    private static string GetServiceAccountJson(JsonElement root)
    {
        if (TryGetStringIgnoreCase(root, out var json, "service_account_json", "serviceAccountJson", "ServiceAccountJson") && !string.IsNullOrWhiteSpace(json))
            return json;

        if (TryGetObjectIgnoreCase(root, "service_account", out var sa) || TryGetObjectIgnoreCase(root, "serviceAccount", out sa) || TryGetObjectIgnoreCase(root, "ServiceAccount", out sa))
            return SerializeServiceAccount(sa);

        if (LooksLikeServiceAccount(root))
            return SerializeServiceAccount(root);

        if (TryGetObjectIgnoreCase(root, "PainRadar", out var pr))
        {
            if (TryGetStringIgnoreCase(pr, out json, "ServiceAccountJson", "service_account_json") && !string.IsNullOrWhiteSpace(json))
                return json;

            if (TryGetObjectIgnoreCase(pr, "GoogleSheets", out var gs) || TryGetObjectIgnoreCase(pr, "Sheets", out gs))
            {
                if (TryGetStringIgnoreCase(gs, out json, "ServiceAccountJson", "service_account_json", "serviceAccountJson") && !string.IsNullOrWhiteSpace(json))
                    return json;

                if (TryGetObjectIgnoreCase(gs, "ServiceAccount", out var gsa) || TryGetObjectIgnoreCase(gs, "service_account", out gsa) || TryGetObjectIgnoreCase(gs, "serviceAccount", out gsa))
                    return SerializeServiceAccount(gsa);
            }
        }

        throw new InvalidOperationException("Missing service account credentials for Sheets export.");
    }

    private static bool LooksLikeServiceAccount(JsonElement obj)
        => obj.ValueKind == JsonValueKind.Object
           && TryGetStringIgnoreCase(obj, out var type, "type") && type == "service_account"
           && TryGetStringIgnoreCase(obj, out var email, "client_email") && !string.IsNullOrWhiteSpace(email)
           && TryGetStringIgnoreCase(obj, out var pk, "private_key") && !string.IsNullOrWhiteSpace(pk);

    private static string SerializeServiceAccount(JsonElement obj)
    {
        string GetString(string name)
            => TryGetStringIgnoreCase(obj, out var v, name) ? v : "";

        var payload = new Dictionary<string, string?>
        {
            ["type"] = GetString("type"),
            ["project_id"] = GetString("project_id"),
            ["private_key_id"] = GetString("private_key_id"),
            ["private_key"] = GetString("private_key"),
            ["client_email"] = GetString("client_email"),
            ["client_id"] = GetString("client_id"),
            ["auth_uri"] = GetString("auth_uri"),
            ["token_uri"] = GetString("token_uri"),
            ["auth_provider_x509_cert_url"] = GetString("auth_provider_x509_cert_url"),
            ["client_x509_cert_url"] = GetString("client_x509_cert_url"),
            ["universe_domain"] = GetString("universe_domain")
        };

        if (string.IsNullOrWhiteSpace(payload["private_key"]) || string.IsNullOrWhiteSpace(payload["client_email"]))
            throw new InvalidOperationException("Missing service account private_key/client_email for Sheets export.");

        return JsonSerializer.Serialize(payload);
    }

    private static bool TryGetObjectIgnoreCase(JsonElement obj, string name, out JsonElement value)
    {
        if (TryGetPropertyIgnoreCase(obj, name, out value) && value.ValueKind == JsonValueKind.Object)
            return true;

        value = default;
        return false;
    }

    private static bool TryGetStringIgnoreCase(JsonElement obj, out string value, params string[] names)
    {
        foreach (var n in names)
        {
            if (TryGetPropertyIgnoreCase(obj, n, out var el) && el.ValueKind == JsonValueKind.String)
            {
                value = el.GetString() ?? "";
                return true;
            }
        }

        value = "";
        return false;
    }

    private static bool TryGetPropertyIgnoreCase(JsonElement obj, string name, out JsonElement value)
    {
        if (obj.ValueKind == JsonValueKind.Object)
        {
            foreach (var p in obj.EnumerateObject())
            {
                if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    value = p.Value;
                    return true;
                }
            }
        }

        value = default;
        return false;
    }

    private static List<IList<object>> BuildValues(IReadOnlyList<SignalItem> rows)
    {
        var values = new List<IList<object>>(rows.Count + 1)
        {
            new List<object>
            {
                "TotalScore","Company","JobTitle","JobUrl","Location","Source",
                "PainScore","GrowthScore","FixableScore","SmbFitScore","RedditScore","GoogleScore",
                "MatchedKeywords","Description"
            }
        };

        foreach (var r in rows)
        {
            values.Add(new List<object>
            {
                r.TotalScore,
                r.Company,
                r.JobTitle,
                r.JobUrl,
                r.Location,
                r.Source,
                r.PainScore,
                r.GrowthScore,
                r.FixableScore,
                r.SmbFitScore,
                r.RedditScore,
                r.GoogleScore,
                r.MatchedKeywordsDisplay,
                r.Description
            });
        }

        return values;
    }

    private static string SanitizeSheetTitle(string title)
    {
        var t = (title ?? "").Trim();
        if (t.Length == 0)
            t = "PainRadar Export";

        // Google Sheets title limits
        t = t.Replace("/", "-").Replace("\\", "-").Replace(":", "-").Replace("?", "").Replace("*", "").Replace("[", "(").Replace("]", ")");
        if (t.Length > 90)
            t = t.Substring(0, 90).Trim();
        return t;
    }

    private static string EscapeA1(string sheetTitle) => sheetTitle.Replace("'", "''");

    private static string ColumnName(int oneBasedIndex)
    {
        if (oneBasedIndex <= 0)
            return "A";

        var index = oneBasedIndex;
        var chars = new List<char>(4);
        while (index > 0)
        {
            index--;
            chars.Add((char)('A' + (index % 26)));
            index /= 26;
        }
        chars.Reverse();
        return new string(chars.ToArray());
    }
}

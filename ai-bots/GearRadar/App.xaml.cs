using System.Diagnostics;
using System.IO;
using System.Windows;
using PainRadar.Configuration;
using PainRadar.Infrastructure;
using PainRadar.Services;
using PainRadar.Services.Sources;
using PainRadar.ViewModels;

namespace PainRadar;

public partial class App : Application
{
    private bool _shownOnboarding;
    private int _showingFatal;

    protected override void OnStartup(StartupEventArgs e)
    {
        ConsoleAttach.TryAttachToParent();
        AppLogger.Initialize(Path.Combine(AppContext.BaseDirectory, "gearradar.log"));
        HookGlobalExceptionLogging();
        AppLogger.Info($"App starting. CWD={Environment.CurrentDirectory}. BaseDir={AppContext.BaseDirectory}. LogPath={AppLogger.LogPath}");

        base.OnStartup(e);

        var (config, configPath) = AppConfigLoader.LoadFirstOrDefaultWithPath(AppConfigLoader.GetCandidateConfigPaths(AppContext.BaseDirectory));
        AppLogger.Info($"Config loaded. subreddits={config.RedditSubreddits.Count} craigslistSites={config.CraigslistBaseUrls.Count} csv=\"{config.CsvPath}\" alertMin={config.AlertMinConfidence}");

        var http = new AppHttpClient(config.UserAgent).Client;
        var coreLog = new AppLoggerAdapter();

        var sources = new IGearSource[]
        {
            new RedditWtbSource(http, config.RedditSubreddits),
            new CraigslistWantedSource(http, config.CraigslistBaseUrls)
        };

        var analyzer = new GearIntentAnalyzer(new GearMatcher(new GearDictionary()));

        var orchestrator = new ScanOrchestrator(
            sources: sources,
            analyzer: analyzer,
            log: coreLog
        );

        var settingsDir = !string.IsNullOrWhiteSpace(configPath) ? Path.GetDirectoryName(configPath) : null;
        var uiSettingsPath = Path.Combine(settingsDir ?? AppContext.BaseDirectory, "gearradar.ui.json");
        var uiSettings = PainRadarUiSettingsStore.Load(uiSettingsPath);
        if (uiSettings is not null)
            AppLogger.Info($"UI settings loaded: {uiSettingsPath}");

        var csvPath = ResolveCsvPath(config.CsvPath, settingsDir ?? AppContext.BaseDirectory);
        var csv = new CsvMatchLogService(csvPath);
        AppLogger.Info($"CSV logging enabled: {csv.CsvPath}");

        var vm = new MainViewModel(config, orchestrator, uiSettings, csv);
        var window = new MainWindow { DataContext = vm };
        window.ContentRendered += (_, _) =>
        {
            if (_shownOnboarding)
                return;
            _shownOnboarding = true;

            Dispatcher.BeginInvoke(new Action(() =>
            {
                try
                {
                    var onboarding = new OnboardingWindow { Owner = window };
                    onboarding.DataContext = window.DataContext;
                    onboarding.ShowDialog();
                }
                catch
                {
                }
                finally
                {
                    window.FocusSearch();
                }
            }), System.Windows.Threading.DispatcherPriority.Background);
        };

        window.Closing += (_, _) =>
        {
            try
            {
                PainRadarUiSettingsStore.Save(uiSettingsPath, vm.ToUiSettings());
                AppLogger.Info($"UI settings saved: {uiSettingsPath}");
            }
            catch
            {
            }
        };

        window.Show();
    }

    private static string ResolveCsvPath(string configured, string baseDirectory)
    {
        var p = (configured ?? "").Trim();
        if (p.Length == 0)
            p = "gearradar_matches.csv";

        if (Path.IsPathRooted(p))
            return p;

        return Path.Combine(baseDirectory, p);
    }

    private void HookGlobalExceptionLogging()
    {
        DispatcherUnhandledException += (_, args) =>
        {
            AppLogger.Exception(args.Exception, "DispatcherUnhandledException");
            ShowFatal(args.Exception, "GearRadar error (UI thread)");
            args.Handled = true;
        };

        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            if (args.ExceptionObject is Exception ex)
            {
                AppLogger.Exception(ex, "AppDomain.UnhandledException");
                ShowFatal(ex, "GearRadar crashed (unhandled)");
            }
            else
            {
                AppLogger.Error($"AppDomain.UnhandledException: {args.ExceptionObject}");
                ShowFatal(new InvalidOperationException($"Unhandled exception: {args.ExceptionObject}"), "GearRadar crashed (unhandled)");
            }
        };

        TaskScheduler.UnobservedTaskException += (_, args) =>
        {
            AppLogger.Exception(args.Exception, "TaskScheduler.UnobservedTaskException");
            args.SetObserved();
        };
    }

    private void ShowFatal(Exception ex, string title)
    {
        if (Interlocked.Exchange(ref _showingFatal, 1) != 0)
            return;

        try
        {
            var details = ex.ToString();
            var msg = $"{details}\n\nLog: {AppLogger.LogPath}";

            try { Clipboard.SetText(msg); } catch { }

            try
            {
                if (Dispatcher.CheckAccess())
                {
                    MessageBox.Show(
                        msg + "\n\n(Details copied to clipboard)",
                        title,
                        MessageBoxButton.OK,
                        MessageBoxImage.Error);
                }
                else
                {
                    Dispatcher.Invoke(() =>
                        MessageBox.Show(
                            msg + "\n\n(Details copied to clipboard)",
                            title,
                            MessageBoxButton.OK,
                            MessageBoxImage.Error));
                }
            }
            catch
            {
                AppLogger.Error("Failed to show MessageBox for fatal error; see log for details.");
            }
        }
        catch
        {
        }
        finally
        {
            Interlocked.Exchange(ref _showingFatal, 0);
        }
    }
}

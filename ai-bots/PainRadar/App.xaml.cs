using System.Diagnostics;
using System.IO;
using System.Windows;
using PainRadar.Configuration;
using PainRadar.Infrastructure;
using PainRadar.Services;
using PainRadar.ViewModels;

namespace PainRadar;

public partial class App : Application
{
    private bool _shownOnboarding;
    private int _showingFatal;

    protected override void OnStartup(StartupEventArgs e)
    {
        ConsoleAttach.TryAttachToParent();
        AppLogger.Initialize(Path.Combine(AppContext.BaseDirectory, "painradar.log"));
        HookGlobalExceptionLogging();
        AppLogger.Info($"App starting. CWD={Environment.CurrentDirectory}. BaseDir={AppContext.BaseDirectory}. LogPath={AppLogger.LogPath}");

        base.OnStartup(e);

        var (config, configPath) = AppConfigLoader.LoadFirstOrDefaultWithPath(AppConfigLoader.GetCandidateConfigPaths(AppContext.BaseDirectory));
        AppLogger.Info($"Config loaded. GoogleReviewsEnabledDefault={config.EnableGoogleReviews}. GoogleKeyPresent={!string.IsNullOrWhiteSpace(config.GooglePlacesApiKey)}");

        var http = new AppHttpClient(config.UserAgent).Client;
        var sources = new IJobSource[]
        {
            new RemotiveJobSource(http),
            new RemoteOkJobSource(http),
            new MuseJobSource(http)
        };

        var orchestrator = new ScanOrchestrator(
            sources: sources,
            reddit: new RedditSearchService(http),
            google: new GooglePlacesService(http, config.GooglePlacesApiKey, verboseLogging: Debugger.IsAttached || Environment.GetEnvironmentVariable("PAINRADAR_GOOGLE_DEBUG") == "1"),
            analyzer: new PainAnalyzer()
        );

        var settingsDir = !string.IsNullOrWhiteSpace(configPath) ? Path.GetDirectoryName(configPath) : null;
        var uiSettingsPath = Path.Combine(settingsDir ?? AppContext.BaseDirectory, "painradar.ui.json");
        var uiSettings = PainRadarUiSettingsStore.Load(uiSettingsPath);
        if (uiSettings is not null)
            AppLogger.Info($"UI settings loaded: {uiSettingsPath}");

        var sheets = new GoogleSheetsExportService(configPath);
        AppLogger.Info($"Sheets export configured={sheets.IsConfigured}");

        var vm = new MainViewModel(config, orchestrator, uiSettings, sheets);
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

    private void HookGlobalExceptionLogging()
    {
        DispatcherUnhandledException += (_, args) =>
        {
            AppLogger.Exception(args.Exception, "DispatcherUnhandledException");
            ShowFatal(args.Exception, "PainRadar error (UI thread)");
            args.Handled = true;
        };

        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            if (args.ExceptionObject is Exception ex)
            {
                AppLogger.Exception(ex, "AppDomain.UnhandledException");
                ShowFatal(ex, "PainRadar crashed (unhandled)");
            }
            else
            {
                AppLogger.Error($"AppDomain.UnhandledException: {args.ExceptionObject}");
                ShowFatal(new InvalidOperationException($"Unhandled exception: {args.ExceptionObject}"), "PainRadar crashed (unhandled)");
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

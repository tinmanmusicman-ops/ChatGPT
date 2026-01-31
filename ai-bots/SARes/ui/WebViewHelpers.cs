using System;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

namespace SARes.ui;

    public static class WebViewHelpers
    {
        private static readonly string WebViewUserDataRoot =
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SARes", "WebView2");
        private static readonly ConcurrentDictionary<string, Task<CoreWebView2Environment>> EnvironmentCache =
            new(StringComparer.OrdinalIgnoreCase);

    public static async Task EnsureReadyAsync(WebView2 view)
    {
        if (view.CoreWebView2 is not null)
            return;

        var env = await CreateEnvironmentAsync(view).ConfigureAwait(true);
        await view.EnsureCoreWebView2Async(env).ConfigureAwait(true);
        if (view.CoreWebView2 is null)
            return;

        view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
        view.CoreWebView2.Settings.AreDevToolsEnabled = false;
        view.CoreWebView2.Settings.IsZoomControlEnabled = false;
    }

        private static Task<CoreWebView2Environment> CreateEnvironmentAsync(WebView2 view)
        {
            var userDataFolder = GetUserDataFolder(view);
            Directory.CreateDirectory(userDataFolder);
            return EnvironmentCache.GetOrAdd(userDataFolder, _ => CoreWebView2Environment.CreateAsync(userDataFolder: userDataFolder));
        }

    public static void SetWebViewSource(WebView2 view, string filePath)
    {
        var uri = new Uri(filePath);
        try { view.Source = null; } catch { }
        view.Source = uri;
        try
        {
            view.CoreWebView2?.Navigate(uri.AbsoluteUri);
        }
        catch
        {
            // best-effort; already set Source.
        }
    }

    public static async Task LeftJustifyWebViewAsync(WebView2 view)
    {
        try
        {
            if (view.CoreWebView2 is null)
                return;

            const string script =
                "(function(){try{"
                + "var de=document.documentElement; var b=document.body;"
                + "if(de){de.style.margin='0';de.style.padding='0';de.scrollLeft=0;de.scrollTop=0;}"
                + "if(b){b.style.margin='0';b.style.padding='0';b.scrollLeft=0;b.scrollTop=0;}"
                + "var ids=['outerContainer','mainContainer','viewerContainer'];"
                + "for(var i=0;i<ids.length;i++){var el=document.getElementById(ids[i]); if(el){el.style.margin='0';el.style.padding='0';}}"
                + "var sc=document.scrollingElement||de||b;"
                + "if(sc){sc.scrollLeft=0;sc.scrollTop=0;}"
                + "var vc=document.getElementById('viewerContainer'); if(vc){vc.scrollLeft=0;vc.scrollTop=0;}"
                + "}catch(e){}})();";

            await view.CoreWebView2.ExecuteScriptAsync(script).ConfigureAwait(true);
            await Task.Delay(75).ConfigureAwait(true);
            await view.CoreWebView2.ExecuteScriptAsync(script).ConfigureAwait(true);
            await Task.Delay(250).ConfigureAwait(true);
            await view.CoreWebView2.ExecuteScriptAsync(script).ConfigureAwait(true);
        }
        catch
        {
            // ignore
        }
    }

    private static string GetUserDataFolder(WebView2 view)
    {
        Directory.CreateDirectory(WebViewUserDataRoot);

        var identifier = !string.IsNullOrWhiteSpace(view.Name)
            ? view.Name
            : view.GetHashCode().ToString("X");

        var invalidChars = Path.GetInvalidFileNameChars();
        var sanitized = string.Concat(identifier.Select(ch => invalidChars.Contains(ch) ? '_' : ch));
        if (string.IsNullOrWhiteSpace(sanitized))
            sanitized = view.GetHashCode().ToString("X");

        return Path.Combine(WebViewUserDataRoot, sanitized);
    }
}

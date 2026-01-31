using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;

namespace PainRadar.Services;

public sealed class AppHttpClient
{
    private readonly HttpClient _httpClient;

    public AppHttpClient(string userAgent)
    {
        var handler = new SocketsHttpHandler
        {
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate
        };

        _httpClient = new HttpClient(handler);
        _httpClient.Timeout = TimeSpan.FromSeconds(30);
        _httpClient.DefaultRequestHeaders.UserAgent.Clear();
        _httpClient.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("PainRadar", "1.0"));

        if (!string.IsNullOrWhiteSpace(userAgent) && userAgent != "PainRadar/1.0")
        {
            _httpClient.DefaultRequestHeaders.UserAgent.Clear();
            _httpClient.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", userAgent);
        }
    }

    public HttpClient Client => _httpClient;
}

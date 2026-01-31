using PainRadar.Models;

namespace PainRadar.Services;

public interface IGearSource
{
    string SourceName { get; }

    Task<IReadOnlyList<GearSignalItem>> FetchAsync(
        string searchTerm,
        int maxResults,
        CancellationToken cancellationToken);
}

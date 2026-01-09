using PainRadar.Models;

namespace PainRadar.Services;

public interface IJobSource
{
    string SourceName { get; }
    Task<IReadOnlyList<SignalItem>> FetchAsync(string searchTerm, int maxResults, CancellationToken cancellationToken);
}


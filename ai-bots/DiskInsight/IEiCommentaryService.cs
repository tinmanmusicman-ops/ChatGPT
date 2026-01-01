using System.Threading;
using System.Threading.Tasks;

namespace DiskInsight;

internal interface IEiCommentaryService
{
    Task<string> GetCommentaryAsync(EiCommentaryRequest request, CancellationToken cancellationToken);
}


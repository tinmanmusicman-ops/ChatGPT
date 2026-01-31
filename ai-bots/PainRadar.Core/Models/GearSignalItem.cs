using PainRadar.Infrastructure;

namespace PainRadar.Models;

public sealed class GearSignalItem : ObservableObject
{
    public GearSignalItem(
        string platform,
        string buyer,
        string title,
        string body,
        string url,
        DateTimeOffset? postedAtUtc)
    {
        Platform = (platform ?? "").Trim();
        Buyer = (buyer ?? "").Trim();
        Title = (title ?? "").Trim();
        Body = body ?? "";
        Url = (url ?? "").Trim();
        PostedAtUtc = postedAtUtc;

        var label = string.IsNullOrWhiteSpace(Platform) ? "Source" : Platform;
        SourceUrls = string.IsNullOrWhiteSpace(Url) ? Array.Empty<SourceLink>() : new[] { new SourceLink($"{label}: post", Url) };
    }

    public string Platform { get; }
    public string Buyer { get; }
    public string Title { get; }
    public string Body { get; }
    public string Url { get; }
    public DateTimeOffset? PostedAtUtc { get; }
    public string PostedAtDisplay => PostedAtUtc is null ? "" : PostedAtUtc.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm");

    private int _intentScore;
    public int IntentScore
    {
        get => _intentScore;
        set
        {
            if (SetProperty(ref _intentScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _gearScore;
    public int GearScore
    {
        get => _gearScore;
        set
        {
            if (SetProperty(ref _gearScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _confidenceScore;
    public int ConfidenceScore
    {
        get => _confidenceScore;
        set
        {
            if (SetProperty(ref _confidenceScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    public int TotalScore => ConfidenceScore;

    private IReadOnlyList<string> _matchedIntentPhrases = Array.Empty<string>();
    public IReadOnlyList<string> MatchedIntentPhrases
    {
        get => _matchedIntentPhrases;
        set => SetProperty(ref _matchedIntentPhrases, value);
    }

    public string MatchedIntentPhrasesDisplay => MatchedIntentPhrases.Count == 0 ? "" : string.Join(", ", MatchedIntentPhrases);

    private IReadOnlyList<string> _matchedGear = Array.Empty<string>();
    public IReadOnlyList<string> MatchedGear
    {
        get => _matchedGear;
        set => SetProperty(ref _matchedGear, value);
    }

    public string MatchedGearDisplay => MatchedGear.Count == 0 ? "" : string.Join(", ", MatchedGear);

    private IReadOnlyList<SourceLink> _sourceUrls = Array.Empty<SourceLink>();
    public IReadOnlyList<SourceLink> SourceUrls
    {
        get => _sourceUrls;
        set => SetProperty(ref _sourceUrls, value);
    }
}

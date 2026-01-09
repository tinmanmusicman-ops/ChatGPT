using PainRadar.Infrastructure;

namespace PainRadar.Models;

public sealed class SignalItem : ObservableObject
{
    public SignalItem(
        string company,
        string jobTitle,
        string location,
        string source,
        string jobUrl,
        string description)
    {
        Company = company;
        JobTitle = jobTitle;
        Location = location;
        Source = source;
        JobUrl = jobUrl;
        Description = description;
        SourceUrls = new[] { new SourceLink($"{source}: job posting", jobUrl) };
    }

    public string Company { get; }
    public string JobTitle { get; }
    public string Location { get; }
    public string Source { get; }
    public string JobUrl { get; }
    public string Description { get; }

    private int _painScore;
    public int PainScore
    {
        get => _painScore;
        set
        {
            if (SetProperty(ref _painScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _growthScore;
    public int GrowthScore
    {
        get => _growthScore;
        set
        {
            if (SetProperty(ref _growthScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _redditScore;
    public int RedditScore
    {
        get => _redditScore;
        set
        {
            if (SetProperty(ref _redditScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _googleScore;
    public int GoogleScore
    {
        get => _googleScore;
        set
        {
            if (SetProperty(ref _googleScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _fixableScore;
    public int FixableScore
    {
        get => _fixableScore;
        set
        {
            if (SetProperty(ref _fixableScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    private int _smbFitScore;
    public int SmbFitScore
    {
        get => _smbFitScore;
        set
        {
            if (SetProperty(ref _smbFitScore, value))
                OnPropertyChanged(nameof(TotalScore));
        }
    }

    public int TotalScore => PainScore + GrowthScore + RedditScore + GoogleScore + FixableScore + SmbFitScore;

    private IReadOnlyList<string> _matchedKeywords = Array.Empty<string>();
    public IReadOnlyList<string> MatchedKeywords
    {
        get => _matchedKeywords;
        set => SetProperty(ref _matchedKeywords, value);
    }

    public string MatchedKeywordsDisplay => MatchedKeywords.Count == 0 ? "" : string.Join(", ", MatchedKeywords);

    private bool _isSelectedForExport;
    public bool IsSelectedForExport
    {
        get => _isSelectedForExport;
        set => SetProperty(ref _isSelectedForExport, value);
    }

    private IReadOnlyList<SourceLink> _sourceUrls = Array.Empty<SourceLink>();
    public IReadOnlyList<SourceLink> SourceUrls
    {
        get => _sourceUrls;
        set => SetProperty(ref _sourceUrls, value);
    }
}

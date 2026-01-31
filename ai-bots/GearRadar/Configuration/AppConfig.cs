namespace PainRadar.Configuration;

public sealed record AppConfig(
    int MaxResultsPerSource,
    int RedditLimitPerSubreddit,
    int CraigslistLimitPerSite,
    IReadOnlyList<string> RedditSubreddits,
    IReadOnlyList<string> CraigslistBaseUrls,
    bool RequireIntentAndGearMatchDefault,
    int AlertMinConfidence,
    string CsvPath,
    string UserAgent
);

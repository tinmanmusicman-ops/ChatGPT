namespace PainRadar.Models;

public sealed record ScanOptions(
    string SearchTerm,
    bool EnableReddit,
    bool EnableCraigslist,
    bool RequireIntentAndGearMatch,
    int MaxResultsPerSource,
    int RedditLimitPerSubreddit,
    int CraigslistLimitPerSite
);

namespace PainRadar.Models;

public sealed record ScanOptions(
    string SearchTerm,
    bool EnableRemotive,
    bool EnableRemoteOk,
    bool EnableMuse,
    bool EnableReddit,
    bool EnableGoogleReviews,
    bool IncludeEnterprises,
    int MaxResultsPerSource,
    int MaxCompaniesToEnrich,
    int MaxEnrichmentConcurrency,
    int RedditSearchLimit
);

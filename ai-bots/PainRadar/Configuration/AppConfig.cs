namespace PainRadar.Configuration;

public sealed record AppConfig(
    string GooglePlacesApiKey,
    bool EnableGoogleReviews,
    int MaxResultsPerSource,
    int MaxCompaniesToEnrich,
    int MaxEnrichmentConcurrency,
    int RedditSearchLimit,
    string UserAgent
);


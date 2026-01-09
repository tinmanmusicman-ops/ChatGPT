namespace PainRadar.Configuration;

public sealed record PainRadarUiSettings(
    double UiFontSize,
    bool IncludeEnterprises,
    string SearchTerm,
    double MinTotalScore,
    bool EnableRemotive,
    bool EnableRemoteOk,
    bool EnableMuse,
    bool EnableReddit,
    bool EnableGoogleReviews
);


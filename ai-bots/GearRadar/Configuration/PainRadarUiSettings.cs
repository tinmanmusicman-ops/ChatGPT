namespace PainRadar.Configuration;

public sealed record PainRadarUiSettings(
    double UiFontSize,
    string SearchTerm,
    double MinTotalScore,
    bool EnableReddit,
    bool EnableCraigslist,
    bool RequireIntentAndGearMatch
);

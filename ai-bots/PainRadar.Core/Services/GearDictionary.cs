namespace PainRadar.Services;

public sealed class GearDictionary
{
    public static readonly string[] SearchTerms =
    {
        "s88",
        "88 key midi",
        "weighted midi",
        "seaboard",
        "roli",
        "ewi",
        "wind controller",
        "apc40",
        "ableton controller",
        "axiom",
        "classical guitar",
        "nylon string guitar"
    };

    public static readonly string[] CategoryTerms =
    {
        "88 key midi",
        "weighted midi",
        "wind controller",
        "ableton controller",
        "classical guitar",
        "nylon string guitar"
    };

    public IReadOnlyList<GearEntry> Entries { get; } = new[]
    {
        new GearEntry(
            CanonicalName: "Komplete Kontrol S88 Mk1",
            Aliases: new[]
            {
                "komplete kontrol s88 mk1",
                "komplete kontrol s88 mk 1",
                "komplete kontrol s88",
                "s88",
                "88 key midi",
                "weighted midi",
                "ni s88 mk1",
                "native instruments s88 mk1",
                "native instruments komplete kontrol s88"
            }
        ),
        new GearEntry(
            CanonicalName: "Roli Seaboard Rise 49",
            Aliases: new[]
            {
                "roli seaboard rise 49",
                "seaboard rise 49",
                "seaboard rise49",
                "seaboard",
                "roli",
                "roli rise 49",
                "rise 49"
            }
        ),
        new GearEntry(
            CanonicalName: "Akai EWI USB",
            Aliases: new[]
            {
                "akai ewi usb",
                "ewi usb",
                "ewi",
                "wind controller",
                "akai ewi"
            }
        ),
        new GearEntry(
            CanonicalName: "Akai APC40",
            Aliases: new[]
            {
                "akai apc40",
                "apc40",
                "ableton controller",
                "akai apc 40"
            }
        ),
        new GearEntry(
            CanonicalName: "M-Audio Axiom",
            Aliases: new[]
            {
                "m-audio axiom",
                "m audio axiom",
                "axiom",
                "axiom keyboard",
                "m-audio axiom 49",
                "m-audio axiom 61",
                "m-audio axiom 25"
            }
        ),
        new GearEntry(
            CanonicalName: "Classical Guitar",
            Aliases: new[]
            {
                "classical guitar",
                "nylon string guitar",
                "nylon-string guitar",
                "nylon guitar"
            }
        )
    };
}

public sealed record GearEntry(string CanonicalName, IReadOnlyList<string> Aliases);

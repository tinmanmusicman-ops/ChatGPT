using System;

namespace DiskInsight;

internal sealed record EiCommentaryRequest(
    string TargetType,
    string TargetName,
    int? InstanceCount,
    int? FileCount,
    int? FolderCount,
    double? TotalWorkingSetMb,
    double? TotalSizeMb,
    string? ContextHint,
    string[]? LocationHints,
    string[]? BrandHints,
    string[]? AssociatedApplications,
    TimeSpan? TotalCpuTime,
    DateTime? StartTimeEarliest,
    DateTime? StartTimeLatest,
    string? OsVersion);

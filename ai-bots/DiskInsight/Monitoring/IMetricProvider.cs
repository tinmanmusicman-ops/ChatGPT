using System;

namespace DiskInsight.Monitoring;

public interface IMetricProvider
{
    string MetricKey { get; }
    Type SnapshotType { get; }
    object Snapshot();
}

public interface IMetricProvider<out TSnapshot> : IMetricProvider where TSnapshot : class
{
    new TSnapshot Snapshot();
}


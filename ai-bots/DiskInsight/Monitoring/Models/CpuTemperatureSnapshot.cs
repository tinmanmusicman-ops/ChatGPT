using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace DiskInsight.Monitoring.Models;

public sealed record CpuTemperatureSnapshotDocument(
    [property: JsonPropertyName("cpu")] CpuTemperatureSnapshot Cpu);

public sealed record CpuTemperatureSnapshot(
    [property: JsonPropertyName("timestamp")] string Timestamp,
    [property: JsonPropertyName("cores")] List<CpuCoreTemperature> Cores,
    [property: JsonPropertyName("package_temp_c")] double? PackageTempC);

public sealed record CpuCoreTemperature(
    [property: JsonPropertyName("id")] int Id,
    [property: JsonPropertyName("temp_c")] double TempC);


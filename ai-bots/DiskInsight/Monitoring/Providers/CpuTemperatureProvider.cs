using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Management;
using DiskInsight.Monitoring.Models;

namespace DiskInsight.Monitoring.Providers;

public sealed class CpuTemperatureProvider : IMetricProvider<CpuTemperatureSnapshotDocument>
{
    private string? _lastError;
    public string? LastError => _lastError;

    public string MetricKey => "cpu";
    public Type SnapshotType => typeof(CpuTemperatureSnapshotDocument);

    public CpuTemperatureSnapshotDocument Snapshot()
    {
        var timestamp = DateTimeOffset.UtcNow.ToString("O");
        var cores = new List<CpuCoreTemperature>(capacity: 16);
        double? packageTemp = null;

        try
        {
            // Primary: LibreHardwareMonitor (real per-core temps when available).
            var read = LibreHardwareCpuSession.Shared.Read(expectedCores: 64);
            if (read.CoreTempsC.Count > 0)
            {
                cores.AddRange(read.CoreTempsC.Select(kvp => new CpuCoreTemperature(Id: kvp.Key, TempC: kvp.Value)));
            }

            packageTemp = read.PackageTempC;
            _lastError = read.Error ?? LibreHardwareCpuSession.Shared.LastError;

            // Fallback: ACPI thermal zones / perf counters (often package-ish only).
            if (packageTemp is null && cores.Count == 0)
            {
                var zoneTempsC = ReadAcpiThermalZoneTemperaturesC();
                if (zoneTempsC.Count == 0)
                {
                    zoneTempsC = ReadPerfThermalZoneTemperaturesC();
                }

                if (zoneTempsC.Count > 0)
                {
                    packageTemp = Math.Round(zoneTempsC.Max(), 1);
                }
            }
        }
        catch (Exception ex)
        {
            // If sensors are unavailable/unsupported, return an empty snapshot (UI can show blanks).
            _lastError = ex.GetType().Name + ": " + ex.Message;
        }

        cores = cores
            .OrderBy(c => c.Id)
            .GroupBy(c => c.Id)
            .Select(g => g.First())
            .ToList();

        if (packageTemp is null && cores.Count > 0)
        {
            packageTemp = Math.Round(cores.Average(c => c.TempC), 1);
        }

        return new CpuTemperatureSnapshotDocument(
            Cpu: new CpuTemperatureSnapshot(
                Timestamp: timestamp,
                Cores: cores,
                PackageTempC: packageTemp));
    }

    object IMetricProvider.Snapshot() => Snapshot();

    private static List<double> ReadAcpiThermalZoneTemperaturesC()
    {
        var temps = new List<double>(capacity: 8);
        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\WMI"),
                query: new ObjectQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    var raw = obj["CurrentTemperature"];
                    if (raw is null)
                    {
                        continue;
                    }

                    var currentTemp = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                    if (currentTemp <= 0)
                    {
                        continue;
                    }

                    // Value is tenths of Kelvin.
                    var celsius = (currentTemp / 10.0) - 273.15;
                    if (celsius is < -40 or > 150)
                    {
                        continue;
                    }

                    temps.Add(Math.Round(celsius, 1));
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        return temps;
    }

    private static List<double> ReadPerfThermalZoneTemperaturesC()
    {
        var temps = new List<double>(capacity: 8);
        try
        {
            using var searcher = new ManagementObjectSearcher(
                scope: new ManagementScope(@"\\.\root\cimv2"),
                query: new ObjectQuery("SELECT Name, Temperature, HighPrecisionTemperature FROM Win32_PerfRawData_Counters_ThermalZoneInformation"));

            foreach (ManagementObject obj in searcher.Get())
            {
                try
                {
                    // Empirically:
                    // - Temperature appears to be integer Kelvin (e.g., 350 => 350K)
                    // - HighPrecisionTemperature appears to be tenths of Kelvin (e.g., 3502 => 350.2K)
                    var highPrecision = obj["HighPrecisionTemperature"];
                    var temperature = obj["Temperature"];

                    double? kelvin = null;
                    if (highPrecision is not null)
                    {
                        var hp = Convert.ToDouble(highPrecision, CultureInfo.InvariantCulture);
                        if (hp > 0)
                        {
                            kelvin = hp / 10.0;
                        }
                    }

                    if (kelvin is null && temperature is not null)
                    {
                        var t = Convert.ToDouble(temperature, CultureInfo.InvariantCulture);
                        if (t > 0)
                        {
                            kelvin = t;
                        }
                    }

                    if (kelvin is null)
                    {
                        continue;
                    }

                    var celsius = kelvin.Value - 273.15;
                    if (celsius is < -40 or > 150)
                    {
                        continue;
                    }

                    temps.Add(Math.Round(celsius, 1));
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        return temps;
    }
}

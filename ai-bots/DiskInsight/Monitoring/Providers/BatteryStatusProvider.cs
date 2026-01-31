using System;
using System.Windows.Forms;

namespace DiskInsight.Monitoring.Providers;

public sealed record BatteryStatusSnapshot(
    double ChargePercent,
    PowerLineStatus PowerLineStatus,
    BatteryChargeStatus ChargeStatus);

public sealed class BatteryStatusProvider
{
    private string? _lastError;
    public string? LastError => _lastError;

    public BatteryStatusSnapshot? Read()
    {
        _lastError = null;
        try
        {
            var status = SystemInformation.PowerStatus;
            if (status is null)
            {
                _lastError = "Power status unavailable.";
                return null;
            }

            if (status.BatteryChargeStatus.HasFlag(BatteryChargeStatus.NoSystemBattery))
            {
                _lastError = "No system battery.";
                return null;
            }

            var life = status.BatteryLifePercent;
            if (float.IsNaN(life) || float.IsInfinity(life) || life < 0f)
            {
                _lastError = "Battery charge percent unavailable.";
                return null;
            }

            var percent = Math.Clamp((double)life * 100d, 0d, 100d);
            return new BatteryStatusSnapshot(
                ChargePercent: Math.Round(percent, 1),
                PowerLineStatus: status.PowerLineStatus,
                ChargeStatus: status.BatteryChargeStatus);
        }
        catch (Exception ex)
        {
            _lastError = ex.GetType().Name + ": " + ex.Message;
            return null;
        }
    }
}


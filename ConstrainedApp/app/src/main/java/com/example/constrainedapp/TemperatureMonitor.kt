package com.example.constrainedapp

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import java.io.File
import java.util.Locale

class TemperatureMonitor(private val context: Context) {
    data class Snapshot(val cpuCelsius: Float?, val batteryCelsius: Float?) {
        fun cpuPercent(maxTemp: Float): Float {
            val temp = cpuCelsius ?: return 0f
            return ((temp / maxTemp).coerceIn(0f, 1f) * 100f)
        }

        fun batteryPercent(maxTemp: Float): Float {
            val temp = batteryCelsius ?: return 0f
            return ((temp / maxTemp).coerceIn(0f, 1f) * 100f)
        }
    }

    fun snapshot(): Snapshot {
        val cpuTemp = readThermalZoneTemperature()
        val batteryTemp = readBatteryTemperature()
        return Snapshot(cpuCelsius = cpuTemp, batteryCelsius = batteryTemp)
    }

    private fun readThermalZoneTemperature(): Float? {
        val base = File("/sys/class/thermal")
        val zones = base.listFiles { file -> file.isDirectory && file.name.startsWith("thermal_zone") } ?: return null
        val candidates = zones.mapNotNull { zone ->
            val temp = readThermalTemp(zone) ?: return@mapNotNull null
            val type = readThermalType(zone)
            ZoneCandidate(type = type, temp = temp)
        }
        if (candidates.isEmpty()) {
            return null
        }

        return candidates
            .sortedWith(compareByDescending<ZoneCandidate> { it.type?.contains("cpu") == true }
                .thenByDescending { it.temp })
            .firstOrNull()
            ?.temp
    }

    private fun readThermalTemp(zone: File): Float? {
        val file = File(zone, "temp")
        return try {
            if (!file.exists() || !file.canRead()) {
                null
            } else {
                file.readText().trim().toFloatOrNull()?.let { value ->
                    if (value > 1000f) {
                        value / 1000f
                    } else {
                        value
                    }
                }
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun readThermalType(zone: File): String? {
        val file = File(zone, "type")
        return try {
            if (!file.exists() || !file.canRead()) {
                null
            } else {
                file.readText().trim().lowercase(Locale.US)
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun readBatteryTemperature(): Float? {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val tempTenths = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1)
        if (tempTenths < 0) {
            return null
        }
        return tempTenths / 10f
    }

    private data class ZoneCandidate(val type: String?, val temp: Float)

    companion object {
        const val MAX_CPU_TEMP = 100f
        const val MAX_BATTERY_TEMP = 60f
    }
}

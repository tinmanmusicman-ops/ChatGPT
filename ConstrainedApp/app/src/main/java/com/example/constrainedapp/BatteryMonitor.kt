package com.example.constrainedapp

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import java.io.File

class BatteryMonitor(context: Context) {
    private val appContext = context.applicationContext

    data class BatterySnapshot(
        val chargePercent: Float,
        val isCharging: Boolean,
    )

    fun snapshot(): BatterySnapshot {
        val sticky = readStickyBatteryIntent()
        val percent = readPercentFromBatteryManager()
            ?: readPercentFromStickyIntent(sticky)
            ?: 0f
        val isCharging = readIsChargingFromSysfs()
            ?: readIsChargingFromBatteryIntent(sticky)
        return BatterySnapshot(
            chargePercent = percent.coerceIn(0f, 100f),
            isCharging = isCharging,
        )
    }

    fun chargePercent(): Float {
        return snapshot().chargePercent
    }

    private fun readPercentFromBatteryManager(): Float? {
        val manager = appContext.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager ?: return null
        val capacity = manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        if (capacity < 0 || capacity > 100) return null
        return capacity.toFloat()
    }

    private fun readStickyBatteryIntent(): Intent? {
        return appContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
    }

    private fun readPercentFromStickyIntent(intent: Intent?): Float? {
        if (intent == null) return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return null
        return ((level.toFloat() / scale.toFloat()) * 100f).coerceIn(0f, 100f)
    }

    private fun readIsChargingFromBatteryIntent(intent: Intent?): Boolean {
        if (intent == null) return false
        val plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0)
        return plugged != 0
    }

    private fun readIsChargingFromSysfs(): Boolean? {
        // Prefer the path you mentioned first.
        val preferred = readOnlineFlag("/sys/class/power_supply/battery/online")
            ?: readOnlineFlag("/sys/class/power_supply/Battery/online")
        if (preferred != null) return preferred

        // Otherwise, consider any non-battery supply with online=1 as "plugged in".
        val dir = File("/sys/class/power_supply")
        val children = try { dir.listFiles() } catch (_: Exception) { null } ?: return null

        var anyReadable = false
        for (child in children) {
            val name = child.name.lowercase()
            if (name.contains("battery")) continue

            val online = readOnlineFlag(File(child, "online").path) ?: continue
            anyReadable = true
            if (online) return true
        }

        if (anyReadable) return false

        // Fallback list for common supplies on some devices.
        val candidates = listOf(
            "/sys/class/power_supply/battery/online",
            "/sys/class/power_supply/Battery/online",
            "/sys/class/power_supply/ac/online",
            "/sys/class/power_supply/AC/online",
            "/sys/class/power_supply/usb/online",
            "/sys/class/power_supply/USB/online",
            "/sys/class/power_supply/mains/online",
            "/sys/class/power_supply/Mains/online",
            "/sys/class/power_supply/charger/online",
            "/sys/class/power_supply/Charger/online",
        )

        for (path in candidates) {
            val online = readOnlineFlag(path) ?: continue
            return online
        }

        return null
    }

    private fun readOnlineFlag(path: String): Boolean? {
        val raw = readSmallTextFile(path) ?: return null
        val value = raw.trim()
        if (value == "1") return true
        if (value == "0") return false
        return null
    }

    private fun readSmallTextFile(path: String): String? {
        return try {
            val file = File(path)
            if (!file.exists() || !file.canRead()) return null
            file.readText(Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }
}

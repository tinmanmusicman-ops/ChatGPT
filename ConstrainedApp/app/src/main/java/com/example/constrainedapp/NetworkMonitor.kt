package com.example.constrainedapp

import android.net.TrafficStats
import android.os.SystemClock
import android.util.Log

class NetworkMonitor(
    private val maxMbps: Float = DEFAULT_MAX_MBPS,
) {
    private var lastTotalBytes: Long? = null
    private var lastTimeMs: Long? = null
    private var lastLogMs: Long = 0L

    fun sampleUsagePercent(): Float {
        val currentBytes = readTotalBytes() ?: return 0f
        val nowMs = SystemClock.elapsedRealtime()

        val prevBytes = lastTotalBytes
        val prevMs = lastTimeMs
        lastTotalBytes = currentBytes
        lastTimeMs = nowMs

        if (prevBytes == null || prevMs == null) {
            maybeLog(nowMs, "NET primed: totalBytes=$currentBytes maxMbps=$maxMbps")
            return 0f
        }

        val deltaBytes = (currentBytes - prevBytes).coerceAtLeast(0L)
        val deltaMs = (nowMs - prevMs).coerceAtLeast(0L)
        if (deltaMs <= 0L) return 0f

        val seconds = deltaMs / 1000.0
        val mbps = (deltaBytes * 8.0) / seconds / 1_000_000.0
        val percent = (mbps / maxMbps.toDouble()) * 100.0
        val clamped = percent.coerceIn(0.0, 100.0).toFloat()
        maybeLog(
            nowMs,
            "NET deltaBytes=$deltaBytes deltaMs=$deltaMs mbps=${"%.2f".format(mbps)} pct=${"%.1f".format(clamped)} (maxMbps=$maxMbps)",
        )
        return clamped
    }

    private fun readTotalBytes(): Long? {
        val rx = TrafficStats.getTotalRxBytes()
        val tx = TrafficStats.getTotalTxBytes()
        if (rx < 0L || tx < 0L) return null
        return rx + tx
    }

    companion object {
        private const val DEFAULT_MAX_MBPS = 100f
        private const val TAG = "NetworkMonitor"
    }

    private fun maybeLog(nowMs: Long, message: String) {
        if (nowMs - lastLogMs < 5_000L) return
        lastLogMs = nowMs
        Log.d(TAG, message)
    }
}

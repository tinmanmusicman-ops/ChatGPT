package com.example.constrainedapp

import android.app.ActivityManager
import android.content.Context

class MemoryMonitor(context: Context) {
    private val activityManager =
        context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
    private val memoryInfo = ActivityManager.MemoryInfo()

    data class Snapshot(val totalGb: Float, val usedGb: Float)

    fun snapshot(): Snapshot {
        activityManager.getMemoryInfo(memoryInfo)
        val totalGb = memoryInfo.totalMem / (1024f * 1024f * 1024f)
        val availGb = memoryInfo.availMem / (1024f * 1024f * 1024f)
        val usedGb = totalGb - availGb
        return Snapshot(totalGb, usedGb)
    }
}

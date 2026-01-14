package com.example.eat

import android.content.Context
import android.util.Log
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object YahooForwarderScheduler {
    private const val TAG = "YahooForwarderScheduler"
    const val WORK_NAME = "YahooForwarderWorker"
    private const val DEFAULT_INTERVAL_MINUTES = 15L

    fun schedule(context: Context, intervalMinutes: Long = DEFAULT_INTERVAL_MINUTES) {
        if (intervalMinutes <= 0L) {
            Log.w(TAG, "Interval must be positive; skipping schedule")
            return
        }
        val delayMinutes = computeDelay(context, intervalMinutes)
        Log.i(TAG, "Scheduling YahooForwarderWorker in $delayMinutes minute(s) (requested $intervalMinutes)")
        val request = OneTimeWorkRequestBuilder<YahooForwarderWorker>()
            .setInitialDelay(delayMinutes, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

    fun scheduleNext(context: Context) {
        schedule(context, DEFAULT_INTERVAL_MINUTES)
    }

    private fun computeDelay(context: Context, requestedMinutes: Long): Long {
        if (SleepPrefs.isSleepWindowActive(context)) {
            val untilWake = SleepPrefs.minutesUntilWake(context).coerceAtLeast(1)
            Log.i(TAG, "Sleep window active; deferring Yahoo forwarder for $untilWake minute(s)")
            return untilWake.toLong()
        }
        return requestedMinutes
    }
}

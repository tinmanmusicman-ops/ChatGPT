package com.example.eat

import android.content.Context
import android.util.Log
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object ReminderScheduler {
    private const val TAG = "ReminderScheduler"

    fun schedule(context: Context, intervalMinutes: Long) {
        if (intervalMinutes <= 0L) {
            Log.w(TAG, "Interval must be positive; skipping schedule")
            return
        }
        val currentMinutes = SleepPrefs.currentMinutesSinceMidnight()
        val delayMinutes = if (SleepPrefs.isSleepWindowActive(context, currentMinutes)) {
            val untilWake = SleepPrefs.minutesUntilWake(context, currentMinutes).coerceAtLeast(1)
            Log.i(TAG, "Sleep window active; deferring reminder for $untilWake minute(s)")
            untilWake.toLong()
        } else {
            intervalMinutes
        }
        Log.i(TAG, "Scheduling EatWorker for $delayMinutes minute delay (requested $intervalMinutes minutes)")
        val request = OneTimeWorkRequestBuilder<EatWorker>()
            .setInitialDelay(delayMinutes, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(context)
            .enqueueUniqueWork(EatWorker.WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

}

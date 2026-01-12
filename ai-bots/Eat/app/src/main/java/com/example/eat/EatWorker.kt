package com.example.eat

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

class EatWorker(
    context: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(context, workerParams) {

    override suspend fun doWork(): Result {
        val intervalMinutes = currentIntervalMinutes()
        val firedAt = System.currentTimeMillis()
        val timestamp = timestampNow()
        Log.i(TAG, "EatWorker fired for $intervalMinutes minute interval at $timestamp")
        ReminderPrefs.recordHistoryEntry(applicationContext, HistoryEntry(firedAt, HistoryType.REMINDER))
        ReminderPrefs.resetActionState(applicationContext)
        NotificationHelper.showNotification(applicationContext)
        scheduleNext(intervalMinutes)
        return Result.success()
    }

    private fun currentIntervalMinutes(): Long {
        return ReminderPrefs.getInterval(applicationContext)
    }

    private fun scheduleNext(intervalMinutes: Long) {
        if (!ReminderPrefs.isEnabled(applicationContext)) {
            Log.i(TAG, "Reminders disabled; skipping next scheduling")
            return
        }
        if (intervalMinutes <= 0L) return

        Log.i(TAG, "Scheduling next EatWorker in $intervalMinutes minute(s)")

        val request = OneTimeWorkRequestBuilder<EatWorker>()
            .setInitialDelay(intervalMinutes, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(applicationContext)
            .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

    private fun timestampNow(): String {
        val formatter = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
        return formatter.format(Date())
    }

    companion object {
        const val WORK_NAME = "EatWorker"
        private const val CHANNEL_ID = "eat_reminder_channel"
        const val NOTIFICATION_ID = 2048
        private const val NOTIFICATION_TEXT = "Eat"
        private const val TAG = "EatWorker"
    }
}

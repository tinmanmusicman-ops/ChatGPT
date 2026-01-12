package com.example.eat

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
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
        val timestamp = timestampNow()
        Log.i(TAG, "EatWorker fired for $intervalMinutes minute interval at $timestamp")
        showNotification()
        scheduleNext(intervalMinutes)
        return Result.success()
    }

    private fun currentIntervalMinutes(): Long {
        return applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getLong(PREF_INTERVAL_KEY, DEFAULT_INTERVAL_MINUTES)
            .coerceAtLeast(1L)
    }

    private fun scheduleNext(intervalMinutes: Long) {
        if (intervalMinutes <= 0L) return

        val request = OneTimeWorkRequestBuilder<EatWorker>()
            .setInitialDelay(intervalMinutes, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(applicationContext)
            .enqueueUniqueWork(WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

    private fun showNotification() {
        ensureChannel()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(
                applicationContext,
                Manifest.permission.POST_NOTIFICATIONS
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(NOTIFICATION_TEXT)
            .setContentText(NOTIFICATION_TEXT)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setVibrate(longArrayOf(0, 250, 200, 250))
            .build()

        NotificationManagerCompat.from(applicationContext)
            .notify(NOTIFICATION_ID, notification)
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }

        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
            ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) {
            return
        }

        val channel = NotificationChannel(
            CHANNEL_ID,
            "Eat reminders",
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 250, 200, 250)
            description = "Periodic reminders to pause and eat."
        }
        manager.createNotificationChannel(channel)
    }

    private fun timestampNow(): String {
        val formatter = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
        return formatter.format(Date())
    }

    companion object {
        const val WORK_NAME = "EatWorker"
        private const val CHANNEL_ID = "eat_reminder_channel"
        private const val NOTIFICATION_ID = 2048
        private const val NOTIFICATION_TEXT = "Eat"
        private const val TAG = "EatWorker"
        private const val DEFAULT_INTERVAL_MINUTES = 15L
    }
}

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
        Log.i(TAG, "Scheduling EatWorker for $intervalMinutes minute interval")
        val request = OneTimeWorkRequestBuilder<EatWorker>()
            .setInitialDelay(intervalMinutes, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(context)
            .enqueueUniqueWork(EatWorker.WORK_NAME, ExistingWorkPolicy.REPLACE, request)
    }

}

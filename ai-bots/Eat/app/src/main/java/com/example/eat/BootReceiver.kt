package com.example.eat

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) {
            return
        }
        Log.i(TAG, "BootReceiver triggered")

        if (!ReminderPrefs.isEnabled(context)) {
            Log.i(TAG, "Reminders disabled; skipping boot reschedule")
            return
        }

        val intervalMinutes = ReminderPrefs.getInterval(context)
        Log.i(TAG, "Rescheduling EatWorker for $intervalMinutes minute interval on boot")
        ReminderScheduler.schedule(context, intervalMinutes)
    }

    companion object {
        private const val TAG = "BootReceiver"
    }
}

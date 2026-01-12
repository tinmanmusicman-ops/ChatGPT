package com.example.eat

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.app.NotificationManagerCompat

class NotificationActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        val actionId = intent.getLongExtra(EXTRA_ACTION_ID, -1L).let {
            if (it <= 0L) System.currentTimeMillis() else it
        }
        when (action) {
            ACTION_ATE -> handleIAte(context, actionId)
            ACTION_VISION_PROMPT -> handleVisionPrompt(context)
            ACTION_VISION_CHOICE -> handleVisionChoice(context, intent, actionId)
            ACTION_DONE -> handleDone(context)
        }
    }

    private fun handleIAte(context: Context, actionId: Long) {
        if (!ReminderPrefs.isMealActionNew(context, actionId)) {
            Log.i(TAG, "Duplicate 'I Ate' action ignored")
            return
        }
        Log.i(TAG, "Notification action 'I Ate' triggered")
        ReminderPrefs.recordMealAcknowledgement(context)
        ReminderPrefs.setVisionPromptPending(context, false)
        ReminderPrefs.setEnabled(context, true)
        ReminderScheduler.schedule(context, ReminderPrefs.getInterval(context))
        NotificationHelper.showNotification(context)
    }

    private fun handleVisionPrompt(context: Context) {
        Log.i(TAG, "Notification action 'How's My Vision?' prompt triggered")
        if (ReminderPrefs.isVisionPromptPending(context)) {
            Log.i(TAG, "Vision prompt already visible; ignoring duplicate")
            return
        }
        ReminderPrefs.setVisionPromptPending(context, true)
        NotificationHelper.showNotification(context)
    }

    private fun handleVisionChoice(context: Context, intent: Intent, actionId: Long) {
        if (!ReminderPrefs.isVisionActionNew(context, actionId)) {
            Log.i(TAG, "Duplicate vision choice ignored")
            return
        }
        val status = intent.getStringExtra(EXTRA_VISION_STATUS) ?: "UNKNOWN"
        Log.i(TAG, "Notification action 'Vision choice' triggered: $status")
        ReminderPrefs.recordVisionStatus(context, status)
        NotificationHelper.showNotification(context)
    }

    private fun handleDone(context: Context) {
        Log.i(TAG, "Notification action 'Done' triggered")
        NotificationManagerCompat.from(context).cancel(EatWorker.NOTIFICATION_ID)
    }

    companion object {
        private const val TAG = "NotificationActionReceiver"
        const val ACTION_ATE = "com.example.eat.ACTION_ATE"
        const val ACTION_VISION_PROMPT = "com.example.eat.ACTION_VISION_PROMPT"
        const val ACTION_VISION_CHOICE = "com.example.eat.ACTION_VISION_CHOICE"
        const val ACTION_DONE = "com.example.eat.ACTION_DONE"
        const val EXTRA_VISION_STATUS = "vision_status"
        const val EXTRA_ACTION_ID = "action_id"
    }
}

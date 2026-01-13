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
            ACTION_ATE -> handleIAte(context, intent, actionId)
            ACTION_VISION_CHOICE -> handleVisionChoice(context, intent, actionId)
            ACTION_DONE -> handleDone(context)
        }
    }

    private fun handleIAte(context: Context, intent: Intent, actionId: Long) {
        if (!ReminderPrefs.isMealActionNew(context, actionId)) {
            Log.i(TAG, "Duplicate 'I Ate' action ignored")
            return
        }
        val mealLabel = intent.getStringExtra(EXTRA_MEAL_TYPE)
        val mealType = try {
            if (mealLabel.isNullOrBlank()) throw IllegalArgumentException("Missing meal type")
            MealType.valueOf(mealLabel)
        } catch (ex: Exception) {
            Log.e(TAG, "Unknown meal type: $mealLabel", ex)
            return
        }
        Log.i(TAG, "Notification action 'I Ate' triggered: $mealType")
        ReminderPrefs.setLastMealType(context, mealType)
        ReminderPrefs.recordMealAcknowledgement(context)
        ReminderPrefs.recordHistoryEntry(
            context,
            HistoryEntry(System.currentTimeMillis(), HistoryType.I_ATE, mealType = mealType)
        )
        ReminderPrefs.setVisionPromptPending(context, true)
        ReminderPrefs.setEnabled(context, true)
        ReminderScheduler.schedule(context, ReminderPrefs.getInterval(context))
        NotificationHelper.showNotification(context)
    }

    private fun handleVisionChoice(context: Context, intent: Intent, actionId: Long) {
        if (!ReminderPrefs.isVisionActionNew(context, actionId)) {
            Log.i(TAG, "Duplicate vision choice ignored")
            return
        }
        val status = intent.getStringExtra(EXTRA_VISION_STATUS)
        if (status.isNullOrBlank()) {
            Log.e(TAG, "Vision action came without status")
            return
        }
        Log.i(TAG, "Notification action 'Vision choice' triggered: $status")
        val clarity = VisionClarity.fromLabel(status)
        if (clarity == null) {
            Log.e(TAG, "Unknown vision status: $status")
            return
        }
        ReminderPrefs.recordVisionStatus(context, clarity.label)
        ReminderPrefs.recordHistoryEntry(context, HistoryEntry(System.currentTimeMillis(), HistoryType.VISION, clarity))
        NotificationHelper.showNotification(context)
    }

    private fun handleDone(context: Context) {
        if (!ReminderPrefs.hasActiveSelection(context)) {
            Log.i(TAG, "Notification action 'Done' ignored (no active selection)")
            return
        }
        Log.i(TAG, "Notification action 'Done' triggered")
        ReminderPrefs.resetActionState(context)
        NotificationManagerCompat.from(context).cancel(EatWorker.NOTIFICATION_ID)
    }

    companion object {
        private const val TAG = "NotificationActionReceiver"
        const val ACTION_ATE = "com.example.eat.ACTION_ATE"
        const val ACTION_VISION_CHOICE = "com.example.eat.ACTION_VISION_CHOICE"
        const val ACTION_DONE = "com.example.eat.ACTION_DONE"
        const val EXTRA_VISION_STATUS = "vision_status"
        const val EXTRA_MEAL_TYPE = "meal_type"
        const val EXTRA_ACTION_ID = "action_id"
    }
}

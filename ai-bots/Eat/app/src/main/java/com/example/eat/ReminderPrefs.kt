package com.example.eat

import android.content.Context

object ReminderPrefs {
    private const val PREFS_NAME = "EatPrefs"
    private const val KEY_INTERVAL = "interval_minutes"
    private const val KEY_ENABLED = "reminders_enabled"
    private const val KEY_LAST_MEAL = "last_meal_timestamp"
    private const val KEY_LAST_VISION = "last_vision_status"
    private const val KEY_ATE_DONE = "ate_done"
    private const val KEY_VISION_DONE = "vision_done"
    private const val KEY_VISION_PROMPT = "vision_prompt_pending"
    private const val KEY_LAST_MEAL_ACTION = "last_meal_action_id"
    private const val KEY_LAST_VISION_ACTION = "last_vision_action_id"
    private const val DEFAULT_INTERVAL_MINUTES = 15L

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getInterval(context: Context): Long =
        prefs(context).getLong(KEY_INTERVAL, DEFAULT_INTERVAL_MINUTES).coerceAtLeast(1L)

    fun setInterval(context: Context, intervalMinutes: Long) {
        prefs(context).edit().putLong(KEY_INTERVAL, intervalMinutes.coerceAtLeast(1L)).apply()
    }

    fun setEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_ENABLED, enabled).apply()
    }

    fun isEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ENABLED, false)

    fun recordMealAcknowledgement(context: Context, timestamp: Long = System.currentTimeMillis()) {
        prefs(context).edit().putLong(KEY_LAST_MEAL, timestamp).apply()
        prefs(context).edit().putBoolean(KEY_ATE_DONE, true).apply()
    }

    fun isAteDone(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ATE_DONE, false)

    fun recordVisionStatus(context: Context, status: String) {
        prefs(context).edit().putString(KEY_LAST_VISION, status).apply()
        prefs(context).edit().putBoolean(KEY_VISION_DONE, true).apply()
        setVisionPromptPending(context, false)
    }

    fun getVisionStatus(context: Context): String? =
        prefs(context).getString(KEY_LAST_VISION, null)

    fun setVisionPromptPending(context: Context, pending: Boolean) {
        prefs(context).edit().putBoolean(KEY_VISION_PROMPT, pending).apply()
    }

    fun isVisionPromptPending(context: Context): Boolean =
        prefs(context).getBoolean(KEY_VISION_PROMPT, false)

    fun isMealActionNew(context: Context, actionId: Long): Boolean {
        val prefs = prefs(context)
        val existing = prefs.getLong(KEY_LAST_MEAL_ACTION, -1L)
        if (existing == actionId) return false
        prefs.edit().putLong(KEY_LAST_MEAL_ACTION, actionId).apply()
        return true
    }

    fun isVisionActionNew(context: Context, actionId: Long): Boolean {
        val prefs = prefs(context)
        val existing = prefs.getLong(KEY_LAST_VISION_ACTION, -1L)
        if (existing == actionId) return false
        prefs.edit().putLong(KEY_LAST_VISION_ACTION, actionId).apply()
        return true
    }

    fun resetActionState(context: Context) {
        prefs(context).edit().putBoolean(KEY_ATE_DONE, false).apply()
        prefs(context).edit().putBoolean(KEY_VISION_DONE, false).apply()
        prefs(context).edit().remove(KEY_LAST_MEAL_ACTION).remove(KEY_LAST_VISION_ACTION).apply()
        prefs(context).edit().remove(KEY_LAST_VISION).apply()
        setVisionPromptPending(context, false)
    }
}

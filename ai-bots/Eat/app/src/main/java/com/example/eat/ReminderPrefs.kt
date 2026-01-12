package com.example.eat

import android.content.Context
import android.util.Log
import java.util.Calendar

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
    private const val KEY_HISTORY_DATE = "history_date"
    private const val KEY_HISTORY_ENTRIES = "history_entries"
    private const val HISTORY_DELIMITER = "|"
    private const val HISTORY_RECORD_SEPARATOR = "\n"
    private const val TAG = "ReminderPrefs"

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

    fun startOfDay(timestamp: Long): Long {
        val calendar = Calendar.getInstance().apply {
            timeInMillis = timestamp
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        return calendar.timeInMillis
    }

    fun recordHistoryEntry(context: Context, entry: HistoryEntry) {
        val prefs = prefs(context)
        val todayStart = startOfDay(entry.timestamp)
        val editor = prefs.edit()
        val storedDay = prefs.getLong(KEY_HISTORY_DATE, 0L)
        if (storedDay != todayStart) {
            editor.putLong(KEY_HISTORY_DATE, todayStart)
            editor.putString(KEY_HISTORY_ENTRIES, "")
        }
        val serialized = serializeHistoryEntry(entry)
        val existing = prefs.getString(KEY_HISTORY_ENTRIES, "") ?: ""
        val updated = if (existing.isBlank()) serialized else "$existing$HISTORY_RECORD_SEPARATOR$serialized"
        editor.putString(KEY_HISTORY_ENTRIES, updated)
        editor.apply()
        Log.d(TAG, "recordHistoryEntry type=${entry.type} clarity=${entry.clarity} ts=${entry.timestamp}")
    }

    fun getTodayHistory(context: Context): List<HistoryEntry> {
        val prefs = prefs(context)
        val todayStart = startOfDay(System.currentTimeMillis())
        if (prefs.getLong(KEY_HISTORY_DATE, 0L) != todayStart) return emptyList()
        val raw = prefs.getString(KEY_HISTORY_ENTRIES, "") ?: return emptyList()
        if (raw.isBlank()) return emptyList()
        val now = System.currentTimeMillis()
        val entries = raw.lines()
            .mapNotNull { parseHistoryEntry(it) }
            .filter { it.timestamp >= todayStart }
            .sortedBy { it.timestamp }
        val visionCount = entries.count { it.type == HistoryType.VISION }
        Log.d(TAG, "getTodayHistory total=${entries.size} visionCount=$visionCount range=${todayStart}..$now")
        return entries
    }

    private fun serializeHistoryEntry(entry: HistoryEntry): String {
        val clarityName = entry.clarity?.name ?: ""
        val mealName = entry.mealType?.name ?: ""
        return "${entry.timestamp}$HISTORY_DELIMITER${entry.type.name}$HISTORY_DELIMITER$clarityName$HISTORY_DELIMITER$mealName"
    }

    private fun parseHistoryEntry(raw: String): HistoryEntry? {
        val parts = raw.split(HISTORY_DELIMITER)
        if (parts.size < 2) return null
        val timestamp = parts[0].toLongOrNull() ?: return null
        val type = try {
            HistoryType.valueOf(parts[1])
        } catch (ex: IllegalArgumentException) {
            return null
        }
        val clarity = if (parts.size >= 3 && parts[2].isNotBlank()) {
            try {
                VisionClarity.valueOf(parts[2])
            } catch (ignored: IllegalArgumentException) {
                null
            }
        } else {
            null
        }
        val mealType = if (parts.size >= 4 && parts[3].isNotBlank()) {
            try {
                MealType.valueOf(parts[3])
            } catch (ignored: IllegalArgumentException) {
                null
            }
        } else {
            null
        }
        return HistoryEntry(timestamp, type, clarity, mealType)
    }
}

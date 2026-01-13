package com.example.eat

import android.content.Context
import android.util.Log
import java.time.LocalDate
import java.time.ZoneId
import java.util.Calendar
import java.util.Random

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
    private const val KEY_LAST_MEAL_TYPE = "last_meal_type"
    private const val KEY_HISTORY_ENTRIES = "history_entries"
    private const val KEY_HISTORY_SEED_RANDOM = "history_seed_random"
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

    fun setLastMealType(context: Context, mealType: MealType?) {
        val editor = prefs(context).edit()
        if (mealType == null) {
            editor.remove(KEY_LAST_MEAL_TYPE)
        } else {
            editor.putString(KEY_LAST_MEAL_TYPE, mealType.name)
        }
        editor.apply()
    }

    fun getLastMealType(context: Context): MealType? {
        val raw = prefs(context).getString(KEY_LAST_MEAL_TYPE, "") ?: ""
        if (raw.isBlank()) return null
        return try {
            MealType.valueOf(raw)
        } catch (ex: IllegalArgumentException) {
            null
        }
    }

    fun hasMealSelection(context: Context): Boolean =
        getLastMealType(context) != null

    fun hasActiveSelection(context: Context): Boolean =
        hasMealSelection(context) || getVisionStatus(context) != null

    fun clearSelectionState(context: Context) {
        setLastMealType(context, null)
    }

    fun resetActionState(context: Context) {
        prefs(context).edit().putBoolean(KEY_ATE_DONE, false).apply()
        prefs(context).edit().putBoolean(KEY_VISION_DONE, false).apply()
        prefs(context).edit().remove(KEY_LAST_MEAL_ACTION).remove(KEY_LAST_VISION_ACTION).apply()
        prefs(context).edit().remove(KEY_LAST_VISION).apply()
        setVisionPromptPending(context, false)
        clearSelectionState(context)
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

    private fun endOfDay(timestamp: Long): Long {
        val calendar = Calendar.getInstance().apply {
            timeInMillis = timestamp
            set(Calendar.HOUR_OF_DAY, 23)
            set(Calendar.MINUTE, 59)
            set(Calendar.SECOND, 59)
            set(Calendar.MILLISECOND, 999)
        }
        return calendar.timeInMillis
    }

    fun recordHistoryEntry(context: Context, entry: HistoryEntry) {
        val prefs = prefs(context)
        val editor = prefs.edit()
        val serialized = serializeHistoryEntry(entry)
        val existing = prefs.getString(KEY_HISTORY_ENTRIES, "") ?: ""
        val updated = if (existing.isBlank()) serialized else "$existing$HISTORY_RECORD_SEPARATOR$serialized"
        editor.putString(KEY_HISTORY_ENTRIES, updated)
        editor.apply()
        Log.d(TAG, "recordHistoryEntry type=${entry.type} clarity=${entry.clarity} ts=${entry.timestamp}")
        if (entry.mealType != null) {
            setLastMealType(context, entry.mealType)
        }
    }

    fun getTodayHistory(context: Context): List<HistoryEntry> {
        val now = System.currentTimeMillis()
        val start = startOfDay(now)
        val end = endOfDay(now)
        return getHistoryEntriesBetween(context, start, end)
    }

    fun getHistoryEntriesBetween(context: Context, startMillis: Long, endMillis: Long): List<HistoryEntry> {
        val prefs = prefs(context)
        ensureHistorySeeded(context)
        val raw = prefs.getString(KEY_HISTORY_ENTRIES, "") ?: return emptyList()
        if (raw.isBlank()) return emptyList()
        val entries = raw.lines()
            .mapNotNull { parseHistoryEntry(it) }
            .filter { it.timestamp in startMillis..endMillis }
            .sortedBy { it.timestamp }
        val visionCount = entries.count { it.type == HistoryType.VISION }
        Log.d(TAG, "getHistoryEntriesBetween total=${entries.size} visionCount=$visionCount range=${startMillis}..${endMillis}")
        return entries
    }

    fun ensureHistorySeeded(context: Context) {
        val prefs = prefs(context)
        val existing = prefs.getString(KEY_HISTORY_ENTRIES, "") ?: ""
        if (existing.isNotBlank()) return
        val seedRandom = getSeedRandom(context)
        val entries = generateSeedEntries(seedRandom)
        entries.forEach { recordHistoryEntry(context, it) }
    }

    private fun getSeedRandom(context: Context): Long {
        val prefs = prefs(context)
        var seed = prefs.getLong(KEY_HISTORY_SEED_RANDOM, Long.MIN_VALUE)
        if (seed == Long.MIN_VALUE) {
            seed = System.currentTimeMillis() xor System.nanoTime()
            prefs.edit().putLong(KEY_HISTORY_SEED_RANDOM, seed).apply()
        }
        return seed
    }

    private fun generateSeedEntries(seed: Long): List<HistoryEntry> {
        val zone = ZoneId.systemDefault()
        val entries = mutableListOf<HistoryEntry>()
        val now = LocalDate.now(zone)
        fun timestampFor(day: LocalDate, hour: Int): Long =
            day.atTime(hour, 0).atZone(zone).toInstant().toEpochMilli()

        for (dayOffset in 6 downTo 0) {
            val day = now.minusDays(dayOffset.toLong())
            val daySeed = seed xor day.toEpochDay()
            val dayRandom = Random(daySeed)
            val visionShift = ((dayOffset % 5) - 2).coerceIn(-2, 2)
            val mealShift = ((dayOffset % 3) - 1).coerceIn(-1, 1)
            val cloudyEndHour = (8 + visionShift).coerceIn(6, 10)
            val mediumEndHour = (16 + visionShift).coerceIn(cloudyEndHour + 2, 20)
            for (hour in 0..22 step 2) {
                val baseTimestamp = timestampFor(day, hour)
                val jitterMinutes = dayRandom.nextInt(31) - 15 // ±15 minutes
                val timestamp = (baseTimestamp + jitterMinutes * 60_000L).coerceIn(dayStartMillis(day, zone), dayEndMillis(day, zone))
                val clarity = pickVisionClarity(dayRandom, hour, cloudyEndHour, mediumEndHour)
                entries.add(HistoryEntry(timestamp, HistoryType.VISION, clarity = clarity))
            }
            listOf(8, 12, 18).forEach { hour ->
                val shiftedHour = (hour + mealShift).coerceIn(6, 20)
                val baseTimestamp = timestampFor(day, shiftedHour)
                val jitterMinutes = dayRandom.nextInt(21) - 10 // ±10 min
                val timestamp = (baseTimestamp + jitterMinutes * 60_000L).coerceIn(dayStartMillis(day, zone), dayEndMillis(day, zone))
                val mealType = if (dayRandom.nextDouble() < 0.7) MealType.MEAL else MealType.SNACK
                entries.add(HistoryEntry(timestamp, HistoryType.I_ATE, mealType = mealType))
            }
        }
        return entries.sortedBy { it.timestamp }
    }

    // Example data randomization helpers (do NOT affect real history)
    private fun dayStartMillis(day: LocalDate, zone: ZoneId): Long =
        day.atStartOfDay(zone).toInstant().toEpochMilli()

    private fun dayEndMillis(day: LocalDate, zone: ZoneId): Long =
        day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli() - 1

    private fun pickVisionClarity(
        random: Random,
        hour: Int,
        cloudyEndHour: Int,
        mediumEndHour: Int
    ): VisionClarity {
        val choices = when {
            hour <= cloudyEndHour -> listOf(
                VisionClarity.CLOUDY,
                VisionClarity.CLOUDY,
                VisionClarity.MODERATE
            )
            hour <= mediumEndHour -> listOf(
                VisionClarity.MODERATE,
                VisionClarity.MODERATE,
                VisionClarity.CLOUDY,
                VisionClarity.ALMOST_CLEAR
            )
            else -> listOf(
                VisionClarity.ALMOST_CLEAR,
                VisionClarity.ALMOST_CLEAR,
                VisionClarity.MODERATE
            )
        }
        return choices[random.nextInt(choices.size)]
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

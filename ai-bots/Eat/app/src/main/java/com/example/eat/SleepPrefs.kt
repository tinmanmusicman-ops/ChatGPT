package com.example.eat

import android.content.Context
import java.util.Calendar

object SleepPrefs {
    private const val PREFS_NAME = "EatSleepPrefs"
    private const val KEY_SLEEP_START = "sleep_start_minutes"
    private const val KEY_SLEEP_END = "sleep_end_minutes"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun setSleepWindow(context: Context, startMinutes: Int, endMinutes: Int) {
        prefs(context).edit().putInt(KEY_SLEEP_START, startMinutes.coerceIn(0, 1439)).apply()
        prefs(context).edit().putInt(KEY_SLEEP_END, endMinutes.coerceIn(0, 1439)).apply()
    }

    fun getSleepStartMinutes(context: Context): Int =
        prefs(context).getInt(KEY_SLEEP_START, 0)

    fun getSleepEndMinutes(context: Context): Int =
        prefs(context).getInt(KEY_SLEEP_END, 0)

    fun currentMinutesSinceMidnight(): Int {
        val calendar = Calendar.getInstance()
        return calendar.get(Calendar.HOUR_OF_DAY) * 60 + calendar.get(Calendar.MINUTE)
    }

    fun isSleepWindowActive(context: Context, minutes: Int = currentMinutesSinceMidnight()): Boolean {
        val start = getSleepStartMinutes(context)
        val end = getSleepEndMinutes(context)
        if (start == end) return false
        return if (start < end) {
            minutes in start until end
        } else {
            minutes >= start || minutes < end
        }
    }

    fun minutesUntilWake(context: Context, minutes: Int = currentMinutesSinceMidnight()): Int {
        if (!isSleepWindowActive(context, minutes)) return 0
        val end = getSleepEndMinutes(context)
        val raw = (end - minutes + 1440) % 1440
        return if (raw == 0) 1440 else raw
    }
}

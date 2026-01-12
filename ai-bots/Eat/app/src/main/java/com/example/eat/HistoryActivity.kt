package com.example.eat

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class HistoryActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_history)
        val historyGraph = findViewById<HistoryGraphView>(R.id.historyGraph)
        historyGraph.historyEntries = ReminderPrefs.getTodayHistory(this)
        historyGraph.axisDurationMillis = axisRangeMillis(ReminderPrefs.getInterval(this))
    }

    private fun axisRangeMillis(intervalMinutes: Long): Long {
        val minutes = when (intervalMinutes) {
            1L -> 60L
            15L -> 60L
            30L -> 1440L
            60L -> 1440L
            120L -> 720L
            else -> 1440L
        }
        return minutes * 60_000L
    }
}

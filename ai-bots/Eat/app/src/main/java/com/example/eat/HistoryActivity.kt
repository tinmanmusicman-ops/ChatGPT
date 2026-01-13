package com.example.eat

import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

class HistoryActivity : AppCompatActivity() {
    companion object {
        private const val KEY_SELECTED_DATE = "selected_date"
        private val DATE_FORMAT = DateTimeFormatter.ofPattern("EEE, MMM d")
    }

    private lateinit var historyGraph: HistoryGraphView
    private lateinit var prevDayButton: Button
    private lateinit var nextDayButton: Button
    private lateinit var dateLabel: TextView
    private var selectedDate: LocalDate = LocalDate.now()
    private val zone = ZoneId.systemDefault()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_history)
        selectedDate = savedInstanceState?.getString(KEY_SELECTED_DATE)?.let { LocalDate.parse(it) } ?: LocalDate.now()

        historyGraph = findViewById(R.id.historyGraph)
        historyGraph.axisDurationMillis = axisRangeMillis(ReminderPrefs.getInterval(this))

        prevDayButton = findViewById(R.id.prevDayButton)
        nextDayButton = findViewById(R.id.nextDayButton)
        dateLabel = findViewById(R.id.dateLabel)

        prevDayButton.setOnClickListener {
            selectedDate = selectedDate.minusDays(1)
            refreshGraph()
        }
        nextDayButton.setOnClickListener {
            selectedDate = selectedDate.plusDays(1)
            refreshGraph()
        }

        refreshGraph()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(KEY_SELECTED_DATE, selectedDate.toString())
    }

    private fun refreshGraph() {
        val start = selectedDate.atStartOfDay(zone).toInstant().toEpochMilli()
        val end = selectedDate.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli() - 1
        val entries = ReminderPrefs.getHistoryEntriesBetween(this, start, end)
        historyGraph.windowStartMillis = start
        historyGraph.windowEndMillis = end
        historyGraph.historyEntries = entries
        dateLabel.text = selectedDate.format(DATE_FORMAT)
        nextDayButton.isEnabled = !selectedDate.isEqual(LocalDate.now())
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

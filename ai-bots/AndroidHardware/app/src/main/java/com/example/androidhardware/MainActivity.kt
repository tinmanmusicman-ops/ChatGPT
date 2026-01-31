package com.example.androidhardware

import android.os.Bundle
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.github.mikephil.charting.charts.LineChart
import kotlinx.coroutines.Job

/**
 * Adding future metrics:
 * - Create another monitor (e.g., `BatteryMonitor`) that polls and emits samples.
 * - Register a new series in `ChartManager`, then append samples the same way as memory.
 * - Keep MainActivity focused on lifecycle + wiring monitors to UI.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var usageText: TextView
    private lateinit var chartManager: ChartManager
    private lateinit var memoryMonitor: MemoryMonitor

    private var pollJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        usageText = findViewById(R.id.usageText)
        val chart = findViewById<LineChart>(R.id.lineChart)

        memoryMonitor = MemoryMonitor(applicationContext)
        chartManager = ChartManager(chart)
    }

    override fun onStart() {
        super.onStart()
        startPolling()
    }

    override fun onStop() {
        super.onStop()
        stopPolling()
    }

    private fun startPolling() {
        if (pollJob != null) return

        pollJob = memoryMonitor.start(
            scope = lifecycleScope,
            pollIntervalMs = POLL_INTERVAL_MS,
            onReading = { reading ->
                usageText.text = formatUsageText(reading.usedBytes, reading.totalBytes)
                chartManager.appendUsedMemory(reading.timestampMillis, reading.usedBytes)
            },
            onError = { error ->
                usageText.text = getString(R.string.usage_unavailable)
                Toast.makeText(this@MainActivity, errorMessage(error), Toast.LENGTH_SHORT).show()
                stopPolling()
            }
        )
    }

    private fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    private fun formatUsageText(usedBytes: Long, totalBytes: Long): String {
        val usedGb = usedBytes.toDouble() / BYTES_PER_GB
        val totalGb = totalBytes.toDouble() / BYTES_PER_GB
        return getString(R.string.usage_format_gb, usedGb, totalGb)
    }

    private fun errorMessage(error: MemoryMonitor.Error): String {
        return when (error) {
            MemoryMonitor.Error.ActivityManagerUnavailable -> getString(R.string.error_activity_manager_unavailable)
            is MemoryMonitor.Error.InvalidTotalMem -> getString(R.string.error_invalid_total_mem, error.totalBytes)
        }
    }

    companion object {
        private const val POLL_INTERVAL_MS = 1500L
        private const val BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
    }
}

package com.example.androidhardware

import android.graphics.Color
import com.github.mikephil.charting.charts.LineChart
import com.github.mikephil.charting.components.Description
import com.github.mikephil.charting.components.XAxis
import com.github.mikephil.charting.data.Entry
import com.github.mikephil.charting.data.LineData
import com.github.mikephil.charting.data.LineDataSet
import com.github.mikephil.charting.formatter.ValueFormatter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Owns all chart configuration and updates.
 *
 * Future metrics:
 * - Register another series via `registerSeries(...)`.
 * - Feed it via `appendPoint(seriesId, timestampMillis, yValue)` (or a typed helper like `appendCpuPercent(...)`).
 * - Keep chart styling here so the Activity stays lifecycle-only.
 */
class ChartManager(private val chart: LineChart) {

    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private val startTimestampMillis = System.currentTimeMillis()

    private val lineData = LineData()
    private val dataSetsById = LinkedHashMap<String, LineDataSet>()

    init {
        chart.data = lineData

        chart.setTouchEnabled(true)
        chart.isDragEnabled = true
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        chart.legend.isEnabled = true

        chart.description = Description().apply { text = "" }

        chart.axisRight.isEnabled = false
        chart.axisLeft.apply {
            axisMinimum = 0f
            valueFormatter = object : ValueFormatter() {
                override fun getFormattedValue(value: Float): String = String.format(Locale.getDefault(), "%.1f GB", value)
            }
        }

        chart.xAxis.apply {
            position = XAxis.XAxisPosition.BOTTOM
            setDrawGridLines(false)
            granularity = 5f
            valueFormatter = object : ValueFormatter() {
                override fun getFormattedValue(value: Float): String {
                    val ts = startTimestampMillis + (value * 1000f).toLong()
                    return timeFormat.format(Date(ts))
                }
            }
        }

        registerSeries(
            id = SERIES_USED_MEMORY_GB,
            label = "Used (GB)",
            color = Color.parseColor("#1E88E5")
        )
    }

    fun appendUsedMemory(timestampMillis: Long, usedBytes: Long) {
        val usedGb = usedBytes.toDouble() / BYTES_PER_GB
        appendPoint(SERIES_USED_MEMORY_GB, timestampMillis, usedGb.toFloat())
    }

    fun registerSeries(id: String, label: String, color: Int) {
        if (dataSetsById.containsKey(id)) return

        val dataSet = LineDataSet(mutableListOf(), label).apply {
            lineWidth = 2f
            setDrawCircles(false)
            setDrawValues(false)
            mode = LineDataSet.Mode.LINEAR
            this.color = color
        }

        dataSetsById[id] = dataSet
        lineData.addDataSet(dataSet)
        chart.data?.notifyDataChanged()
        chart.notifyDataSetChanged()
        chart.invalidate()
    }

    fun appendPoint(seriesId: String, timestampMillis: Long, yValue: Float) {
        val dataSet = dataSetsById[seriesId] ?: return
        val secondsFromStart = (timestampMillis - startTimestampMillis).coerceAtLeast(0L) / 1000f
        dataSet.addEntry(Entry(secondsFromStart, yValue))

        chart.data?.notifyDataChanged()
        chart.notifyDataSetChanged()
        chart.moveViewToX(secondsFromStart)
        chart.invalidate()
    }

    companion object {
        private const val BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
        private const val SERIES_USED_MEMORY_GB = "used_memory_gb"
    }
}

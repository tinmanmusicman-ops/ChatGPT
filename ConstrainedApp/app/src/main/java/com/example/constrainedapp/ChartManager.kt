package com.example.constrainedapp

import com.github.mikephil.charting.charts.BarChart
import com.github.mikephil.charting.components.XAxis
import com.github.mikephil.charting.components.YAxis
import com.github.mikephil.charting.data.BarData
import com.github.mikephil.charting.data.BarDataSet
import com.github.mikephil.charting.data.BarEntry
import com.github.mikephil.charting.formatter.IndexAxisValueFormatter
import com.github.mikephil.charting.formatter.ValueFormatter
import kotlin.math.roundToInt
import java.util.Locale

class ChartManager(private val chart: BarChart) {
    private val laneLabels = listOf("RAM", "Swap", "CPU", "Int", "SD", "BATT", "CPU°C", "BAT°C", "AMB°F")
    private val entries = MutableList(laneLabels.size) { index -> BarEntry(index.toFloat(), 0f) }
    private val context = chart.context
    private val memoryColor = context.getColor(R.color.chart_accent1)
    private val swapColor = context.getColor(R.color.chart_swap)
    private val cpuColor = context.getColor(R.color.chart_accent2)
    private val reservedColor = context.getColor(R.color.chart_reserved)
    private val batteryChargingColor = context.getColor(R.color.chart_battery_charging)
    private val batteryDischargingColor = context.getColor(R.color.chart_battery_discharging)
    private val cpuTempColor = context.getColor(R.color.chart_cpu_temp)
    private val batteryTempColor = context.getColor(R.color.chart_battery_temp)
    private val ambientTempColor = context.getColor(R.color.chart_ambient_temp)
    private var lastBatteryCharging: Boolean? = null
    private val dataSet = BarDataSet(entries, "Slot Utilization").apply {
        setColors(buildColors(isBatteryCharging = false))
        valueTextColor = context.getColor(R.color.on_surface)
        valueTextSize = 9f
        valueFormatter = object : ValueFormatter() {
            override fun getBarLabel(barEntry: BarEntry?): String {
                val entry = barEntry ?: return ""
                val lane = entry.x.roundToInt()
                val value = entry.y
                return when (lane) {
                    0 -> ""
                    6 -> String.format("%.0fC", value)
                    7 -> String.format("%.0fC", value)
                    8 -> String.format("%.0fF", value)
                    else -> value.roundToInt().toString()
                }
            }
        }
        axisDependency = YAxis.AxisDependency.LEFT
        setDrawValues(true)
    }

    init {
        chart.description.isEnabled = false
        chart.legend.isEnabled = false
        chart.setDrawGridBackground(false)
        chart.setPinchZoom(false)
        chart.setScaleEnabled(false)
        chart.setFitBars(true)

        chart.axisRight.isEnabled = false
        chart.axisLeft.apply {
            textColor = context.getColor(R.color.on_surface)
            axisMinimum = 0f
            axisMaximum = 100f
            granularity = 10f
        }

        chart.xAxis.apply {
            position = XAxis.XAxisPosition.BOTTOM
            valueFormatter = IndexAxisValueFormatter(laneLabels)
            setDrawGridLines(false)
            granularity = 1f
            isGranularityEnabled = true
            textColor = context.getColor(R.color.on_surface)
            textSize = 10f
            axisMinimum = -0.5f
            axisMaximum = laneLabels.size - 0.5f
            // Don't force label count; forcing it breaks integer alignment and can cause labels to "skip".
            setLabelCount(laneLabels.size, false)
            setAvoidFirstLastClipping(false)
            labelRotationAngle = 0f
        }

        chart.data = BarData(dataSet).apply {
            barWidth = 0.7f
        }
        // Add a bit of headroom so value labels (e.g. 100) don't get clipped at the top.
        chart.setExtraOffsets(0f, 20f, 0f, 0f)
        chart.setBackgroundColor(context.getColor(R.color.surface))
        chart.invalidate()
    }

	private fun buildColors(isBatteryCharging: Boolean): List<Int> {
		return laneLabels.mapIndexed { index, _ ->
			when (index) {
				0 -> memoryColor
				1 -> swapColor
				2 -> cpuColor
				5 -> if (isBatteryCharging) batteryChargingColor else batteryDischargingColor
				6 -> cpuTempColor
				7 -> batteryTempColor
				8 -> ambientTempColor
				else -> reservedColor
			}
		}
	}

    fun updateSlots(
        memoryPercent: Float,
        memoryUsedGb: Float,
        memoryTotalGb: Float,
        swapPercent: Float,
        swapUsedGb: Float,
        swapTotalGb: Float,
        cpuPercent: Float,
        cpuFreqMHz: Float?,
        internalStoragePercent: Float,
        externalStoragePercent: Float,
        internalUsedGb: Float,
        internalTotalGb: Float,
        externalUsedGb: Float,
        batteryPercent: Float,
        batteryIsCharging: Boolean,
        cpuTempValue: Float,
        batteryTempValue: Float,
        ambientTempValue: Float,
    ) {
        entries[0].y = memoryPercent.coerceIn(0f, 100f)
        entries[1].y = swapPercent.coerceIn(0f, 100f)
        entries[2].y = cpuPercent.coerceIn(0f, 100f)
        entries[3].y = internalStoragePercent.coerceIn(0f, 100f)
        entries[4].y = externalStoragePercent.coerceIn(0f, 100f)
        entries[5].y = batteryPercent.coerceIn(0f, 100f)
        entries[6].y = cpuTempValue.coerceIn(0f, 100f)
        entries[7].y = batteryTempValue.coerceIn(0f, 100f)
        entries[8].y = ambientTempValue.coerceIn(0f, 100f)
        if (lastBatteryCharging != batteryIsCharging) {
            lastBatteryCharging = batteryIsCharging
            dataSet.setColors(buildColors(isBatteryCharging = batteryIsCharging))
        }
        updateBarLabel(0, formatGbLabel(memoryUsedGb, memoryTotalGb))
        updateBarLabel(1, formatGbLabel(swapUsedGb, swapTotalGb))
        updateBarLabel(2, formatCpuLabel(cpuPercent, cpuFreqMHz))
        updateBarLabel(3, formatGbLabel(internalUsedGb, internalTotalGb))
        updateBarLabel(4, formatUsedLabel(externalUsedGb))
        updateBarLabel(5, if (batteryIsCharging) "Charging" else "Discharging")
        updateBarLabel(6, formatTempLabel(cpuTempValue, "°C"))
        updateBarLabel(7, formatTempLabel(batteryTempValue, "°C"))
        updateBarLabel(8, formatTempLabel(ambientTempValue, "°F"))
        dataSet.notifyDataSetChanged()
        chart.data?.notifyDataChanged()
        chart.notifyDataSetChanged()
        chart.invalidate()
    }

    private fun updateBarLabel(index: Int, label: String?) {
        (chart as? PerfBarChart)?.setBarLabel(index, label)
    }

    private fun formatGbLabel(usedGb: Float, totalGb: Float): String? {
        return if (totalGb > 0f) {
            String.format(Locale.US, "%.1f/%.1f", usedGb, totalGb)
        } else {
            null
        }
    }

    private fun formatCpuLabel(percent: Float, freqMHz: Float?): String {
        val percentClamped = percent.coerceIn(0f, 100f)
        val freq = freqMHz ?: 0f
        return String.format(Locale.US, "%.0f%%/%.0fMHz", percentClamped, freq)
    }

    private fun formatUsedLabel(usedGb: Float): String {
        return String.format(Locale.US, "%.1fGB", usedGb)
    }

    private fun formatTempLabel(value: Float, suffix: String): String {
        return String.format(Locale.US, "%.1f%s", value, suffix)
    }
}

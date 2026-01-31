package com.example.constrainedapp

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.TextView
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.github.mikephil.charting.charts.BarChart
import java.util.Locale

class MainActivity : Activity() {
    private lateinit var chartManager: ChartManager
    private lateinit var memoryMonitor: MemoryMonitor
    private lateinit var cpuMonitor: CpuMonitor
    private lateinit var storageMonitor: StorageMonitor
    private lateinit var batteryMonitor: BatteryMonitor
    private lateinit var temperatureMonitor: TemperatureMonitor
    private lateinit var ambientMonitor: AmbientWeatherMonitor
    private lateinit var swapMonitor: SwapMonitor
    private lateinit var memoryStatus: TextView
    private lateinit var swapStatus: TextView
    private lateinit var ambientStatus: TextView
    private lateinit var cpuStatus: TextView
    private lateinit var batteryStatus: TextView
    private lateinit var cpuTempStatus: TextView
    private lateinit var batteryTempStatus: TextView
    private lateinit var storageInternalStatus: TextView
    private lateinit var storageExternalStatus: TextView
    private val handler = Handler(Looper.getMainLooper())

    private val updateRunnable = object : Runnable {
        override fun run() {
            val snapshot = memoryMonitor.snapshot()
            val memoryPercent = if (snapshot.totalGb <= 0f) {
                0f
            } else {
                (snapshot.usedGb / snapshot.totalGb) * 100f
            }
            val cpuPercent = (cpuMonitor.usagePercent() * CPU_DISPLAY_SCALE).coerceIn(0f, 100f)
            val cpuFreqMHz = cpuMonitor.currentMaxFreqMHz()
            val storageSnapshot = storageMonitor.snapshot()
            val batterySnapshot = batteryMonitor.snapshot()
            val tempSnapshot = temperatureMonitor.snapshot()
            val cpuTempValue = tempSnapshot.cpuCelsius ?: 0f
            val batteryTempValue = tempSnapshot.batteryCelsius ?: 0f
            val ambientTempF = ambientMonitor.latestAmbientF()
            val ambientTempForChart = ambientTempF ?: 0f
            val swapSnapshot = swapMonitor.snapshot()
            chartManager.updateSlots(
                memoryPercent,
                snapshot.usedGb,
                snapshot.totalGb,
                swapSnapshot?.percentUsed ?: 0f,
                swapSnapshot?.usedGb ?: 0f,
                swapSnapshot?.totalGb ?: 0f,
                cpuPercent,
                cpuFreqMHz,
                storageSnapshot.internal.percent,
                storageSnapshot.external.percent,
                bytesToGb(storageSnapshot.internal.usedBytes),
                bytesToGb(storageSnapshot.internal.totalBytes),
                bytesToGb(storageSnapshot.external.usedBytes),
                batterySnapshot.chargePercent,
                batterySnapshot.isCharging,
                cpuTempValue,
                batteryTempValue,
                ambientTempForChart,
            )
            val swapText = swapSnapshot?.let {
                val usedGb = it.usedBytes / 1024.0 / 1024.0 / 1024.0
                val totalGb = it.totalBytes / 1024.0 / 1024.0 / 1024.0
                val percent = it.percentUsed ?: 0f
                String.format(Locale.US, "Swap %.2f/%.2f GB (%.0f%%)", usedGb, totalGb, percent)
            } ?: "Swap: n/a"
            val ambientText = ambientTempF?.let {
                String.format(Locale.US, "Ambient %.1f°F", it)
            } ?: "Ambient temp: (needs location)"
            memoryStatus.text = String.format(Locale.US, "Mem Used %.1f / %.1f GB", snapshot.usedGb, snapshot.totalGb)
            swapStatus.text = swapText
            ambientStatus.text = ambientText
            cpuStatus.text = cpuFreqMHz?.let {
                String.format(Locale.US, getString(R.string.cpu_status_with_freq_format), cpuPercent, it)
            } ?: String.format(Locale.US, getString(R.string.cpu_status_format), cpuPercent)
            batteryStatus.text = if (batterySnapshot.isCharging) {
                String.format(Locale.US, "BATT %.0f%% (chg)", batterySnapshot.chargePercent)
            } else {
                String.format(Locale.US, "BATT %.0f%%", batterySnapshot.chargePercent)
            }
            batteryStatus.setTextColor(
                getColor(
                    if (batterySnapshot.isCharging) {
                        R.color.chart_battery_charging
                    } else {
                        R.color.chart_battery_discharging
                    }
                )
            )
            cpuTempStatus.text = tempSnapshot.cpuCelsius?.let {
                String.format(Locale.US, "CPU Temp %.1f°C", it)
            } ?: "CPU Temp: n/a"
            batteryTempStatus.text = tempSnapshot.batteryCelsius?.let {
                String.format(Locale.US, "Batt Temp %.1f°C", it)
            } ?: "Batt Temp: n/a"
            storageInternalStatus.text = formatStorageText("Internal", storageSnapshot.internal, StorageUnit.GB)
            storageExternalStatus.text = formatStorageText("SD", storageSnapshot.external, StorageUnit.GB)
            handler.postDelayed(this, 1_000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        memoryStatus = findViewById(R.id.memoryStatus)
        swapStatus = findViewById(R.id.swapStatus)
        ambientStatus = findViewById(R.id.ambientStatus)
        cpuStatus = findViewById(R.id.cpuStatus)
        batteryStatus = findViewById(R.id.batteryStatus)
        cpuTempStatus = findViewById(R.id.cpuTempStatus)
        batteryTempStatus = findViewById(R.id.batteryTempStatus)
        val chart = findViewById<BarChart>(R.id.memoryChart)
        chartManager = ChartManager(chart)
        memoryMonitor = MemoryMonitor(this)
        cpuMonitor = CpuMonitor()
        storageMonitor = StorageMonitor(this)
        batteryMonitor = BatteryMonitor(this)
        temperatureMonitor = TemperatureMonitor(this)
        ambientMonitor = AmbientWeatherMonitor(this)
        storageInternalStatus = findViewById(R.id.storageInternalStatus)
        storageExternalStatus = findViewById(R.id.storageExternalStatus)
        swapMonitor = SwapMonitor()
    }

    override fun onResume() {
        super.onResume()
        handler.post(updateRunnable)
        ensureAmbientWeatherPermissionAndStart()
    }

    override fun onPause() {
        ambientMonitor.stop()
        handler.removeCallbacks(updateRunnable)
        super.onPause()
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == LOCATION_PERMISSION_REQUEST_CODE) {
            val anyGranted = grantResults.any { it == PackageManager.PERMISSION_GRANTED }
            if (anyGranted) {
                ambientMonitor.start()
            } else {
                ambientMonitor.stop()
            }
        }
    }

    private fun ensureAmbientWeatherPermissionAndStart() {
        if (hasAnyLocationPermission()) {
            ambientMonitor.start()
        } else {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ),
                LOCATION_PERMISSION_REQUEST_CODE,
            )
        }
    }

    private fun hasAnyLocationPermission(): Boolean {
        val hasFine = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        return hasFine || hasCoarse
    }

    private fun formatStorageText(label: String, stats: StorageMonitor.StorageStats, unit: StorageUnit): String {
        val used = stats.usedBytes.toDouble() / unit.divisor
        val total = stats.totalBytes.toDouble() / unit.divisor
        return String.format(Locale.US, getString(R.string.storage_format), label, used, total, unit.suffix)
    }

    private enum class StorageUnit(val divisor: Double, val suffix: String) {
        GB(BYTES_PER_GB, "GB"),
        MB(BYTES_PER_MB, "MB")
    }

    private fun bytesToGb(bytes: Long): Float = (bytes / BYTES_PER_GB).toFloat()

    companion object {
        private const val BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
        private const val BYTES_PER_MB = 1024.0 * 1024.0
        private const val LOCATION_PERMISSION_REQUEST_CODE = 1001
        private const val CPU_DISPLAY_SCALE = 0.6f
    }
}

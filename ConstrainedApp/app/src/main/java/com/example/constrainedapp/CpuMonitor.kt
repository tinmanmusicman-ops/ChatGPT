package com.example.constrainedapp

import android.os.Process
import android.os.SystemClock
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.io.IOException

class CpuMonitor {
    private val timeInStateFiles: List<File> = findTimeInStateFiles()
    private val processMonitor = ProcessCpuMonitor()
    private var lastDeviceSnapshot: DeviceSnapshot? = null
    private var lastProcSnapshot: ProcSnapshot? = null
    private var lastPerCoreUsage: List<Float> = emptyList()

    fun usagePercent(): Float {
        deviceBusyUsage()?.let { return it }
        deviceFreqUsage()?.let { return it }
        lastPerCoreUsage = emptyList()
        return processMonitor.usagePercent()
    }

    fun currentMaxFreqMHz(): Float? {
        val base = File("/sys/devices/system/cpu")
        val cpuDirs = base.listFiles { file ->
            file.isDirectory && file.name.matches(Regex("cpu[0-9]+"))
        } ?: return null

        var maxKHz = 0L
        for (dir in cpuDirs) {
            val scaling = File(dir, "cpufreq/scaling_cur_freq")
            val cpuInfo = File(dir, "cpufreq/cpuinfo_cur_freq")
            val kHz = readLongFile(scaling) ?: readLongFile(cpuInfo) ?: continue
            if (kHz > maxKHz) maxKHz = kHz
        }
        if (maxKHz <= 0L) return null
        return (maxKHz / 1000f)
    }

    private fun deviceBusyUsage(): Float? {
        val snapshot = readProcSnapshot() ?: return null
        val previous = lastProcSnapshot
        lastProcSnapshot = snapshot
        if (previous == null) return null

        val overall = computeDeltaPercent(snapshot.overall, previous.overall) ?: return null
        lastPerCoreUsage = (0 until CORE_BARS).map { index ->
            val current = snapshot.perCore.getOrNull(index) ?: return@map 0f
            val prior = previous.perCore.getOrNull(index) ?: return@map 0f
            (computeDeltaPercent(current, prior) ?: 0.0).toFloat()
        }
        return overall.toFloat()
    }

    private fun deviceFreqUsage(): Float? {
        if (timeInStateFiles.isEmpty()) return null
        val snapshot = readDeviceSnapshot() ?: return null
        val nowMs = SystemClock.elapsedRealtime()
        val previous = lastDeviceSnapshot
        lastDeviceSnapshot = snapshot.copy(timestampMs = nowMs)
        if (previous == null) {
            lastPerCoreUsage = emptyList()
            return null
        }
        val deltaMs = nowMs - previous.timestampMs
        if (deltaMs <= 0L) return null

        val perCore = computePerCoreFreqUsage(snapshot.coreFreqTimes, previous.coreFreqTimes)
        lastPerCoreUsage = perCore.take(CORE_BARS)
        if (perCore.isEmpty()) return null
        return perCore.take(CORE_BARS).average().toFloat()
    }

    private data class CpuTimes(
        val total: Long,
        val idle: Long,
    )

    private data class ProcSnapshot(
        val overall: CpuTimes,
        val perCore: List<CpuTimes>,
    )

    private fun readProcSnapshot(): ProcSnapshot? {
        val file = File("/proc/stat")
        return try {
            BufferedReader(FileReader(file)).use { reader ->
                var line: String?
                var overall: CpuTimes? = null
                val perCore = mutableListOf<CpuTimes>()
                while (reader.readLine().also { line = it } != null) {
                    val trimmed = line!!.trim()
                    if (!trimmed.startsWith("cpu")) break
                    val parts = trimmed.split(Regex("\\s+"))
                    if (parts.isEmpty()) continue
                    val label = parts[0]
                    val times = parseCpuTimes(parts) ?: continue
                    if (label == "cpu") {
                        overall = times
                    } else if (label.startsWith("cpu") && label.length > 3 && label.substring(3).all { it.isDigit() }) {
                        perCore.add(times)
                    }
                }
                val overallTimes = overall ?: return null
                ProcSnapshot(overallTimes, perCore)
            }
        } catch (_: IOException) {
            null
        } catch (_: SecurityException) {
            null
        }
    }

    private fun parseCpuTimes(parts: List<String>): CpuTimes? {
        if (parts.size < 5) return null
        var total = 0L
        var idle = 0L
        for (index in 1 until parts.size) {
            val value = parts[index].toLongOrNull() ?: continue
            total += value
            if (index == 4) idle += value // idle
            if (index == 5) idle += value // iowait
        }
        if (total <= 0L) return null
        return CpuTimes(total = total, idle = idle)
    }

    private fun computeDeltaPercent(current: CpuTimes, previous: CpuTimes): Double? {
        val totalDelta = (current.total - previous.total).coerceAtLeast(0L)
        val idleDelta = (current.idle - previous.idle).coerceAtLeast(0L)
        if (totalDelta <= 0L) return null
        val busy = (totalDelta - idleDelta).coerceAtLeast(0L)
        return (busy.toDouble() / totalDelta.toDouble() * 100.0).coerceIn(0.0, 100.0)
    }

    private fun readDeviceSnapshot(): DeviceSnapshot? {
        val perCore = mutableListOf<Map<Long, Long>>()
        for (file in timeInStateFiles) {
            val times = readTimeInStateByFreq(file) ?: return null
            perCore.add(times)
        }
        return DeviceSnapshot(coreFreqTimes = perCore)
    }

    private fun readTimeInStateByFreq(file: File): Map<Long, Long>? {
        return try {
            BufferedReader(FileReader(file)).use { reader ->
                var line: String?
                val map = LinkedHashMap<Long, Long>()
                while (reader.readLine().also { line = it } != null) {
                    val parts = line!!.trim().split("\\s+".toRegex())
                    if (parts.size < 2) continue
                    val freqKHz = parts[0].toLongOrNull() ?: continue
                    val time = parts[1].toLongOrNull() ?: continue
                    map[freqKHz] = time
                }
                map
            }
        } catch (io: IOException) {
            null
        }
    }

    private fun findTimeInStateFiles(): List<File> {
        val base = File("/sys/devices/system/cpu")
        val cpuDirs = base.listFiles { file ->
            file.isDirectory && file.name.matches(Regex("cpu[0-9]+"))
        } ?: emptyArray()
        return cpuDirs.mapNotNull { dir ->
            val candidate = File(dir, "cpufreq/stats/time_in_state")
            if (candidate.canRead()) candidate else null
        }
    }

    private fun readLongFile(file: File): Long? {
        if (!file.canRead()) return null
        return try {
            val text = file.readText().trim()
            text.toLongOrNull()
        } catch (_: Exception) {
            null
        }
    }

    private data class DeviceSnapshot(
        val coreFreqTimes: List<Map<Long, Long>>,
        val timestampMs: Long = 0L,
    )

    private fun computePerCoreFreqUsage(
        current: List<Map<Long, Long>>,
        previous: List<Map<Long, Long>>,
    ): List<Float> {
        val usageList = mutableListOf<Float>()
        for (i in current.indices) {
            val cur = current[i]
            val prev = previous.getOrElse(i) { emptyMap() }
            if (cur.isEmpty()) {
                usageList.add(0f)
                continue
            }
            var deltaTotal = 0L
            var weightedFreq = 0.0
            var maxFreq = 0L
            for ((freq, curTime) in cur) {
                val prevTime = prev[freq] ?: 0L
                val delta = (curTime - prevTime).coerceAtLeast(0L)
                deltaTotal += delta
                weightedFreq += freq.toDouble() * delta.toDouble()
                if (freq > maxFreq) maxFreq = freq
            }
            if (deltaTotal <= 0L || maxFreq <= 0L) {
                usageList.add(0f)
                continue
            }
            val avgFreq = weightedFreq / deltaTotal.toDouble()
            val percent = (avgFreq / maxFreq.toDouble()) * 100.0
            usageList.add(percent.coerceIn(0.0, 100.0).toFloat())
        }
        return usageList
    }

    fun latestPerCoreUsage(): List<Float> = lastPerCoreUsage

    private inner class ProcessCpuMonitor {
        private val coreCount = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
        private var lastCpuTime = Process.getElapsedCpuTime()
        private var lastRealtime = SystemClock.elapsedRealtime()

        fun usagePercent(): Float {
            val currentCpu = Process.getElapsedCpuTime()
            val currentRealtime = SystemClock.elapsedRealtime()
            val deltaCpu = currentCpu - lastCpuTime
            val deltaRealtime = currentRealtime - lastRealtime
            lastCpuTime = currentCpu
            lastRealtime = currentRealtime
            if (deltaRealtime <= 0L) return 0f
            val usage = deltaCpu.toDouble() / (deltaRealtime * coreCount) * 100.0
            return usage.coerceIn(0.0, 100.0).toFloat()
        }
    }

    companion object {
        private const val CORE_BARS = 4
    }
}

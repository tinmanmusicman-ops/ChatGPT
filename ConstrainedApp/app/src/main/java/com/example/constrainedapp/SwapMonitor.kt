package com.example.constrainedapp

import java.io.BufferedReader
import java.io.File
import java.io.FileReader

class SwapMonitor {
    data class Snapshot(val totalBytes: Long, val freeBytes: Long) {
        val usedBytes: Long get() = (totalBytes - freeBytes).coerceAtLeast(0L)
        val percentUsed: Float?
            get() = if (totalBytes <= 0L) null else (usedBytes / totalBytes.toDouble() * 100.0).toFloat()
        val usedGb: Float get() = (usedBytes / BYTES_PER_GB).toFloat()
        val totalGb: Float get() = (totalBytes / BYTES_PER_GB).toFloat()
    }

    fun snapshot(): Snapshot? {
        val meminfo = File("/proc/meminfo")
        if (!meminfo.exists() || !meminfo.canRead()) {
            return null
        }

        var total: Long? = null
        var free: Long? = null
        BufferedReader(FileReader(meminfo)).use { reader ->
            reader.lineSequence().forEach { line ->
                when {
                    line.startsWith("SwapTotal:", ignoreCase = true) -> {
                        total = extractKilobytes(line)
                    }
                    line.startsWith("SwapFree:", ignoreCase = true) -> {
                        free = extractKilobytes(line)
                    }
                }
                if (total != null && free != null) {
                    return@use
                }
            }
        }

        val totalBytes = total ?: return null
        val freeBytes = free ?: return null
        return Snapshot(totalBytes = totalBytes * 1024L, freeBytes = freeBytes * 1024L)
    }

    private fun extractKilobytes(line: String): Long? {
        return line.split(Regex("\\s+")).getOrNull(1)?.toLongOrNull()
    }

    companion object {
        private const val BYTES_PER_GB = 1024.0 * 1024.0 * 1024.0
    }
}

package com.example.constrainedapp

import android.content.Context
import android.os.Environment
import android.os.StatFs
import android.util.Log
import java.io.File

class StorageMonitor(private val context: Context) {
    data class StorageStats(val usedBytes: Long, val totalBytes: Long, val percent: Float)
    data class Snapshot(val internal: StorageStats, val external: StorageStats)

    fun snapshot(): Snapshot {
        return Snapshot(
            internal = usageFor(context.filesDir),
            external = removableExternal()
        )
    }

    private fun removableExternal(): StorageStats {
        val externalDirs = context.getExternalFilesDirs(null)
        for (dir in externalDirs) {
            if (dir?.let { Environment.isExternalStorageRemovable(it) } == true) {
                return usageFor(dir)
            }
        }
        return StorageStats(0L, 0L, 0f)
    }

    private fun usageFor(dir: File?): StorageStats {
        if (dir == null) return StorageStats(0L, 0L, 0f)
        return try {
            val stat = StatFs(dir.absolutePath)
            val total = stat.totalBytes
            if (total <= 0L) return StorageStats(0L, 0L, 0f)
            val available = stat.availableBytes
            val used = (total - available).coerceAtLeast(0L)
            val percent = ((used.toDouble() / total) * 100.0).coerceIn(0.0, 100.0).toFloat()
            StorageStats(used, total, percent)
        } catch (illegal: IllegalArgumentException) {
            Log.w(TAG, "Unable to read storage stats for ${dir.path}", illegal)
            StorageStats(0L, 0L, 0f)
        }
    }

    companion object {
        private const val TAG = "StorageMonitor"
    }
}

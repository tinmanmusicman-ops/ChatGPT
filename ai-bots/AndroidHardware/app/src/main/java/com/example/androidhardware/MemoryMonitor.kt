package com.example.androidhardware

import android.app.ActivityManager
import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Future metrics:
 * - Add a new `XxxMonitor` that produces `SamplePoint`s (timestamp + value).
 * - Add a new dataset in `ChartManager` and route the new samples to it.
 * - Keep each monitor focused on *reading* only; keep chart logic in `ChartManager`.
 */
class MemoryMonitor(context: Context) {

    sealed interface Error {
        data object ActivityManagerUnavailable : Error
        data class InvalidTotalMem(val totalBytes: Long) : Error
    }

    data class MemoryReading(
        val timestampMillis: Long,
        val totalBytes: Long,
        val availableBytes: Long
    ) {
        val usedBytes: Long get() = (totalBytes - availableBytes).coerceAtLeast(0L)
    }

    private val activityManager: ActivityManager? = context.getSystemService(ActivityManager::class.java)

    private sealed interface ReadResult {
        data class Success(val reading: MemoryReading) : ReadResult
        data class Failure(val error: Error) : ReadResult
    }

    fun readNow(): MemoryReading? = (readResult() as? ReadResult.Success)?.reading

    private fun readResult(): ReadResult {
        val am = activityManager ?: return ReadResult.Failure(Error.ActivityManagerUnavailable)

        val info = ActivityManager.MemoryInfo()
        am.getMemoryInfo(info)
        if (info.totalMem <= 0L) {
            return ReadResult.Failure(Error.InvalidTotalMem(totalBytes = info.totalMem))
        }

        return ReadResult.Success(
            MemoryReading(
                timestampMillis = System.currentTimeMillis(),
                totalBytes = info.totalMem,
                availableBytes = info.availMem
            )
        )
    }

    fun start(
        scope: CoroutineScope,
        pollIntervalMs: Long,
        onReading: (MemoryReading) -> Unit,
        onError: (Error) -> Unit
    ): Job {
        return scope.launch(Dispatchers.Default) {
            while (isActive) {
                when (val result = readResult()) {
                    is ReadResult.Success -> withContext(Dispatchers.Main) { onReading(result.reading) }
                    is ReadResult.Failure -> {
                        withContext(Dispatchers.Main) { onError(result.error) }
                        return@launch
                    }
                }
                delay(pollIntervalMs)
            }
        }
    }
}

package com.example.eat

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import javax.mail.MessagingException

class YahooForwarderWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val timestamp = System.currentTimeMillis()
        val settings = YahooForwarderStorage.loadSettings(applicationContext)
        if (!settings.isValid) {
            val message = "Yahoo forwarder credentials incomplete; skipping run"
            Log.i(TAG, message)
            YahooForwarderStorage.updateLastStatus(applicationContext, timestamp, message)
            YahooForwarderScheduler.scheduleNext(applicationContext)
            return Result.success()
        }

        if (SleepPrefs.isSleepWindowActive(applicationContext)) {
            val message = "Sleep window active; skipping Yahoo forwarder"
            Log.i(TAG, message)
            YahooForwarderStorage.updateLastStatus(applicationContext, timestamp, message)
            YahooForwarderScheduler.scheduleNext(applicationContext)
            return Result.success()
        }

        if (!hasNetworkAccess()) {
            val message = "Network unavailable; will retry"
            Log.i(TAG, message)
            YahooForwarderStorage.updateLastStatus(applicationContext, timestamp, message)
            return Result.retry()
        }

        YahooForwarderStorage.clearWorkLog(applicationContext)
        YahooForwarderStorage.appendWorkLog(applicationContext, "Job started")
        return try {
            val filterSettings = YahooForwarderStorage.loadFilterSettings(applicationContext)
            val engineResult = withContext(Dispatchers.IO) {
                YahooForwarderEngine.forwardUnseen(applicationContext, settings, filterSettings)
            }
            YahooForwarderStorage.updateLastStatus(
                applicationContext,
                timestamp,
                engineResult.resultMessage
            )
            YahooForwarderScheduler.scheduleNext(applicationContext)
            Result.success()
        } catch (ex: IOException) {
            val statusMessage = "I/O error: ${ex.localizedMessage}"
            Log.w(TAG, "I/O failure during Yahoo forwarding", ex)
            YahooForwarderStorage.appendWorkLog(applicationContext, statusMessage)
            YahooForwarderStorage.updateLastStatus(
                applicationContext,
                timestamp,
                statusMessage
            )
            Result.retry()
        } catch (ex: MessagingException) {
            val statusMessage = "SMTP/IMAP error: ${ex.localizedMessage}"
            Log.w(TAG, "Email protocol error during Yahoo forwarding", ex)
            YahooForwarderStorage.appendWorkLog(applicationContext, statusMessage)
            YahooForwarderStorage.updateLastStatus(
                applicationContext,
                timestamp,
                statusMessage
            )
            Result.retry()
        } catch (ex: Exception) {
            val statusMessage = "Unexpected error: ${ex.localizedMessage}"
            Log.w(TAG, "Unexpected error during Yahoo forwarding", ex)
            YahooForwarderStorage.appendWorkLog(applicationContext, statusMessage)
            YahooForwarderStorage.updateLastStatus(
                applicationContext,
                timestamp,
                statusMessage
            )
            Result.retry()
        }
    }

    private suspend fun hasNetworkAccess(): Boolean = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("https://clients3.google.com/generate_204")
            .head()
            .build()
        return@withContext try {
            okHttpClient.newCall(request).execute().use { it.isSuccessful }
        } catch (ex: IOException) {
            Log.w(TAG, "Network pre-flight check failed", ex)
            false
        }
    }

    companion object {
        private const val TAG = "YahooForwarderWorker"
        private val okHttpClient = OkHttpClient()
    }
}

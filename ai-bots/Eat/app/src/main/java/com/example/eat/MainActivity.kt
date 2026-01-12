package com.example.eat

import android.content.Context
import android.os.Bundle
import android.widget.Button
import android.widget.RadioGroup
import androidx.appcompat.app.AppCompatActivity
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private lateinit var intervalGroup: RadioGroup
    private val prefs by lazy {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        intervalGroup = findViewById(R.id.intervalGroup)
        val startButton = findViewById<Button>(R.id.startButton)
        val stopButton = findViewById<Button>(R.id.stopButton)

        startButton.setOnClickListener { scheduleReminderWorker() }
        stopButton.setOnClickListener { cancelReminderWorker() }
    }

    private fun scheduleReminderWorker() {
        val intervalMinutes = selectedIntervalMinutes()
        prefs.edit().putLong(PREF_INTERVAL_KEY, intervalMinutes).apply()

        val request = OneTimeWorkRequestBuilder<EatWorker>()
            .setInitialDelay(intervalMinutes, TimeUnit.MINUTES)
            .build()

        val workManager = WorkManager.getInstance(applicationContext)
        workManager.cancelUniqueWork(EatWorker.WORK_NAME)
        workManager.enqueueUniqueWork(
            EatWorker.WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request
        )
    }

    private fun cancelReminderWorker() {
        WorkManager.getInstance(applicationContext).cancelUniqueWork(EatWorker.WORK_NAME)
    }

    private fun selectedIntervalMinutes(): Long {
        return when (intervalGroup.checkedRadioButtonId) {
            R.id.interval1 -> 1L
            R.id.interval15 -> 15L
            R.id.interval30 -> 30L
            R.id.interval60 -> 60L
            R.id.interval120 -> 120L
            else -> 15L
        }
    }

}

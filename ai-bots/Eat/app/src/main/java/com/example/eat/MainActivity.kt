package com.example.eat

import android.os.Bundle
import android.widget.Button
import android.widget.RadioGroup
import androidx.appcompat.app.AppCompatActivity
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private lateinit var intervalGroup: RadioGroup

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
        val request = PeriodicWorkRequestBuilder<EatWorker>(intervalMinutes, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(applicationContext).enqueueUniquePeriodicWork(
            EatWorker.WORK_NAME,
            ExistingPeriodicWorkPolicy.REPLACE,
            request
        )
    }

    private fun cancelReminderWorker() {
        WorkManager.getInstance(applicationContext).cancelUniqueWork(EatWorker.WORK_NAME)
    }

    private fun selectedIntervalMinutes(): Long {
        return when (intervalGroup.checkedRadioButtonId) {
            R.id.interval15 -> 15L
            R.id.interval30 -> 30L
            R.id.interval60 -> 60L
            R.id.interval120 -> 120L
            else -> 15L
        }
    }
}

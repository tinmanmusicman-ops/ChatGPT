package com.example.eat

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.RadioGroup
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import androidx.work.WorkManager
import java.text.DateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private lateinit var intervalGroup: RadioGroup

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        ReminderPrefs.ensureHistorySeeded(this)

        intervalGroup = findViewById(R.id.intervalGroup)
        val startButton = findViewById<Button>(R.id.startButton)
        val stopButton = findViewById<Button>(R.id.stopButton)

        startButton.setOnClickListener { scheduleReminderWorker() }
        stopButton.setOnClickListener { cancelReminderWorker() }
    }

    private fun scheduleReminderWorker() {
        val intervalMinutes = selectedIntervalMinutes()
        ReminderPrefs.setInterval(applicationContext, intervalMinutes)
        ReminderPrefs.setEnabled(applicationContext, true)

        ReminderScheduler.schedule(applicationContext, intervalMinutes)
        showNextReminderToast(intervalMinutes)
    }

    private fun cancelReminderWorker() {
        ReminderPrefs.setEnabled(applicationContext, false)
        WorkManager.getInstance(applicationContext).cancelUniqueWork(EatWorker.WORK_NAME)
        NotificationManagerCompat.from(this).cancel(EatWorker.NOTIFICATION_ID)
        ReminderPrefs.resetActionState(applicationContext)
        showStopToast()
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

    private fun showNextReminderToast(intervalMinutes: Long) {
        val nextTime = Date(System.currentTimeMillis() + intervalMinutes * 60_000)
        val timeText = DateFormat.getTimeInstance(DateFormat.SHORT, Locale.getDefault())
            .format(nextTime)
        val message = "Next reminder in $intervalMinutes minute${if (intervalMinutes == 1L) "" else "s"} ($timeText)"
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    private fun showStopToast() {
        Toast.makeText(this, "Eat reminders paused", Toast.LENGTH_LONG).show()
    }

    override fun onCreateOptionsMenu(menu: android.view.Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: android.view.MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_history -> {
                val intent = Intent(this, HistoryActivity::class.java)
                intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                startActivity(intent)
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }
}

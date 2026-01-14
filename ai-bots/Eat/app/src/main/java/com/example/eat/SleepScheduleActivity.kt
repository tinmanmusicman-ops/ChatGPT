package com.example.eat

import android.os.Bundle
import android.view.MenuItem
import android.widget.Button
import android.widget.TimePicker
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class SleepScheduleActivity : AppCompatActivity() {
    private lateinit var bedtimePicker: TimePicker
    private lateinit var wakePicker: TimePicker

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_sleep_schedule)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = getString(R.string.sleep_schedule_title)

        bedtimePicker = findViewById(R.id.bedtimePicker)
        wakePicker = findViewById(R.id.wakePicker)
        bedtimePicker.setIs24HourView(true)
        wakePicker.setIs24HourView(true)
        val saveButton = findViewById<Button>(R.id.saveSleepScheduleButton)

        val startMinutes = SleepPrefs.getSleepStartMinutes(this)
        bedtimePicker.hour = startMinutes / 60
        bedtimePicker.minute = startMinutes % 60

        val endMinutes = SleepPrefs.getSleepEndMinutes(this)
        wakePicker.hour = endMinutes / 60
        wakePicker.minute = endMinutes % 60

        saveButton.setOnClickListener {
            val bedtimeMinutes = bedtimePicker.hour * 60 + bedtimePicker.minute
            val wakeMinutes = wakePicker.hour * 60 + wakePicker.minute
            SleepPrefs.setSleepWindow(this, bedtimeMinutes, wakeMinutes)
            Toast.makeText(this, getString(R.string.sleep_schedule_saved), Toast.LENGTH_SHORT).show()
            finish()
        }
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        return super.onOptionsItemSelected(item)
    }
}

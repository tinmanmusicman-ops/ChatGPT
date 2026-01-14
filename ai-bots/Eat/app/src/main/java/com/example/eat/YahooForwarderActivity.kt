package com.example.eat

import android.os.Bundle
import android.util.Log
import android.view.MenuItem
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import com.google.android.material.textfield.TextInputEditText
import java.text.DateFormat
import java.util.Date
import java.util.Locale

class YahooForwarderActivity : AppCompatActivity() {
    private lateinit var settingsContainer: LinearLayout
    private lateinit var editSettingsButton: MaterialButton
    private lateinit var logCard: MaterialCardView
    private lateinit var logText: TextView
    private lateinit var runButton: MaterialButton
    private lateinit var emailInput: TextInputEditText
    private lateinit var passwordInput: TextInputEditText
    private lateinit var imapInput: TextInputEditText
    private lateinit var smtpInput: TextInputEditText
    private lateinit var forwardToInput: TextInputEditText
    private lateinit var forwardAllCheckbox: MaterialCheckBox
    private lateinit var domainInput: TextInputEditText
    private lateinit var addDomainButton: MaterialButton
    private lateinit var domainChipGroup: ChipGroup
    private lateinit var statusText: TextView
    private var isCollapsedState = false
    private var logEntriesPresent = false
    private var forceShowLog = false
    private val TAG = "YahooForwarderActivity"
    private val allowedDomains = mutableListOf<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_yahoo_forwarder)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = getString(R.string.yahoo_forwarder_title)
        try {
            settingsContainer = findViewById<LinearLayout>(R.id.settingsContainer)
            editSettingsButton = findViewById<MaterialButton>(R.id.editSettingsButton)
            logCard = findViewById<MaterialCardView>(R.id.logCard)
            logText = findViewById<TextView>(R.id.logText)
            logState("Starting Yahoo Forwarder log")
            runButton = findViewById(R.id.runButton)
            emailInput = findViewById<TextInputEditText>(R.id.yahooEmailInput)
            passwordInput = findViewById<TextInputEditText>(R.id.yahooPasswordInput)
            imapInput = findViewById<TextInputEditText>(R.id.imapServerInput)
            smtpInput = findViewById<TextInputEditText>(R.id.smtpServerInput)
            forwardToInput = findViewById<TextInputEditText>(R.id.forwardToInput)
            forwardAllCheckbox = findViewById(R.id.forwardAllCheckbox)
            domainInput = findViewById(R.id.domainInput)
            addDomainButton = findViewById(R.id.addDomainButton)
            domainChipGroup = findViewById(R.id.domainChipGroup)
            statusText = findViewById<TextView>(R.id.statusText)
            editSettingsButton.setOnClickListener { showSettings() }

            findViewById<MaterialButton>(R.id.saveButton).setOnClickListener { onSaveClicked() }
            findViewById<MaterialButton>(R.id.testButton).setOnClickListener { onTestClicked() }
            runButton.setOnClickListener { runForwarder("Yahoo forwarder run queued") }

            loadSettings()
            loadFilterSettings()
            wireFilterUi()
            val shouldCollapse = YahooForwarderStorage.hasSavedSettings(this)
            setCollapsed(shouldCollapse)
            logState("onCreate - collapsed=$shouldCollapse")
            refreshStatus()
            logState("UI log heartbeat")
        } catch (tp: Throwable) {
            forceShowLog = true
            logState("onCreate error: ${tp.message ?: tp::class.java.simpleName}")
            Toast.makeText(this, "Unable to open Yahoo forwarder", Toast.LENGTH_LONG).show()
            setCollapsed(true)
            refreshStatus()
        }
    }

    private fun loadSettings() {
        val settings = YahooForwarderStorage.loadSettings(this)
        emailInput.setText(settings.yahooEmail)
        passwordInput.setText(settings.yahooAppPassword)
        imapInput.setText(settings.imapServer)
        smtpInput.setText(settings.smtpServer)
        forwardToInput.setText(settings.forwardTo)
    }

    private fun loadFilterSettings() {
        val filterSettings = YahooForwarderStorage.loadFilterSettings(this)
        forwardAllCheckbox.isChecked = filterSettings.forwardAll
        allowedDomains.clear()
        allowedDomains.addAll(filterSettings.allowedDomains)
        renderAllowedDomains()
        logState("Forward mode: ${if (filterSettings.forwardAll) "ALL" else "SELECTED"}")
        logState("Allowed domains loaded: ${filterSettings.allowedDomains.size}")
    }

    private fun wireFilterUi() {
        forwardAllCheckbox.setOnCheckedChangeListener { _, _ ->
            persistFilterSettings()
        }
        addDomainButton.setOnClickListener { addDomainFromInput() }
    }

    private fun addDomainFromInput() {
        val raw = domainInput.text?.toString()?.trim().orEmpty()
        if (raw.isBlank()) return

        val normalized = normalizeDomain(raw)
        if (normalized.isBlank()) return
        if (allowedDomains.contains(normalized)) return

        allowedDomains.add(normalized)
        domainInput.setText("")
        renderAllowedDomains()
        persistFilterSettings()
    }

    private fun normalizeDomain(input: String): String {
        val trimmed = input.trim().lowercase(Locale.ROOT)
        val candidate = if (trimmed.contains("@")) trimmed.substringAfter("@") else trimmed
        val cleaned = candidate.trim().trimEnd('.')
        if (cleaned.isBlank()) return ""
        if (cleaned.contains(" ")) return ""
        return cleaned
    }

    private fun renderAllowedDomains() {
        domainChipGroup.removeAllViews()
        allowedDomains.forEach { domain ->
            val chip = Chip(this).apply {
                text = domain
                isCloseIconVisible = true
                setOnCloseIconClickListener {
                    allowedDomains.remove(domain)
                    renderAllowedDomains()
                    persistFilterSettings()
                }
            }
            domainChipGroup.addView(chip)
        }
    }

    private fun persistFilterSettings() {
        YahooForwarderStorage.saveFilterSettings(
            this,
            YahooForwarderStorage.FilterSettings(
                forwardAll = forwardAllCheckbox.isChecked,
                allowedDomains = allowedDomains.toList()
            )
        )
    }

    private fun onSaveClicked() {
        val email = emailInput.text?.toString()?.trim().orEmpty()
        val password = passwordInput.text?.toString()?.trim().orEmpty()
        val imap = imapInput.text?.toString()?.trim().orEmpty()
        val smtp = smtpInput.text?.toString()?.trim().orEmpty()
        val target = forwardToInput.text?.toString()?.trim().orEmpty()
        val previousProcessed = YahooForwarderStorage.loadSettings(this).processedFolder

        val settings = YahooForwarderStorage.Settings(email, password, imap, smtp, target, previousProcessed)
        if (!settings.isValid) {
            Toast.makeText(this, "Please fill in all fields", Toast.LENGTH_SHORT).show()
            return
        }

        YahooForwarderStorage.saveSettings(this, settings)
        YahooForwarderScheduler.schedule(applicationContext)
        Toast.makeText(this, "Yahoo forwarder saved and scheduled", Toast.LENGTH_SHORT).show()
        setCollapsed(true)
        refreshStatus()
        logState("Settings saved")
    }

    private fun onTestClicked() {
        runForwarder("Yahoo forwarder test run queued")
    }

    private fun runForwarder(toastMessage: String = "Yahoo forwarder run queued") {
        val settings = YahooForwarderStorage.loadSettings(this)
        if (!settings.isValid) {
            Toast.makeText(this, "Complete the Yahoo configuration before testing", Toast.LENGTH_SHORT).show()
            return
        }

        val request = OneTimeWorkRequestBuilder<YahooForwarderWorker>().build()
        WorkManager.getInstance(this)
            .enqueueUniqueWork("YahooForwarderTest", ExistingWorkPolicy.REPLACE, request)
        Toast.makeText(this, toastMessage, Toast.LENGTH_SHORT).show()
        logState("enqueue worker; message=$toastMessage")
    }

    private fun refreshStatus() {
        val status = YahooForwarderStorage.getLastStatus(this)
        val timeText = if (status.runTimeMillis > 0) {
            DateFormat.getDateTimeInstance().format(Date(status.runTimeMillis))
        } else {
            "Never run"
        }
        statusText.text = "$timeText\n${status.result}"
        logState("Status refreshed: ${status.result}")
        refreshLog()
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
        logState("onResume")
    }

    private fun refreshLog() {
        val entries = YahooForwarderStorage.getStatusHistory(this)
        logEntriesPresent = entries.isNotEmpty()
        if (entries.isEmpty()) {
            logText.text = getString(R.string.yahoo_status_log_empty)
        } else {
            val formatter = DateFormat.getDateTimeInstance()
            logText.text = entries.joinToString("\n\n") { entry ->
                val entryTime = if (entry.runTimeMillis > 0) {
                    formatter.format(Date(entry.runTimeMillis))
                } else {
                    "Unknown time"
                }
                "$entryTime\n${entry.result}"
            }
        }
        updateLogVisibility()
    }

    private fun setCollapsed(collapsed: Boolean) {
        settingsContainer.isVisible = !collapsed
        isCollapsedState = collapsed
        refreshLog()
        updateLogVisibility()
        logState("setCollapsed -> $collapsed")
    }

    private fun showSettings() {
        setCollapsed(false)
        logState("showSettings")
    }

    private fun logState(message: String) {
        val trimmed = message.trim()
        if (trimmed.isEmpty()) return
        Log.d(TAG, trimmed)
        YahooForwarderStorage.recordEvent(this, trimmed)
        runOnUiThread {
            logText.append("$trimmed\n")
            updateLogVisibility()
        }
        if (trimmed.contains("error", ignoreCase = true) || trimmed.contains("unable", ignoreCase = true)) {
            forceShowLog = true
        }
    }

    private fun updateLogVisibility() {
        val showLog = isCollapsedState || forceShowLog || logEntriesPresent
        logCard.isVisible = showLog
        editSettingsButton.isVisible = isCollapsedState
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        return super.onOptionsItemSelected(item)
    }
}

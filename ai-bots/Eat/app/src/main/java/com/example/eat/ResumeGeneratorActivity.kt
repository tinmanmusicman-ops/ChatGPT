package com.example.eat

import android.content.Intent
import android.content.SharedPreferences
import android.net.Uri
import android.os.Bundle
import android.view.MenuItem
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.google.android.material.button.MaterialButton
import io.noties.markwon.Markwon
import java.io.File

class ResumeGeneratorActivity : AppCompatActivity() {
    private lateinit var jobDescriptionInput: EditText
    private lateinit var generateButton: MaterialButton
    private lateinit var clearLogButton: MaterialButton
    private lateinit var shareResumePdfButton: MaterialButton
    private lateinit var shareCoverLetterPdfButton: MaterialButton
    private lateinit var resumeOutput: TextView
    private lateinit var coverLetterOutput: TextView
    private lateinit var logText: TextView
    private lateinit var prefs: SharedPreferences
    private lateinit var markwon: Markwon

    private val prefsListener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key == ResumeGeneratorStorage.getWorkLogKey() ||
            key == ResumeGeneratorStorage.getResumeKey() ||
            key == ResumeGeneratorStorage.getCoverLetterKey() ||
            key == ResumeGeneratorStorage.getResumePdfPathKey() ||
            key == ResumeGeneratorStorage.getCoverLetterPdfPathKey()
        ) {
            refreshOutputs()
            refreshWorkLog()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_resume_generator)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        supportActionBar?.title = "Resume Generator"

        jobDescriptionInput = findViewById(R.id.jobDescriptionInput)
        generateButton = findViewById(R.id.generateButton)
        clearLogButton = findViewById(R.id.clearLogButton)
        shareResumePdfButton = findViewById(R.id.shareResumePdfButton)
        shareCoverLetterPdfButton = findViewById(R.id.shareCoverLetterPdfButton)
        resumeOutput = findViewById(R.id.resumeOutput)
        coverLetterOutput = findViewById(R.id.coverLetterOutput)
        logText = findViewById(R.id.logText)

        prefs = ResumeGeneratorStorage.sharedPreferences(this)
        prefs.registerOnSharedPreferenceChangeListener(prefsListener)

        markwon = Markwon.create(this)

        jobDescriptionInput.setText(ResumeGeneratorStorage.loadJobDescription(this))
        refreshOutputs()
        refreshWorkLog()

        clearLogButton.setOnClickListener {
            ResumeGeneratorStorage.clearWorkLog(this)
            refreshWorkLog()
        }

        shareResumePdfButton.setOnClickListener {
            sharePdf(
                ResumeGeneratorStorage.loadResumePdfPath(this),
                "resume.pdf"
            )
        }

        shareCoverLetterPdfButton.setOnClickListener {
            sharePdf(
                ResumeGeneratorStorage.loadCoverLetterPdfPath(this),
                "cover_letter.pdf"
            )
        }

        generateButton.setOnClickListener {
            val jd = jobDescriptionInput.text?.toString()?.trim().orEmpty()
            if (jd.isBlank()) {
                Toast.makeText(this, "Paste a job description first", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            ResumeGeneratorStorage.saveJobDescription(this, jd)
            ResumeGeneratorStorage.clearWorkLog(this)
            enqueueGenerationWork()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        prefs.unregisterOnSharedPreferenceChangeListener(prefsListener)
    }

    private fun enqueueGenerationWork() {
        val request = OneTimeWorkRequestBuilder<ResumeGeneratorWorker>().build()
        WorkManager.getInstance(this)
            .enqueueUniqueWork(ResumeGeneratorWorker.WORK_NAME, ExistingWorkPolicy.REPLACE, request)
        Toast.makeText(this, "Resume generation queued", Toast.LENGTH_SHORT).show()
        ResumeGeneratorStorage.appendWorkLog(this, "Generate queued")
        refreshWorkLog()
    }

    private fun refreshOutputs() {
        val resume = ResumeGeneratorStorage.loadResume(this)
        val coverLetter = ResumeGeneratorStorage.loadCoverLetter(this)
        if (resume.isBlank()) {
            resumeOutput.text = ""
        } else {
            markwon.setMarkdown(resumeOutput, resume)
        }
        if (coverLetter.isBlank()) {
            coverLetterOutput.text = ""
        } else {
            markwon.setMarkdown(coverLetterOutput, coverLetter)
        }
    }

    private fun refreshWorkLog() {
        val workLog = ResumeGeneratorStorage.loadWorkLog(this)
        val header = buildString {
            appendLine("Resume Generator ready")
            append("Job description saved: ${if (ResumeGeneratorStorage.loadJobDescription(this@ResumeGeneratorActivity).isNotBlank()) "YES" else "NO"}")
        }
        val display = if (workLog.isNotBlank()) "$header\n$workLog" else header
        runOnUiThread { logText.text = display }
    }

    private fun sharePdf(path: String, fallbackName: String) {
        if (path.isBlank()) {
            Toast.makeText(this, "PDF not generated yet", Toast.LENGTH_SHORT).show()
            return
        }

        val uri = if (path.startsWith("content://", ignoreCase = true)) {
            Uri.parse(path)
        } else {
            val file = File(path)
            if (!file.exists()) {
                Toast.makeText(this, "PDF not generated yet", Toast.LENGTH_SHORT).show()
                return
            }
            FileProvider.getUriForFile(
                this,
                "${BuildConfig.APPLICATION_ID}.fileprovider",
                file
            )
        }

        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "application/pdf"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_SUBJECT, fallbackName)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(intent, "Share PDF"))
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == android.R.id.home) {
            finish()
            return true
        }
        return super.onOptionsItemSelected(item)
    }
}

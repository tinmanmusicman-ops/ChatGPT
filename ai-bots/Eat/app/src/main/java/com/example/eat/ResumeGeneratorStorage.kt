package com.example.eat

import android.content.Context
import android.content.SharedPreferences
import java.text.DateFormat
import java.util.Date

object ResumeGeneratorStorage {
    private const val PREFS_NAME = "ResumeGeneratorPrefs"
    private const val KEY_JOB_DESCRIPTION = "jobDescription"
    private const val KEY_RESUME = "resumeText"
    private const val KEY_COVER_LETTER = "coverLetterText"
    private const val KEY_RESUME_PDF_URI = "resumePdfUri"
    private const val KEY_COVER_LETTER_PDF_URI = "coverLetterPdfUri"
    private const val KEY_WORK_LOG = "workLog"
    private const val MAX_WORK_LOG_LINES = 128

    fun sharedPreferences(context: Context): SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun getWorkLogKey(): String = KEY_WORK_LOG
    fun getResumeKey(): String = KEY_RESUME
    fun getCoverLetterKey(): String = KEY_COVER_LETTER
    fun getResumePdfPathKey(): String = KEY_RESUME_PDF_URI
    fun getCoverLetterPdfPathKey(): String = KEY_COVER_LETTER_PDF_URI

    fun saveJobDescription(context: Context, text: String) {
        sharedPreferences(context).edit().putString(KEY_JOB_DESCRIPTION, text.trim()).apply()
    }

    fun loadJobDescription(context: Context): String =
        sharedPreferences(context).getString(KEY_JOB_DESCRIPTION, "") ?: ""

    fun saveOutputs(context: Context, resume: String, coverLetter: String) {
        sharedPreferences(context).edit()
            .putString(KEY_RESUME, resume)
            .putString(KEY_COVER_LETTER, coverLetter)
            .apply()
    }

    fun savePdfUris(context: Context, resumePdfUri: String, coverLetterPdfUri: String) {
        sharedPreferences(context).edit()
            .putString(KEY_RESUME_PDF_URI, resumePdfUri)
            .putString(KEY_COVER_LETTER_PDF_URI, coverLetterPdfUri)
            .apply()
    }

    fun loadResume(context: Context): String =
        sharedPreferences(context).getString(KEY_RESUME, "") ?: ""

    fun loadCoverLetter(context: Context): String =
        sharedPreferences(context).getString(KEY_COVER_LETTER, "") ?: ""

    fun loadResumePdfPath(context: Context): String =
        sharedPreferences(context).getString(KEY_RESUME_PDF_URI, "") ?: ""

    fun loadCoverLetterPdfPath(context: Context): String =
        sharedPreferences(context).getString(KEY_COVER_LETTER_PDF_URI, "") ?: ""

    fun loadWorkLog(context: Context): String =
        sharedPreferences(context).getString(KEY_WORK_LOG, "") ?: ""

    fun clearWorkLog(context: Context) {
        sharedPreferences(context).edit().putString(KEY_WORK_LOG, "").apply()
    }

    fun appendWorkLog(context: Context, message: String) {
        val trimmed = message.trim()
        if (trimmed.isBlank()) return
        synchronized(this) {
            val prefs = sharedPreferences(context)
            val existing = prefs.getString(KEY_WORK_LOG, "") ?: ""
            val builder = StringBuilder()
            if (existing.isNotBlank()) {
                builder.append(existing)
                builder.append("\n")
            }
            builder.append("${DateFormat.getDateTimeInstance().format(Date())} $trimmed")
            val updated = trimWorkLog(builder.toString())
            prefs.edit().putString(KEY_WORK_LOG, updated).apply()
        }
    }

    private fun trimWorkLog(raw: String): String {
        val lines = raw.split('\n')
        if (lines.size <= MAX_WORK_LOG_LINES) return raw
        return lines.takeLast(MAX_WORK_LOG_LINES).joinToString("\n")
    }
}

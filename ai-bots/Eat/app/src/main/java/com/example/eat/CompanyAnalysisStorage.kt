package com.example.eat

import android.content.Context

data class CompanyAnalysisCache(val company: String, val report: String)

object CompanyAnalysisStorage {
    private const val PREFS_NAME = "CompanyAnalysisPrefs"
    private const val KEY_COMPANY = "last_company"
    private const val KEY_REPORT = "last_report"

    fun save(context: Context, company: String, report: String) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit()
            .putString(KEY_COMPANY, company)
            .putString(KEY_REPORT, report)
            .apply()
    }

    fun load(context: Context): CompanyAnalysisCache? {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val company = prefs.getString(KEY_COMPANY, "") ?: ""
        val report = prefs.getString(KEY_REPORT, "") ?: ""
        return if (company.isNotBlank() && report.isNotBlank()) {
            CompanyAnalysisCache(company, report)
        } else {
            null
        }
    }
}

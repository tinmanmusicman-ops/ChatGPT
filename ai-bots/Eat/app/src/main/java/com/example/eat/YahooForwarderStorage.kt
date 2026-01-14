package com.example.eat

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

object YahooForwarderStorage {
    private const val PREFS_NAME = "YahooForwarderPrefs"
    private const val KEY_YAHOO_EMAIL = "yahooEmail"
    private const val KEY_YAHOO_PASSWORD = "yahooAppPassword"
    private const val KEY_IMAP_SERVER = "imapServer"
    private const val KEY_SMTP_SERVER = "smtpServer"
    private const val KEY_FORWARD_TO = "forwardTo"
    private const val KEY_PROCESSED_FOLDER = "processedFolder"
    private const val KEY_LAST_RUN_TIME = "lastRunTime"
    private const val KEY_LAST_RESULT = "lastResult"
    private const val KEY_STATUS_LOG = "statusLog"
    private const val MAX_LOG_ENTRIES = 8
    private const val KEY_SETTINGS_SAVED = "settingsSaved"
    private const val DEFAULT_PROCESSED_FOLDER = "YahooForwarder"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    data class Settings(
        val yahooEmail: String,
        val yahooAppPassword: String,
        val imapServer: String,
        val smtpServer: String,
        val forwardTo: String,
        val processedFolder: String,
    ) {
        val isValid: Boolean
            get() = listOf(
                yahooEmail,
                yahooAppPassword,
                imapServer,
                smtpServer,
                forwardTo
            ).all { it.isNotBlank() }

        private fun parseHostPort(rawValue: String, defaultPort: Int): Pair<String, Int> {
            val trimmed = rawValue.trim()
            if (trimmed.isEmpty()) return "" to defaultPort
            val parts = trimmed.split(":")
            val host = parts.firstOrNull()?.trim().orEmpty()
            val port = parts.getOrNull(1)?.toIntOrNull() ?: defaultPort
            return host to port
        }

        val imapHost: String
            get() = parseHostPort(imapServer, 993).first

        val imapPort: Int
            get() = parseHostPort(imapServer, 993).second

        val smtpHost: String
            get() = parseHostPort(smtpServer, 587).first

        val smtpPort: Int
            get() = parseHostPort(smtpServer, 587).second

        fun maskedForwardTo(): String = maskEmail(forwardTo)
    }

    data class Status(val runTimeMillis: Long, val result: String)

    fun loadSettings(context: Context): Settings {
        val prefs = prefs(context)
        return Settings(
            yahooEmail = prefs.getString(KEY_YAHOO_EMAIL, "")?.trim().orEmpty().ifBlank { BuildConfig.YAHOO_EMAIL_DEFAULT },
            yahooAppPassword = prefs.getString(KEY_YAHOO_PASSWORD, "")?.trim().orEmpty().ifBlank { BuildConfig.YAHOO_APP_PASSWORD_DEFAULT },
            imapServer = prefs.getString(KEY_IMAP_SERVER, "")?.trim().orEmpty().ifBlank { BuildConfig.YAHOO_IMAP_SERVER_DEFAULT },
            smtpServer = prefs.getString(KEY_SMTP_SERVER, "")?.trim().orEmpty().ifBlank { BuildConfig.YAHOO_SMTP_SERVER_DEFAULT },
            forwardTo = prefs.getString(KEY_FORWARD_TO, "")?.trim().orEmpty().ifBlank { BuildConfig.YAHOO_FORWARD_TO_DEFAULT },
            processedFolder = prefs.getString(KEY_PROCESSED_FOLDER, DEFAULT_PROCESSED_FOLDER)?.trim()
                ?: DEFAULT_PROCESSED_FOLDER
        )
    }

    fun saveSettings(context: Context, settings: Settings) {
        if (!settings.isValid) return
        prefs(context).edit()
            .putString(KEY_YAHOO_EMAIL, settings.yahooEmail.trim())
            .putString(KEY_YAHOO_PASSWORD, settings.yahooAppPassword.trim())
            .putString(KEY_IMAP_SERVER, settings.imapServer.trim())
            .putString(KEY_SMTP_SERVER, settings.smtpServer.trim())
            .putString(KEY_FORWARD_TO, settings.forwardTo.trim())
            .putString(KEY_PROCESSED_FOLDER, settings.processedFolder.ifBlank {
                DEFAULT_PROCESSED_FOLDER
            })
            .putBoolean(KEY_SETTINGS_SAVED, true)
            .apply()
    }

    fun updateLastStatus(context: Context, runTimeMillis: Long, result: String) {
        prefs(context).edit()
            .putLong(KEY_LAST_RUN_TIME, runTimeMillis)
            .putString(KEY_LAST_RESULT, result.trim())
            .apply()
        appendStatusLog(context, Status(runTimeMillis, result.trim()))
    }

    fun getLastStatus(context: Context): Status {
        val prefs = prefs(context)
        val runTime = prefs.getLong(KEY_LAST_RUN_TIME, 0L)
        val result = prefs.getString(KEY_LAST_RESULT, "Not run yet.") ?: "Not run yet."
        return Status(runTime, result)
    }

    fun getStatusHistory(context: Context): List<Status> {
        val prefs = prefs(context)
        val raw = prefs.getString(KEY_STATUS_LOG, "[]") ?: "[]"
        val array = try {
            JSONArray(raw)
        } catch (ex: Exception) {
            JSONArray()
        }
        val list = mutableListOf<Status>()
        for (i in 0 until array.length()) {
            val obj = array.optJSONObject(i) ?: continue
            val time = obj.optLong("timestamp", 0L)
            val text = obj.optString("result", "No status")
            list.add(Status(time, text))
        }
        return list
    }

    fun hasSavedSettings(context: Context): Boolean {
        val prefs = prefs(context)
        return prefs.getBoolean(KEY_SETTINGS_SAVED, false) || hasDefaultCredentials()
    }

    private fun hasDefaultCredentials(): Boolean {
        return listOf(
            BuildConfig.YAHOO_EMAIL_DEFAULT,
            BuildConfig.YAHOO_APP_PASSWORD_DEFAULT,
            BuildConfig.YAHOO_IMAP_SERVER_DEFAULT,
            BuildConfig.YAHOO_SMTP_SERVER_DEFAULT,
            BuildConfig.YAHOO_FORWARD_TO_DEFAULT
        ).all { it.isNotBlank() }
    }

    fun recordEvent(context: Context, message: String) {
        appendStatusLog(context, Status(System.currentTimeMillis(), message))
    }

    private fun appendStatusLog(context: Context, entry: Status) {
        val prefs = prefs(context)
        val raw = prefs.getString(KEY_STATUS_LOG, "[]") ?: "[]"
        val array = try {
            JSONArray(raw)
        } catch (ex: Exception) {
            JSONArray()
        }
        array.put(JSONObject().apply {
            put("timestamp", entry.runTimeMillis)
            put("result", entry.result)
        })
        while (array.length() > MAX_LOG_ENTRIES) {
            array.remove(0)
        }
        prefs.edit().putString(KEY_STATUS_LOG, array.toString()).apply()
    }

    fun isConfigured(context: Context): Boolean =
        loadSettings(context).isValid

    private fun maskEmail(value: String): String {
        val trimmed = value.trim()
        if (!trimmed.contains("@")) return "***"
        val parts = trimmed.split("@", limit = 2)
        val prefix = parts[0]
        val domain = parts.getOrNull(1).orEmpty()
        val visible = if (prefix.length <= 2) prefix else prefix.substring(0, 2)
        return "$visible***@${domain}"
    }
}

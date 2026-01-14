package com.example.eat

import android.util.Log
import java.io.IOException
import java.util.Date
import java.util.Locale
import java.util.Properties
import javax.mail.Authenticator
import javax.mail.Flags
import javax.mail.Folder
import javax.mail.Message
import javax.mail.MessagingException
import javax.mail.Multipart
import javax.mail.Part
import javax.mail.PasswordAuthentication
import javax.mail.Session
import javax.mail.Transport
import javax.mail.internet.InternetAddress
import javax.mail.internet.MimeMessage
import javax.mail.search.FlagTerm

object YahooForwarderEngine {
    private const val TAG = "YahooForwarderEngine"
    private const val TAG_KEYWORD = "FORWARDED_CRAIGSLIST"
    private const val PROCESSED_FOLDER_DEFAULT = "YahooForwarder"
    private const val UNMATCHED_FOLDER = "_Unread"

    data class EngineResult(val forwardedCount: Int, val resultMessage: String)

    @Throws(IOException::class, MessagingException::class)
    fun forwardUnseen(
        settings: YahooForwarderStorage.Settings,
        filterSettings: YahooForwarderStorage.FilterSettings
    ): EngineResult {
        val store = connectToImap(settings)
        var inbox: Folder? = null
        var processed: Folder? = null
        return try {
            inbox = store.getFolder("INBOX").apply { open(Folder.READ_WRITE) }
            val unseen = inbox.search(FlagTerm(Flags(Flags.Flag.SEEN), false))
            if (unseen.isEmpty()) {
                return EngineResult(0, "No unseen messages found")
            }

            processed = ensureMailbox(store, settings.processedFolder.ifBlank { PROCESSED_FOLDER_DEFAULT })
            val unmatched = ensureMailbox(store, UNMATCHED_FOLDER)
            var forwarded = 0
            for (message in unseen) {
                if (!shouldForwardMessage(message, filterSettings)) {
                    if (moveMessageSafely(message, inbox, unmatched)) {
                        Log.i(TAG, "No match; moved message to $UNMATCHED_FOLDER (kept UNREAD)")
                    }
                    continue
                }
                try {
                    processMessage(message, settings, inbox, processed)
                    forwarded++
                } catch (ex: Exception) {
                    Log.w(TAG, "Failed to forward message: ${ex.message}", ex)
                }
            }
            EngineResult(forwarded, "Forwarded $forwarded message(s)")
        } finally {
            try {
                processed?.close(false)
            } catch (ignored: MessagingException) {
            }
            try {
                inbox?.close(true)
            } catch (ignored: MessagingException) {
            }
            try {
                store.close()
            } catch (ignored: MessagingException) {
            }
        }
    }

    @Throws(MessagingException::class)
    private fun connectToImap(settings: YahooForwarderStorage.Settings): javax.mail.Store {
        val props = Properties().apply {
            put("mail.store.protocol", "imaps")
            put("mail.imaps.host", settings.imapHost)
            put("mail.imaps.port", settings.imapPort.toString())
            put("mail.imaps.ssl.trust", "*")
            put("mail.imaps.connectiontimeout", "30000")
            put("mail.imaps.timeout", "30000")
            put("mail.imaps.ssl.enable", "true")
        }
        val session = Session.getInstance(props, object : Authenticator() {
            override fun getPasswordAuthentication() =
                PasswordAuthentication(settings.yahooEmail, settings.yahooAppPassword)
        })
        val store = session.getStore("imaps")
        store.connect(settings.imapHost, settings.imapPort, settings.yahooEmail, settings.yahooAppPassword)
        return store
    }

    @Throws(MessagingException::class)
    private fun ensureMailbox(store: javax.mail.Store, mailboxName: String): Folder {
        val targetName = mailboxName.trim()
        val target = store.getFolder(targetName)
        if (!target.exists()) {
            try {
                target.create(Folder.HOLDS_MESSAGES)
            } catch (ex: MessagingException) {
                Log.w(TAG, "Unable to create folder $targetName: ${ex.message}", ex)
            }
        }
        if (!target.isOpen) {
            target.open(Folder.READ_WRITE)
        }
        return target
    }

    @Throws(IOException::class, MessagingException::class)
    private fun processMessage(message: Message, settings: YahooForwarderStorage.Settings, inbox: Folder, processed: Folder) {
        val from = message.from?.firstOrNull()?.toString() ?: "unknown"
        val subject = message.subject ?: ""
        val date = message.sentDate?.toString() ?: Date().toString()
        Log.i(
            TAG,
            "Processing message from ${maskEmail(from)} subject=\"${subject.takeIf { it.isNotBlank() } ?: "No subject"}\""
        )
        val body = extractPlainText(message)
        sendForward(message, body, settings, subject, from, date)
        markMessageFlags(message)
        if (!moveMessageSafely(message, inbox, processed)) {
            Log.w(TAG, "Forwarded but failed to move to ${processed.fullName}")
        }
    }

    @Throws(IOException::class, MessagingException::class)
    private fun sendForward(
        original: Message,
        bodyText: String,
        settings: YahooForwarderStorage.Settings,
        originalSubject: String,
        sender: String,
        date: String
    ) {
        val smtpPorts = listOf(settings.smtpPort, 465, 587).distinct().filter { it > 0 }
        val lastException = RuntimeExceptionHolder()
        smtpPorts.forEach { port ->
            try {
                val props = smtpProperties(settings, port)
                val session = Session.getInstance(props, object : Authenticator() {
                    override fun getPasswordAuthentication() =
                        PasswordAuthentication(settings.yahooEmail, settings.yahooAppPassword)
                })
                val forwarded = MimeMessage(session).apply {
                    setFrom(InternetAddress(settings.yahooEmail))
                    setRecipients(
                        Message.RecipientType.TO,
                        InternetAddress.parse(settings.forwardTo, false)
                    )
                    setSubject(if (originalSubject.isBlank()) "FWD: message" else "FWD: $originalSubject")
                    setSentDate(Date())
                    setText(
                        buildForwardBody(sender, originalSubject, date, bodyText),
                        "utf-8"
                    )
                    setHeader("Reply-To", settings.yahooEmail)
                    setHeader("X-Forwarded-By", "Eat Yahoo Forwarder")
                }
                Transport.send(forwarded)
                Log.i(TAG, "Forwarded to ${maskEmail(settings.forwardTo)} via SMTP port $port")
                return
            } catch (ex: MessagingException) {
                Log.w(TAG, "SMTP port $port failed: ${ex.message}")
                lastException.exception = ex
            }
        }
        throw lastException.exception ?: MessagingException("SMTP send failed")
    }

    private fun smtpProperties(settings: YahooForwarderStorage.Settings, port: Int): Properties {
        return Properties().apply {
            put("mail.smtp.host", settings.smtpHost)
            put("mail.smtp.port", port.toString())
            put("mail.smtp.ssl.trust", "*")
            put("mail.smtp.connectiontimeout", "30000")
            put("mail.smtp.timeout", "30000")
            put("mail.smtp.auth", "true")
            if (port == 465) {
                put("mail.smtp.ssl.enable", "true")
            } else {
                put("mail.smtp.starttls.enable", "true")
                put("mail.smtp.starttls.required", "false")
            }
        }
    }

    @Throws(MessagingException::class)
    private fun markMessageFlags(message: Message) {
        try {
            message.setFlag(Flags.Flag.SEEN, true)
            message.setFlags(Flags(Flags.Flag.FLAGGED), true)
        } catch (_: MessagingException) {
        }
        try {
            message.setFlags(Flags(TAG_KEYWORD), true)
        } catch (_: MessagingException) {
        }
    }

    @Throws(MessagingException::class)
    private fun moveMessageSafely(message: Message, source: Folder, destination: Folder): Boolean {
        try {
            source.copyMessages(arrayOf(message), destination)
        } catch (ex: MessagingException) {
            Log.w(TAG, "Move failed (copy) to ${destination.fullName}: ${ex.message}", ex)
            return false
        }
        try {
            message.setFlag(Flags.Flag.DELETED, true)
        } catch (ex: MessagingException) {
            Log.w(TAG, "Move incomplete; copy succeeded but delete failed: ${ex.message}", ex)
        }
        return true
    }

    @Throws(IOException::class, MessagingException::class)
    private fun extractPlainText(message: Message): String {
        if (message.isMimeType("text/plain")) {
            return message.getContent()?.toString() ?: ""
        }
        if (message.isMimeType("multipart/*")) {
            val multipart = message.content as? Multipart
            if (multipart != null) {
                for (index in 0 until multipart.count) {
                    val part = multipart.getBodyPart(index)
                    if (Part.ATTACHMENT.equals(part.disposition, ignoreCase = true)) continue
                    if (part.isMimeType("text/plain")) {
                        return part.getContent()?.toString() ?: ""
                    }
                }
                for (index in 0 until multipart.count) {
                    val part = multipart.getBodyPart(index)
                    if (part.isMimeType("text/html")) {
                        return part.getContent()?.toString() ?: ""
                    }
                }
            }
        }
        return message.getContent()?.toString() ?: ""
    }

    private fun shouldForwardMessage(
        message: Message,
        filterSettings: YahooForwarderStorage.FilterSettings
    ): Boolean {
        if (filterSettings.forwardAll) return true
        if (filterSettings.allowedDomains.isEmpty()) return false
        val senderDomain = extractSenderDomain(message) ?: return false
        return filterSettings.allowedDomains.any { allowed ->
            senderDomain == allowed || senderDomain.endsWith(".$allowed")
        }
    }

    private fun extractSenderDomain(message: Message): String? {
        val from = message.from?.firstOrNull()
        val address = (from as? InternetAddress)?.address?.trim().orEmpty().ifBlank {
            try {
                InternetAddress.parse(from?.toString().orEmpty(), false).firstOrNull()?.address?.trim().orEmpty()
            } catch (_: Exception) {
                ""
            }
        }
        if (address.isBlank() || !address.contains("@")) return null
        val domain = address.substringAfter("@").trim().lowercase(Locale.ROOT)
        return domain.ifBlank { null }
    }

    private fun buildForwardBody(sender: String, subject: String, date: String, body: String): String {
        return buildString {
            appendLine("Forwarded message")
            appendLine("From: ${sender.trim()}")
            appendLine("Subject: ${subject.trim().ifBlank { "No subject" }}")
            appendLine("Date: ${date.trim()}")
            appendLine()
            appendLine("---- Original Body (plain text preferred) ----")
            appendLine(body)
        }
    }

    private fun maskEmail(candidate: String): String {
        val trimmed = candidate.trim()
        if (!trimmed.contains("@")) return "***"
        val parts = trimmed.split("@", limit = 2)
        val prefix = parts[0]
        val domain = parts.getOrNull(1).orEmpty()
        val visible = if (prefix.length <= 2) prefix else prefix.substring(0, 2)
        return "$visible***@${domain}"
    }

    private class RuntimeExceptionHolder {
        var exception: MessagingException? = null
    }
}

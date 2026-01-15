package com.example.eat

import android.content.Context
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

object ResumeGeneratorEngine {
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .writeTimeout(180, TimeUnit.SECONDS)
        .callTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val CLOSED_JOB_INDICATORS = listOf(
        "no longer accepting applications",
        "position has been filled",
        "job is no longer available",
        "posting has expired",
        "applications are closed",
        "requisition closed",
        "this job has been filled",
        "job unavailable",
        "posting removed",
    )

    data class GeneratedOutput(val resume: String, val coverLetter: String)

    fun detectClosedJobIndicator(jobDescription: String): String? {
        val lowered = jobDescription.lowercase()
        return CLOSED_JOB_INDICATORS.firstOrNull { indicator -> lowered.contains(indicator) }
    }

    @Throws(IOException::class)
    fun generate(context: Context, jobDescription: String): GeneratedOutput {
        if (BuildConfig.OPENAI_API_KEY.isBlank()) {
            throw IOException("OPENAI_API_KEY missing (same requirement as Company Intelligence tool)")
        }

        val baseResumeJson = loadBaseResumeJson(context)
        val prompt = buildPrompt(jobDescription, baseResumeJson)
        val payload = buildPayload(prompt)

        val mediaType = "application/json; charset=utf-8".toMediaType()
        val body = payload.toString().toRequestBody(mediaType)
        val request = Request.Builder()
            .url("https://api.openai.com/v1/responses")
            .header("Authorization", "Bearer ${BuildConfig.OPENAI_API_KEY}")
            .post(body)
            .build()

        val raw = client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IOException("OpenAI error ${response.code}")
            }
            response.body?.string().orEmpty()
        }

        val outputText = extractText(raw)
        return extractJsonPayload(outputText)
    }

    private fun buildPrompt(jobDescription: String, baseResumeJson: String): String {
        return buildString {
            appendLine("Base resume JSON:")
            appendLine(baseResumeJson.trim())
            appendLine()
            appendLine("Job description:")
            appendLine(jobDescription.trim())
            appendLine()
            append(
                "Return a JSON object that contains exactly two keys: `resume` and `cover_letter`. " +
                    "Do not wrap the JSON in markdown or code fence. " +
                    "Each value must be Markdown (headings, bullet lists, bold where helpful). " +
                    "Do not include triple-backtick code fences in the values. " +
                    "Each value should be a polished, fully formatted document adapted to the job."
            )
        }
    }

    private fun buildPayload(prompt: String): JSONObject {
        val systemMessage = JSONObject().apply {
            put("role", "system")
            val contentArray = JSONArray()
            contentArray.put(
                JSONObject()
                    .put("type", "input_text")
                    .put(
                        "text",
                        "You are an expert resume writer who adapts a base resume JSON payload " +
                            "into tailored resumes and cover letters based on job descriptions."
                    )
            )
            put("content", contentArray)
        }
        val userMessage = JSONObject().apply {
            put("role", "user")
            val contentArray = JSONArray()
            contentArray.put(JSONObject().put("type", "input_text").put("text", prompt))
            put("content", contentArray)
        }
        return JSONObject().apply {
            put("model", "gpt-4.1")
            put("temperature", 0.2)
            put("max_output_tokens", 8000)
            put("input", JSONArray().put(systemMessage).put(userMessage))
        }
    }

    private fun loadBaseResumeJson(context: Context): String {
        context.assets.open("resume/base_resume.json").use { input ->
            return input.bufferedReader(Charsets.UTF_8).readText()
        }
    }

    private fun extractText(raw: String): String {
        if (raw.isBlank()) throw IOException("OpenAI returned empty payload")
        val json = JSONObject(raw)
        val outputText = json.optString("output_text")
        if (outputText.isNotBlank()) return outputText.trim()
        val outputArray = json.optJSONArray("output") ?: return ""
        val parts = mutableListOf<String>()
        for (i in 0 until outputArray.length()) {
            val entry = outputArray.getJSONObject(i)
            val textField = entry.optString("text")
            if (textField.isNotBlank()) {
                parts.add(textField)
                continue
            }
            val content = entry.optJSONArray("content") ?: continue
            for (j in 0 until content.length()) {
                val chunk = content.getJSONObject(j)
                val textChunk = chunk.optString("text")
                if (textChunk.isNotBlank()) parts.add(textChunk)
            }
        }
        return parts.joinToString("\n").trim()
    }

    private fun extractJsonPayload(text: String): GeneratedOutput {
        val trimmed = text.trim()
        if (trimmed.isBlank()) throw IOException("Received an empty response from the AI model.")

        val payload = try {
            JSONObject(trimmed)
        } catch (_: Exception) {
            val start = trimmed.indexOf('{')
            val end = trimmed.lastIndexOf('}')
            if (start == -1 || end == -1 || end <= start) {
                throw IOException("Unable to parse model JSON output")
            }
            JSONObject(trimmed.substring(start, end + 1))
        }

        val resumeText = payload.optString("resume", "").trim()
        val coverLetterText = payload.optString("cover_letter", "").trim()
        if (resumeText.isBlank() || coverLetterText.isBlank()) {
            throw IOException("Model response missing required `resume` or `cover_letter` fields")
        }

        return GeneratedOutput(resumeText, coverLetterText)
    }
}

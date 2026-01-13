package com.example.eat

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

class CompanyAnalysisActivity : AppCompatActivity() {
    private val client = OkHttpClient()
    private lateinit var companyInput: EditText
    private lateinit var analyzeButton: Button
    private lateinit var reportContainer: LinearLayout
    private lateinit var statusText: TextView
    private lateinit var progressBar: ProgressBar

    companion object {
        private val PROMPT_TEMPLATE = """
            You are an experienced market researcher. Provide a deep analysis of %s formatted as structured Markdown.
            Return the response as a professional company intelligence report that is easy to read, clearly spaced, and uses headings, subheadings, and bullet points.
            Include the following sections, each introduced with a Markdown heading (##):
            - Company Overview
            - Business Model & Core Offerings
            - Market Position & Competitive Landscape
            - Revenue & Scale (Approximate)
            - Customer Perception & Brand Reputation
            - Employee Sentiment & Culture
            - Recent Notable Events
            - Key Risks & Challenges
            - Growth Opportunities & Strategic Insights
            - Evaluation Highlights (use bullet points for this final recap)

            Emphasize approximate figures when you are unsure, avoid unsupported claims, and keep each section concise but informative.
        """.trimIndent()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_company_analysis)
        companyInput = findViewById(R.id.companyInput)
        analyzeButton = findViewById(R.id.analyzeButton)
        reportContainer = findViewById(R.id.reportContainer)
        statusText = findViewById(R.id.statusText)
        progressBar = findViewById(R.id.progressBar)

        analyzeButton.setOnClickListener {
            val name = companyInput.text.toString().trim()
            if (name.isEmpty()) {
                showStatus("Enter a company name first", true)
                return@setOnClickListener
            }
            analyzeCompany(name)
        }

        CompanyAnalysisStorage.load(this)?.let { cache ->
            companyInput.setText(cache.company)
            displaySections(parseSections(cache.report))
            showStatus("Loaded last analysis for ${cache.company}", false)
        }
    }

    private fun analyzeCompany(companyName: String) {
        if (BuildConfig.OPENAI_API_KEY.isBlank()) {
            showStatus("OPENAI_API_KEY missing. Set it in gradle.properties as openai.api.key", true)
            return
        }
        showStatus("Requesting intelligence for $companyName", false)
        progressBar.isVisible = true
        analyzeButton.isEnabled = false
        lifecycleScope.launch {
            try {
                val prompt = PROMPT_TEMPLATE.format(companyName)
                val responseText = withContext(Dispatchers.IO) { fetchReport(prompt) }
                val sections = parseSections(responseText)
                displaySections(sections)
                CompanyAnalysisStorage.save(this@CompanyAnalysisActivity, companyName, responseText)
                showStatus("Analysis complete for $companyName", false)
            } catch (exc: Exception) {
                showStatus("Analysis failed: ${exc.message}", true)
            } finally {
                progressBar.isVisible = false
                analyzeButton.isEnabled = true
            }
        }
    }

    private fun showStatus(message: String, isError: Boolean) {
        statusText.text = message
        statusText.setTextColor(
            if (isError) statusText.context.getColor(android.R.color.holo_red_light)
            else statusText.context.getColor(R.color.onSurface)
        )
    }

    private suspend fun fetchReport(prompt: String): String {
        val payload = buildPayload(prompt)
        val mediaType = "application/json; charset=utf-8".toMediaType()
        val body = payload.toString().toRequestBody(mediaType)
        val request = Request.Builder()
            .url("https://api.openai.com/v1/responses")
            .header("Authorization", "Bearer ${BuildConfig.OPENAI_API_KEY}")
            .post(body)
            .build()

        return withContext(Dispatchers.IO) {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                throw IOException("OpenAI error ${response.code}")
            }
            val raw = response.body?.string().orEmpty()
            extractText(raw)
        }
    }

    private fun buildPayload(prompt: String): JSONObject {
        val userMessage = JSONObject().apply {
            put("role", "user")
            val contentArray = JSONArray()
            contentArray.put(JSONObject().put("type", "text").put("text", prompt))
            put("content", contentArray)
        }
        return JSONObject().apply {
            put("model", "gpt-5.1")
            put("temperature", 0.35)
            put("input", JSONArray().put(userMessage))
        }
    }

    private fun extractText(raw: String): String {
        if (raw.isBlank()) {
            throw IOException("OpenAI returned empty payload")
        }
        val json = JSONObject(raw)
        val outputText = json.optString("output_text")
        if (outputText.isNotBlank()) {
            return outputText.trim()
        }
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
                if (textChunk.isNotBlank()) {
                    parts.add(textChunk)
                }
            }
        }
        if (parts.isEmpty()) {
            throw IOException("Unable to parse OpenAI response")
        }
        return parts.joinToString("\n").trim()
    }

    private fun parseSections(rawText: String): List<Section> {
        val sections = mutableListOf<Section>()
        var currentTitle: String? = null
        val currentLines = mutableListOf<String>()
        rawText.lines().forEach { raw ->
            val line = raw.trim()
            if (line.startsWith("## ")) {
                currentTitle?.let {
                    if (currentLines.isNotEmpty()) {
                        sections.add(Section(it, currentLines.toList()))
                    }
                }
                currentLines.clear()
                currentTitle = line.removePrefix("## ").trim()
            } else if (line.startsWith("# ")) {
                // skip top-level heading
            } else if (line.isNotEmpty()) {
                if (currentTitle == null) {
                    currentTitle = "Details"
                }
                currentLines.add(line)
            }
        }
        currentTitle?.let {
            if (currentLines.isNotEmpty()) {
                sections.add(Section(it, currentLines.toList()))
            }
        }
        return sections
    }

    private fun displaySections(sections: List<Section>) {
        reportContainer.removeAllViews()
        if (sections.isEmpty()) {
            showStatus("No structured sections were detected.", true)
            return
        }
        sections.forEach { section ->
            val titleView = TextView(this).apply {
                text = section.title
                textSize = 18f
                setPadding(0, 16, 0, 4)
            }
            val bodyView = TextView(this).apply {
                text = section.lines.joinToString("\n")
                textSize = 15f
            }
            reportContainer.addView(titleView)
            reportContainer.addView(bodyView)
        }
    }

    data class Section(val title: String, val lines: List<String>)
}

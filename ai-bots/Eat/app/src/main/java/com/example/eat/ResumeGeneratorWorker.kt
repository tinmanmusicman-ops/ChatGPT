package com.example.eat

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.ListenableWorker.Result
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class ResumeGeneratorWorker(context: Context, params: WorkerParameters) :
    CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        ResumeGeneratorStorage.appendWorkLog(applicationContext, "Job started")

        val jobDescription = ResumeGeneratorStorage.loadJobDescription(applicationContext).trim()
        if (jobDescription.isBlank()) {
            ResumeGeneratorStorage.appendWorkLog(applicationContext, "Job description empty; aborting")
            return Result.failure()
        }

        if (BuildConfig.OPENAI_API_KEY.isBlank()) {
            ResumeGeneratorStorage.appendWorkLog(
                applicationContext,
                "OPENAI_API_KEY missing. Set it in gradle.properties as openai.api.key"
            )
            return Result.failure()
        }

        val closedPhrase = ResumeGeneratorEngine.detectClosedJobIndicator(jobDescription)
        if (closedPhrase != null) {
            ResumeGeneratorStorage.appendWorkLog(applicationContext, "Closed-job detected ($closedPhrase); skipping")
            ResumeGeneratorStorage.saveOutputs(applicationContext, "", "")
            return Result.success()
        }

        ResumeGeneratorStorage.appendWorkLog(applicationContext, "Closed-job detection: none")
        ResumeGeneratorStorage.appendWorkLog(applicationContext, "Generation started")

        return try {
            val output = withContext(Dispatchers.IO) {
                ResumeGeneratorEngine.generate(applicationContext, jobDescription)
            }
            ResumeGeneratorStorage.saveOutputs(applicationContext, output.resume, output.coverLetter)

            ResumeGeneratorStorage.appendWorkLog(applicationContext, "PDF generation started")
            val stamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
            val resumeUri = ResumeGeneratorPdf.saveMarkdownPdfToDocuments(
                applicationContext,
                "resume_$stamp.pdf",
                "",
                output.resume
            )
            val coverUri = ResumeGeneratorPdf.saveMarkdownPdfToDocuments(
                applicationContext,
                "cover_letter_$stamp.pdf",
                "Cover Letter",
                output.coverLetter
            )
            ResumeGeneratorStorage.savePdfUris(applicationContext, resumeUri.toString(), coverUri.toString())
            ResumeGeneratorStorage.appendWorkLog(applicationContext, "PDF saved: resume_$stamp.pdf")
            ResumeGeneratorStorage.appendWorkLog(applicationContext, "PDF saved: cover_letter_$stamp.pdf")

            ResumeGeneratorStorage.appendWorkLog(applicationContext, "Generation completed")
            Result.success()
        } catch (ex: Exception) {
            val message = when (ex) {
                is IOException -> "Network/I/O error: ${ex.localizedMessage}"
                else -> "Generation error: ${ex.localizedMessage}"
            }
            Log.w(TAG, message, ex)
            ResumeGeneratorStorage.appendWorkLog(applicationContext, message)
            Result.failure()
        }
    }

    companion object {
        const val WORK_NAME = "ResumeGeneratorGenerate"
        private const val TAG = "ResumeGeneratorWorker"
    }
}

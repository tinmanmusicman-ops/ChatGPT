package com.example.eat

import android.content.Context
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.os.Environment
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import io.noties.markwon.Markwon
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.text.DateFormat
import java.util.Date

object ResumeGeneratorPdf {
    private const val PAGE_WIDTH = 612
    private const val PAGE_HEIGHT = 792
    private const val MARGIN = 36f

    fun outputDir(context: Context): File {
        val documentsDir = context.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS)
        val root = documentsDir ?: context.filesDir
        return File(root, "ResumeGenerator").apply { mkdirs() }
    }

    fun writeTextPdf(outputFile: File, title: String, body: String) {
        val pdf = PdfDocument()
        try {
            val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
                textSize = 16f
                color = android.graphics.Color.BLACK
            }
            val metaPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.NORMAL)
                textSize = 10f
                color = android.graphics.Color.DKGRAY
            }
            val bodyPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.NORMAL)
                textSize = 11f
                color = android.graphics.Color.BLACK
            }

            val availableWidth = PAGE_WIDTH - (MARGIN * 2)
            val lineHeight = (bodyPaint.fontMetrics.bottom - bodyPaint.fontMetrics.top)
            val maxY = PAGE_HEIGHT - MARGIN

            val lines = wrapText(body, bodyPaint, availableWidth)
            var pageNumber = 1
            var lineIndex = 0
            while (lineIndex < lines.size) {
                val pageInfo = PdfDocument.PageInfo.Builder(PAGE_WIDTH, PAGE_HEIGHT, pageNumber).create()
                val page = pdf.startPage(pageInfo)
                val canvas = page.canvas

                var y = MARGIN + 18f
                y = drawHeader(canvas, title, titlePaint, metaPaint, y)
                y += 12f

                while (lineIndex < lines.size) {
                    val nextY = y + lineHeight
                    if (nextY > maxY) break
                    canvas.drawText(lines[lineIndex], MARGIN, y, bodyPaint)
                    y = nextY
                    lineIndex++
                }

                pdf.finishPage(page)
                pageNumber++
            }

            FileOutputStream(outputFile).use { out ->
                pdf.writeTo(out)
            }
        } finally {
            pdf.close()
        }
    }

    fun writeMarkdownPdf(context: Context, outputFile: File, title: String, markdown: String) {
        FileOutputStream(outputFile).use { out ->
            writeMarkdownPdfToStream(context, out, title, markdown)
        }
    }

    fun saveMarkdownPdfToDocuments(
        context: Context,
        displayName: String,
        title: String,
        markdown: String
    ): Uri {
        if (Build.VERSION.SDK_INT >= 29) {
            val resolver = context.contentResolver
            val values = ContentValues().apply {
                put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, displayName)
                put(android.provider.MediaStore.MediaColumns.MIME_TYPE, "application/pdf")
                put(
                    android.provider.MediaStore.MediaColumns.RELATIVE_PATH,
                    Environment.DIRECTORY_DOCUMENTS + "/Eat/ResumeGenerator"
                )
                put(android.provider.MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val uri = resolver.insert(android.provider.MediaStore.Files.getContentUri("external"), values)
                ?: throw java.io.IOException("Unable to create Documents entry for $displayName")
            try {
                resolver.openOutputStream(uri)?.use { out ->
                    writeMarkdownPdfToStream(context, out, title, markdown)
                } ?: throw java.io.IOException("Unable to open output stream for $displayName")
                values.clear()
                values.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
                return uri
            } catch (ex: Exception) {
                try {
                    resolver.delete(uri, null, null)
                } catch (_: Exception) {
                }
                throw ex
            }
        }

        val docsRoot = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOCUMENTS)
        val dir = File(docsRoot, "Eat/ResumeGenerator").apply { mkdirs() }
        val file = File(dir, displayName)
        writeMarkdownPdf(context, file, title, markdown)
        return Uri.fromFile(file)
    }

    private fun writeMarkdownPdfToStream(
        context: Context,
        out: OutputStream,
        title: String,
        markdown: String
    ) {
        val markwon = Markwon.create(context)
        val spanned = markwon.toMarkdown(markdown.trim())

        val pdf = PdfDocument()
        try {
            val titlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.BOLD)
                textSize = 16f
                color = android.graphics.Color.BLACK
            }
            val metaPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.NORMAL)
                textSize = 10f
                color = android.graphics.Color.DKGRAY
            }
            val textPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
                typeface = Typeface.create(Typeface.SERIF, Typeface.NORMAL)
                textSize = 12f
                color = android.graphics.Color.BLACK
            }

            val availableWidth = (PAGE_WIDTH - (MARGIN * 2)).toInt()
            val layout = StaticLayout.Builder.obtain(spanned, 0, spanned.length, textPaint, availableWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setIncludePad(false)
                .setLineSpacing(0f, 1.15f)
                .build()

            val lineCount = layout.lineCount
            var startLine = 0
            var pageNumber = 1
            while (startLine < lineCount) {
                val pageInfo = PdfDocument.PageInfo.Builder(PAGE_WIDTH, PAGE_HEIGHT, pageNumber).create()
                val page = pdf.startPage(pageInfo)
                val canvas = page.canvas

                var y = MARGIN + 18f
                y = drawHeader(canvas, title, titlePaint, metaPaint, y)
                y += 12f

                val bodyTop = y
                val availableHeight = (PAGE_HEIGHT - MARGIN - bodyTop).toInt()
                val startTop = layout.getLineTop(startLine)

                var endLine = startLine
                while (endLine < lineCount) {
                    val bottom = layout.getLineBottom(endLine)
                    if (bottom - startTop > availableHeight) break
                    endLine++
                }
                if (endLine == startLine) {
                    endLine = (startLine + 1).coerceAtMost(lineCount)
                }

                canvas.save()
                canvas.translate(MARGIN, bodyTop)
                canvas.clipRect(0f, 0f, availableWidth.toFloat(), availableHeight.toFloat())
                canvas.translate(0f, -startTop.toFloat())
                layout.draw(canvas)
                canvas.restore()

                pdf.finishPage(page)
                startLine = endLine
                pageNumber++
            }

            pdf.writeTo(out)
        } finally {
            pdf.close()
        }
    }

    private fun drawHeader(
        canvas: Canvas,
        title: String,
        titlePaint: Paint,
        metaPaint: Paint,
        startY: Float
    ): Float {
        var y = startY
        if (title.isNotBlank()) {
            canvas.drawText(title, MARGIN, y, titlePaint)
            y += 16f
        }
        val timestamp = DateFormat.getDateTimeInstance().format(Date())
        canvas.drawText(timestamp, MARGIN, y, metaPaint)
        return y
    }

    private fun wrapText(text: String, paint: Paint, maxWidth: Float): List<String> {
        val normalized = text.replace("\r\n", "\n").replace('\r', '\n')
        val output = mutableListOf<String>()
        for (rawLine in normalized.split('\n')) {
            val line = rawLine.trimEnd()
            if (line.isEmpty()) {
                output.add("")
                continue
            }
            var start = 0
            while (start < line.length) {
                val count = paint.breakText(line, start, line.length, true, maxWidth, null)
                if (count <= 0) break
                val candidate = line.substring(start, start + count)
                output.add(candidate.trimEnd())
                start += count
            }
        }
        if (output.isEmpty()) output.add("")
        return output
    }
}

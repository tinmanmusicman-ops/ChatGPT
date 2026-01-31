package com.example.constrainedapp

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.util.AttributeSet
import androidx.core.content.ContextCompat
import com.github.mikephil.charting.charts.BarChart
import com.github.mikephil.charting.data.BarDataSet

class PerfBarChart @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0,
) : BarChart(context, attrs, defStyleAttr) {

    private val barLabels = mutableMapOf<Int, String>()

    private val baseTextSize = resources.getDimension(R.dimen.chart_memory_label_size)
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF000000.toInt()
        textAlign = Paint.Align.CENTER
        textSize = baseTextSize * 2f
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
    }

    fun setBarLabel(index: Int, label: String?) {
        if (label.isNullOrBlank()) {
            barLabels.remove(index)
        } else {
            barLabels[index] = label
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val data = data ?: return
        val dataSet = data.getDataSetByIndex(0) as? BarDataSet ?: return
        barLabels.forEach { (index, label) ->
            val entry = dataSet.getEntryForIndex(index) ?: return@forEach
            val bounds = RectF()
            getBarBounds(entry, bounds)
            if (bounds.width() <= 0f || bounds.height() <= 0f) {
                return@forEach
            }
            val padding = 8f
            val baseSize = baseTextSize * 1.5f
            labelPaint.textSize = baseSize
            val fm = labelPaint.fontMetrics
            val textHeight = fm.descent - fm.ascent
            var scale = 1f
            val availableHeight = (bounds.height() - padding * 2).coerceAtLeast(0f)
            if (availableHeight > 0f && textHeight > 0f) {
                scale = minOf(scale, availableHeight / textHeight)
            }
            labelPaint.textSize = baseSize * scale
            canvas.save()
            canvas.translate(bounds.centerX(), bounds.centerY())
            canvas.rotate(-90f)
            val baselineOffset = (labelPaint.descent() + labelPaint.ascent()) / 2f
            canvas.drawText(label, 0f, -baselineOffset, labelPaint)
            canvas.restore()
        }
    }
}

package com.example.eat

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.util.AttributeSet
import android.util.Log
import android.view.View
import androidx.core.content.ContextCompat

class HistoryGraphView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    var historyEntries: List<HistoryEntry> = emptyList()
        set(value) {
            field = value.sortedBy { it.timestamp }
            Log.d(TAG, "rendering ${field.size} history entries")
            invalidate()
        }

    var axisDurationMillis: Long? = null
    var windowStartMillis: Long? = null
        set(value) {
            field = value
            invalidate()
        }
    var windowEndMillis: Long? = null
        set(value) {
            field = value
            invalidate()
        }

    init {
        setWillNotDraw(false)
    }

    companion object {
        private const val TAG = "HistoryGraphView"
    }

    private val backgroundPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.panelBackground)
    }
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.onSurface)
        alpha = 80
        strokeWidth = 1.5f
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.onSurface)
        textSize = resources.getDimension(R.dimen.history_graph_label_size)
    }
    private val placeholderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.onSurface)
        textSize = resources.getDimension(R.dimen.history_graph_placeholder_size)
        textAlign = Paint.Align.CENTER
    }
    private val visionLinePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.accent)
        strokeWidth = 3f
        style = Paint.Style.STROKE
    }
    private val visionDotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = ContextCompat.getColor(context, R.color.accent)
        style = Paint.Style.FILL
    }
    private val ateLabelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF4CAF50.toInt()
        textSize = resources.getDimension(R.dimen.history_graph_label_size)
    }
    private val ateDotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF4CAF50.toInt()
        style = Paint.Style.FILL
    }

    private val rect = RectF()
    private val path = Path()
    private val graphPadding = resources.getDimension(R.dimen.history_graph_margin)
    private val tickHeight = resources.getDimension(R.dimen.history_graph_tick_height)
    private val dotRadius = resources.getDimension(R.dimen.history_graph_dot_radius)
    private val cornerRadius = resources.getDimension(R.dimen.history_graph_corner_radius)
    private val placeholderText = context.getString(R.string.history_graph_empty)

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (width == 0 || height == 0) return

        val left = paddingLeft + graphPadding
        val right = width - paddingRight - graphPadding
        val top = paddingTop + graphPadding
        val bottom = height - paddingBottom - graphPadding
        if (right <= left || bottom <= top) return

        rect.set(left, top, right, bottom)
        canvas.drawRoundRect(rect, cornerRadius, cornerRadius, backgroundPaint)

        val tickAreaTop = bottom - tickHeight
        val graphBottom = tickAreaTop - graphPadding
        val graphHeight = (graphBottom - top).coerceAtLeast(1f)
        val graphWidth = (right - left).coerceAtLeast(1f)
        val maxLevel = VisionClarity.values().maxOf { it.level }.coerceAtLeast(1)

        val yForClarity: (VisionClarity) -> Float = { clarity ->
            val ratio = clarity.level.toFloat() / maxLevel
            graphBottom - ratio * graphHeight
        }

        VisionClarity.values().forEach { clarity ->
            val y = yForClarity(clarity)
            canvas.drawLine(left, y, right, y, gridPaint)
            canvas.drawText(clarity.label, left + 8f, y - 4f, labelPaint)
        }
        val ateLabelY = tickAreaTop + tickHeight / 1.5f
        canvas.drawLine(left, ateLabelY, right, ateLabelY, gridPaint)
        canvas.drawText("I Ate", left + 8f, ateLabelY - 4f, ateLabelPaint)
        val ateMarkerY = ateLabelY - tickHeight / 2f

        val now = System.currentTimeMillis()
        val defaultStart = ReminderPrefs.startOfDay(now)
        val fallbackDuration = axisDurationMillis ?: (now - defaultStart).coerceAtLeast(1L)
        val fallbackStart = maxOf(now - fallbackDuration, defaultStart)
        val startTime = windowStartMillis ?: fallbackStart
        val endReference = windowEndMillis ?: now
        val endTime = maxOf(endReference, startTime + 1L)
        val totalDuration = (endTime - startTime).coerceAtLeast(1L).toFloat()

        val xForPosition: (Long) -> Float = { timestamp ->
            val clamped = timestamp.coerceIn(startTime, endTime)
            left + ((clamped - startTime) / totalDuration) * graphWidth
        }

        val visionEntries = historyEntries.filter { it.type == HistoryType.VISION && it.clarity != null }
        if (visionEntries.isNotEmpty()) {
            path.reset()
            visionEntries.forEachIndexed { index, entry ->
                val x = xForPosition(entry.timestamp)
                val y = yForClarity(entry.clarity!!)
                if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                canvas.drawCircle(x, y, dotRadius, visionDotPaint)
            }
            canvas.drawPath(path, visionLinePaint)
        }

        val mealEntries = historyEntries.filter { it.type == HistoryType.I_ATE }
        val snackRadius = dotRadius * 0.6f
        val mealRadius = dotRadius * 1.1f
        mealEntries.forEach { entry ->
            val x = xForPosition(entry.timestamp)
            val radius = when (entry.mealType) {
                MealType.MEAL -> mealRadius
                MealType.SNACK -> snackRadius
                else -> snackRadius
            }
            canvas.drawCircle(x, ateMarkerY, radius, ateDotPaint)
        }

        val hasVisibleEntries = visionEntries.isNotEmpty() || mealEntries.isNotEmpty()
        if (!hasVisibleEntries) {
            val centerX = (left + right) / 2f
            val centerY = (top + tickAreaTop) / 2f
            canvas.drawText(placeholderText, centerX, centerY, placeholderPaint)
        }
    }
}

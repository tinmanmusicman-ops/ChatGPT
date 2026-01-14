package com.example.eat

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import java.util.Locale
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

object NotificationHelper {
    private const val CHANNEL_ID = "eat_reminder_channel"
    private const val CHANNEL_NAME = "Eat Reminders"
    private const val NOTIFICATION_ID = EatWorker.NOTIFICATION_ID
    private const val ACTION_REQUEST_BASE = 1_000

    private val VISION_CHOICES = listOf("Cloudy", "Moderate", "Almost Clear")
    private val MEAL_ACTIONS = listOf(
        MealType.SNACK to "I ate a snack",
        MealType.MEAL to "I ate a full meal"
    )

    fun showNotification(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            return
        }
        ensureChannel(context)

        val ateCompleted = ReminderPrefs.isAteDone(context)
        val visionStatus = ReminderPrefs.getVisionStatus(context)
        val visionPromptPending = ReminderPrefs.isVisionPromptPending(context)
        val contentText = buildContentText(ateCompleted, visionStatus, visionPromptPending)
        val actionIdBase = System.currentTimeMillis()

        val selectionActive = ReminderPrefs.hasActiveSelection(context)
        val builder = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("Eat Reminder")
            .setContentText(contentText)
            .setStyle(NotificationCompat.BigTextStyle().bigText(contentText))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(false)
            .setOnlyAlertOnce(true)

        val showingVisionChoices = visionPromptPending && visionStatus == null
        val selectedMeal = ReminderPrefs.getLastMealType(context)
        if (!showingVisionChoices) {
            MEAL_ACTIONS.forEachIndexed { index, pair ->
                val (mealType, label) = pair
                val selected = mealType == selectedMeal
                builder.addAction(buildMealAction(context, mealType, label, actionIdBase + index, selected))
            }
        }

        when {
            visionStatus != null -> {
                builder.setSubText("Vision: $visionStatus")
                builder.color = 0xFF4CAF50.toInt()
            }
            showingVisionChoices -> {
                builder.setSubText("Vision: selecting")
                addVisionChoiceActions(builder, context, actionIdBase, visionStatus)
            }
        }

        builder.addAction(buildDoneAction(context, actionIdBase + ACTION_REQUEST_BASE, selectionActive))

        if (ateCompleted && visionStatus == null && !showingVisionChoices) {
            builder.color = 0xFF4CAF50.toInt()
        }

        NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, builder.build())
    }

    private fun buildContentText(
        ateCompleted: Boolean,
        visionStatus: String?,
        visionPromptPending: Boolean
    ): String {
        return buildString {
            append("Eat reminder pending.")
            if (ateCompleted) append(" ✓ Ate recorded.")
            if (visionStatus != null) {
                append(" Vision: $visionStatus.")
            } else if (visionPromptPending) {
                append(" Tap to describe your vision.")
            }
        }
    }

    private fun buildMealAction(
        context: Context,
        mealType: MealType,
        label: String,
        actionSeed: Long,
        selected: Boolean
    ): NotificationCompat.Action {
        val mealIntent = Intent(context, NotificationActionReceiver::class.java).apply {
            action = NotificationActionReceiver.ACTION_ATE
            putExtra(NotificationActionReceiver.EXTRA_ACTION_ID, actionSeed)
            putExtra(NotificationActionReceiver.EXTRA_MEAL_TYPE, mealType.name)
        }
        val mealPending = PendingIntent.getBroadcast(
            context,
            ACTION_REQUEST_BASE + mealType.ordinal,
            mealIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val iconRes = if (selected) R.drawable.ic_state_dot_active else R.drawable.ic_state_dot_idle
        return NotificationCompat.Action.Builder(iconRes, label, mealPending).build()
    }

    private fun addVisionChoiceActions(
        builder: NotificationCompat.Builder,
        context: Context,
        actionSeed: Long,
        selectedVision: String?
    ) {
        VISION_CHOICES.forEachIndexed { index, label ->
            val choiceIntent = Intent(context, NotificationActionReceiver::class.java).apply {
                action = NotificationActionReceiver.ACTION_VISION_CHOICE
                putExtra(NotificationActionReceiver.EXTRA_VISION_STATUS, label)
                putExtra(NotificationActionReceiver.EXTRA_ACTION_ID, actionSeed + index + 2)
            }
            val choicePending = PendingIntent.getBroadcast(
                context,
                ACTION_REQUEST_BASE + 2 + index,
                choiceIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            val normalizedSelected = selectedVision?.trim()?.lowercase(Locale.getDefault())
            val normalizedLabel = label.lowercase(Locale.getDefault())
            val selected = normalizedSelected != null && normalizedSelected == normalizedLabel
            val iconRes = if (selected) R.drawable.ic_state_dot_active else R.drawable.ic_state_dot_idle
            builder.addAction(
                NotificationCompat.Action.Builder(
                    iconRes,
                    label,
                    choicePending
                ).build()
            )
        }
    }

    private fun buildDoneAction(context: Context, requestCode: Long, enabled: Boolean): NotificationCompat.Action {
        val doneIntent = Intent(context, NotificationActionReceiver::class.java).apply {
            action = NotificationActionReceiver.ACTION_DONE
            putExtra(NotificationActionReceiver.EXTRA_ACTION_ID, requestCode)
        }
        val donePending = PendingIntent.getBroadcast(
            context,
            ACTION_REQUEST_BASE + 50,
            doneIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val iconRes = if (enabled) {
            R.drawable.ic_state_dot_active
        } else {
            R.drawable.ic_state_dot_idle
        }
        return NotificationCompat.Action.Builder(
            iconRes,
            "Done",
            donePending
        ).build()
    }

    private fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        val channel = NotificationChannel(CHANNEL_ID, CHANNEL_NAME, NotificationManager.IMPORTANCE_HIGH)
        channel.description = "Eat reminders"
        channel.enableVibration(true)
        channel.vibrationPattern = longArrayOf(0, 250, 200, 250)
        manager.createNotificationChannel(channel)
    }
}

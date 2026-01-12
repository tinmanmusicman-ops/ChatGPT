package com.example.eat

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

object NotificationHelper {
    private const val CHANNEL_ID = "eat_reminder_channel"
    private const val CHANNEL_NAME = "Eat Reminders"
    private const val NOTIFICATION_ID = EatWorker.NOTIFICATION_ID
    private const val ACTION_REQUEST_BASE = 1_000

    private val VISION_CHOICES = listOf("Cloudy", "Low", "Good")

    fun showNotification(context: Context) {
        ensureChannel(context)

        val ateCompleted = ReminderPrefs.isAteDone(context)
        val visionStatus = ReminderPrefs.getVisionStatus(context)
        val visionPromptPending = ReminderPrefs.isVisionPromptPending(context)
        val contentText = buildContentText(ateCompleted, visionStatus, visionPromptPending)
        val actionIdBase = System.currentTimeMillis()

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
        if (!showingVisionChoices) {
            val ateAction = buildIAteAction(context, ateCompleted, actionIdBase)
            builder.addAction(ateAction)
        }

        when {
            visionStatus != null -> {
                builder.setSubText("Vision: $visionStatus")
                builder.color = 0xFF4CAF50.toInt()
            }
            showingVisionChoices -> {
                builder.setSubText("Vision: selecting")
                addVisionChoiceActions(builder, context, actionIdBase)
            }
            else -> {
                builder.addAction(buildVisionPromptAction(context, actionIdBase))
            }
        }

        if (!showingVisionChoices) {
            builder.addAction(buildDoneAction(context, actionIdBase + ACTION_REQUEST_BASE))
        }

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

    private fun buildIAteAction(context: Context, ateCompleted: Boolean, actionSeed: Long): NotificationCompat.Action {
        val ateIntent = Intent(context, NotificationActionReceiver::class.java).apply {
            action = NotificationActionReceiver.ACTION_ATE
            putExtra(NotificationActionReceiver.EXTRA_ACTION_ID, actionSeed)
        }
        val atePending = PendingIntent.getBroadcast(
            context,
            ACTION_REQUEST_BASE,
            ateIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val ateLabel = if (ateCompleted) "✓ Ate" else "I Ate"
        val ateIcon = if (ateCompleted) android.R.drawable.presence_online else android.R.drawable.ic_menu_send
        return NotificationCompat.Action.Builder(ateIcon, ateLabel, atePending).build()
    }

    private fun buildVisionPromptAction(context: Context, actionSeed: Long): NotificationCompat.Action {
        val promptIntent = Intent(context, NotificationActionReceiver::class.java).apply {
            action = NotificationActionReceiver.ACTION_VISION_PROMPT
            putExtra(NotificationActionReceiver.EXTRA_ACTION_ID, actionSeed + 1)
        }
        val promptPending = PendingIntent.getBroadcast(
            context,
            ACTION_REQUEST_BASE + 1,
            promptIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Action.Builder(
            android.R.drawable.ic_menu_search,
            "How's My Vision?",
            promptPending
        ).build()
    }

    private fun addVisionChoiceActions(builder: NotificationCompat.Builder, context: Context, actionSeed: Long) {
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
            builder.addAction(
                NotificationCompat.Action.Builder(
                    android.R.drawable.checkbox_on_background,
                    label,
                    choicePending
                ).build()
            )
        }
    }

    private fun buildDoneAction(context: Context, requestCode: Long): NotificationCompat.Action {
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
        return NotificationCompat.Action.Builder(
            android.R.drawable.ic_menu_close_clear_cancel,
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

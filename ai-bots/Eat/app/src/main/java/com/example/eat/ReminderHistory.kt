package com.example.eat

import java.util.Locale

enum class HistoryType {
    REMINDER,
    I_ATE,
    VISION
}

enum class VisionClarity(val label: String, val level: Int) {
    CLOUDY("Cloudy", 0),
    MODERATE("Moderate", 1),
    ALMOST_CLEAR("Almost Clear", 2);

    companion object {
        fun fromLabel(label: String?): VisionClarity? {
            if (label.isNullOrBlank()) return null
            val normalized = label.trim().lowercase(Locale.US)
            return when (normalized) {
                "cloudy" -> CLOUDY
                "moderate", "low" -> MODERATE
                "almost clear", "good", "vision is good" -> ALMOST_CLEAR
                else -> values().firstOrNull {
                    it.label.lowercase(Locale.US) == normalized
                }
            }
        }
    }
}

enum class MealType(val label: String) {
    SNACK("Snack"),
    MEAL("Meal");

    companion object {
        fun fromLabel(label: String?): MealType? {
            if (label.isNullOrBlank()) return null
            return when (label.trim().lowercase(Locale.US)) {
                "snack" -> SNACK
                "meal", "full meal", "full" -> MEAL
                else -> values().firstOrNull { it.label.lowercase(Locale.US) == label.trim().lowercase(Locale.US) }
            }
        }
    }
}

data class HistoryEntry(
    val timestamp: Long,
    val type: HistoryType,
    val clarity: VisionClarity? = null,
    val mealType: MealType? = null
) {
    fun describe(): String {
        return when (type) {
            HistoryType.VISION -> clarity?.label ?: "Vision"
            HistoryType.I_ATE -> "Ate"
            HistoryType.REMINDER -> "Reminder"
        }
    }
}

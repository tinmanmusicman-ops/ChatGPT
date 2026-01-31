package com.example.constrainedapp

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import java.util.concurrent.atomic.AtomicReference

class AmbientTempMonitor(context: Context) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val ambientSensor = sensorManager.getDefaultSensor(Sensor.TYPE_AMBIENT_TEMPERATURE)
    private val lastValue = AtomicReference<Float?>(null)

    fun start() {
        ambientSensor?.let { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
    }

    fun stop() {
        ambientSensor?.let {
            sensorManager.unregisterListener(this, it)
        }
    }

    fun latestAmbientF(): Float? = lastValue.get()

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_AMBIENT_TEMPERATURE) {
            return
        }
        val celsius = event.values.firstOrNull() ?: return
        lastValue.set(celsiusToFahrenheit(celsius))
    }

    override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {
        // No-op
    }

    companion object {
        private fun celsiusToFahrenheit(celsius: Float): Float = (celsius * 9f / 5f) + 32f
    }
}

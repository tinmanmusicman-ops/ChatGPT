package com.example.constrainedapp

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Looper
import android.util.Log
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class AmbientWeatherMonitor(private val context: Context) {
    private val locationManager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
    private val latestAmbientC = AtomicReference<Float?>(null)
    private val executor = Executors.newSingleThreadScheduledExecutor()
    private var future: ScheduledFuture<*>? = null
    @Volatile private var isRunning = false

    fun start() {
        if (isRunning) {
            return
        }
        isRunning = true
        scheduleNext(0, TimeUnit.SECONDS)
    }

    fun stop() {
        isRunning = false
        future?.cancel(false)
        future = null
    }

    fun latestAmbientF(): Float? = latestAmbientC.get()?.let { celsiusToFahrenheit(it) }

    private fun scheduleNext(delay: Long, unit: TimeUnit) {
        if (!isRunning) {
            return
        }
        future = executor.schedule(
            {
                if (!isRunning) {
                    return@schedule
                }
                val success = fetchAmbientTemperature()
                val nextDelay = if (success) NORMAL_REFRESH_MINUTES.toLong() else RETRY_SECONDS.toLong()
                val nextUnit = if (success) TimeUnit.MINUTES else TimeUnit.SECONDS
                scheduleNext(nextDelay, nextUnit)
            },
            delay,
            unit,
        )
    }

    private fun fetchAmbientTemperature(): Boolean {
        val location = determineLocation()
        if (location == null) {
            Log.w(TAG, "Ambient weather fetch skipped: location unavailable")
            return false
        }
        val (latitude, longitude) = location
        Log.d(TAG, "Fetching ambient weather at lat=$latitude lon=$longitude")
        val url = "https://api.open-meteo.com/v1/forecast?latitude=$latitude&longitude=$longitude&current_weather=true&temperature_unit=celsius"
        var success = false
        try {
            val connection = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 5000
                readTimeout = 5000
                requestMethod = "GET"
            }
            connection.inputStream.bufferedReader().use { reader ->
                val payload = reader.readText()
                val current = JSONObject(payload).optJSONObject("current_weather")
                val temp = current?.optDouble("temperature", Double.NaN)
                if (temp != null && !temp.isNaN()) {
                    Log.d(TAG, "Ambient temperature received ${temp}°C (${celsiusToFahrenheit(temp.toFloat())}°F)")
                    latestAmbientC.set(temp.toFloat())
                    success = true
                }
            }
            connection.disconnect()
        } catch (ex: Exception) {
            Log.w(TAG, "Ambient weather fetch failed", ex)
        }
        return success
    }

    private fun determineLocation(): Pair<Double, Double>? {
        val hasFine = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_COARSE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) {
            Log.w(TAG, "Location permission not granted for ambient weather")
            return null
        }

        val providers = buildList {
            if (hasFine) {
                add(LocationManager.GPS_PROVIDER)
            }
            add(LocationManager.NETWORK_PROVIDER)
            add(LocationManager.PASSIVE_PROVIDER)
        }.distinct()

        providers.forEach { provider ->
            val last = tryGetLastKnownLocation(provider)
            if (last != null) {
                return last.latitude to last.longitude
            }
        }

        providers.forEach { provider ->
            val current = tryGetCurrentLocation(provider)
            if (current != null) {
                return current.latitude to current.longitude
            }
        }

        Log.w(TAG, "Location unavailable (no last-known or current fix)")
        return null
    }

    private fun tryGetLastKnownLocation(provider: String): Location? {
        val manager = locationManager ?: return null
        val enabled = try {
            manager.isProviderEnabled(provider)
        } catch (ex: Exception) {
            false
        }
        if (!enabled) {
            return null
        }
        return try {
            manager.getLastKnownLocation(provider)
        } catch (ex: SecurityException) {
            null
        } catch (ex: IllegalArgumentException) {
            null
        }
    }

    private fun tryGetCurrentLocation(provider: String): Location? {
        val manager = locationManager ?: return null
        val enabled = try {
            manager.isProviderEnabled(provider)
        } catch (ex: Exception) {
            false
        }
        if (!enabled) {
            return null
        }

        val latch = CountDownLatch(1)
        val result = AtomicReference<Location?>(null)

        try {
            if (Build.VERSION.SDK_INT >= 30) {
                manager.getCurrentLocation(
                    provider,
                    null,
                    context.mainExecutor,
                ) { location ->
                    result.set(location)
                    latch.countDown()
                }
            } else {
                @Suppress("DEPRECATION")
                manager.requestSingleUpdate(
                    provider,
                    object : LocationListener {
                        override fun onLocationChanged(location: Location) {
                            result.set(location)
                            latch.countDown()
                            try {
                                manager.removeUpdates(this)
                            } catch (_: Exception) {
                            }
                        }

                        @Deprecated("Deprecated in Java")
                        override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit

                        override fun onProviderEnabled(provider: String) = Unit

                        override fun onProviderDisabled(provider: String) = Unit
                    },
                    Looper.getMainLooper(),
                )
            }
        } catch (ex: SecurityException) {
            return null
        } catch (ex: IllegalArgumentException) {
            return null
        }

        latch.await(3, TimeUnit.SECONDS)
        return result.get()
    }

    companion object {
        private const val TAG = "AmbientWeatherMonitor"
        private const val NORMAL_REFRESH_MINUTES = 5
        private const val RETRY_SECONDS = 15

        private fun celsiusToFahrenheit(celsius: Float): Float = (celsius * 9f / 5f) + 32f
    }
}

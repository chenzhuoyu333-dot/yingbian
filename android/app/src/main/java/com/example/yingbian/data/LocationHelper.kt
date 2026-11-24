package com.example.yingbian.data

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * 一次性的位置读取。
 *
 * 刻意不用 FusedLocationProviderClient：国产手机通常没有 Google Play 服务，
 * 用了会在真机上直接失败。这里只用系统自带的 LocationManager。
 */
class LocationHelper(private val context: Context) {

    fun hasPermission(): Boolean =
        ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.ACCESS_COARSE_LOCATION,
            ) == PackageManager.PERMISSION_GRANTED

    /**
     * 取一次最近的位置，取不到返回 null。
     *
     * 用户可能只给了粗略定位，也可能在室内没有 GPS；调用方必须允许降级，
     * 不能因为这里返回 null 就崩掉或卡住。
     */
    fun lastKnown(): Pair<Double, Double>? {
        val best = lastKnownLocation() ?: return null
        return best.latitude to best.longitude
    }

    private fun lastKnownLocation(): Location? {
        if (!hasPermission()) return null
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return null

        val providers = listOf(
            LocationManager.NETWORK_PROVIDER,
            LocationManager.GPS_PROVIDER,
            LocationManager.PASSIVE_PROVIDER,
        )
        val candidates = providers.mapNotNull { provider ->
            runCatching {
                if (manager.isProviderEnabled(provider)) {
                    manager.getLastKnownLocation(provider)
                } else {
                    null
                }
            }.getOrNull()
        }
        return candidates.maxByOrNull { it.time }
    }

    /**
     * 主动拿一次当前位置：缓存太旧就等一个新的定位点，最多等 timeoutMs。
     *
     * 只用 lastKnown 在室内经常是空的，用户点了“定位”会以为功能没做。
     * 这里不依赖 Google 服务，只向系统要一次；超时就退回缓存，不阻塞界面。
     */
    suspend fun currentLocation(timeoutMs: Long = 8_000): Pair<Double, Double>? {
        if (!hasPermission()) return null
        val cached = lastKnownLocation()
        if (cached != null && System.currentTimeMillis() - cached.time < 30_000) {
            return cached.latitude to cached.longitude
        }
        val manager = context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return cached?.let { it.latitude to it.longitude }
        val fine = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.ACCESS_FINE_LOCATION,
        ) == PackageManager.PERMISSION_GRANTED
        val providers = buildList {
            add(LocationManager.NETWORK_PROVIDER)
            if (fine) add(LocationManager.GPS_PROVIDER)
            add(LocationManager.PASSIVE_PROVIDER)
        }.filter { runCatching { manager.isProviderEnabled(it) }.getOrDefault(false) }
        if (providers.isEmpty()) return cached?.let { it.latitude to it.longitude }

        return suspendCancellableCoroutine { continuation ->
            val handler = Handler(Looper.getMainLooper())
            var finished = false

            fun finish(point: Pair<Double, Double>?) {
                if (finished) return
                finished = true
                handler.removeCallbacksAndMessages(null)
                continuation.resume(point)
            }

            val listener = object : LocationListener {
                override fun onLocationChanged(location: Location) {
                    runCatching { manager.removeUpdates(this) }
                    finish(location.latitude to location.longitude)
                }

                override fun onProviderEnabled(provider: String) = Unit
                override fun onProviderDisabled(provider: String) = Unit
                @Deprecated("Deprecated in Java")
                override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
            }

            providers.forEach { provider ->
                runCatching {
                    manager.requestLocationUpdates(provider, 0L, 0f, listener, Looper.getMainLooper())
                }
            }
            handler.postDelayed(
                {
                    runCatching { manager.removeUpdates(listener) }
                    finish(cached?.let { it.latitude to it.longitude })
                },
                timeoutMs,
            )
            continuation.invokeOnCancellation {
                runCatching { manager.removeUpdates(listener) }
                handler.removeCallbacksAndMessages(null)
            }
        }
    }
}

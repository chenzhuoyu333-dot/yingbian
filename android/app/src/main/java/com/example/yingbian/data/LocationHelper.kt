package com.example.yingbian.data

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.core.content.ContextCompat

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
        val best = candidates.maxByOrNull { it.time } ?: return null
        return best.latitude to best.longitude
    }
}

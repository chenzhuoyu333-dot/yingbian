package com.example.yingbian.data

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.example.yingbian.MainActivity
import com.example.yingbian.R
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 行程中的后台位置检查。
 *
 * 只做两件事：每 60 秒取一次系统定位、问后端“我到了还是落后了”。
 * 到了或落后才发一条通知；其余时间只保留一条低打扰的常驻通知。
 * 不记录轨迹、不上传历史位置，用户关掉开关服务就停。
 */
class TripTrackingService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var helper: LocationHelper
    private lateinit var settings: ApiSettings
    private lateinit var repo: PlanRepository
    private var lastAlertKey = ""

    override fun onCreate() {
        super.onCreate()
        helper = LocationHelper(this)
        settings = ApiSettings(this)
        repo = createRepository(this, settings)
        createChannel()
        showForeground("正在每 60 秒检查一次位置")
        scope.launch { loop() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            settings.trackingEnabled = false
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    private suspend fun loop() {
        while (currentCoroutineContext().isActive) {
            runCatching { tick() }
            delay(INTERVAL_MS)
        }
    }

    private suspend fun tick() {
        if (!helper.hasPermission()) return
        if (settings.lastPlanId.isBlank()) return
        val point = helper.currentLocation(8_000) ?: return
        val result = repo.locate(point.first, point.second)
        TrackBus.publish(result)
        if (!result.arrived && !result.isBehind) return
        val key = if (result.arrived) "arrive:${result.atNodeId}" else "behind:${result.shouldNodeId}"
        if (key == lastAlertKey) return
        lastAlertKey = key
        val text = if (result.arrived) {
            "已到「${result.atNodeTitle}」 · 打开应变勾选确认"
        } else {
            "落后约 ${result.driftMinutes} 分钟 · 打开看看怎么改"
        }
        showForeground(text)
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < 26) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager ?: return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "行程中位置提醒",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "行程中每 60 秒检查一次是否到达；到点或落后才提醒"
            setShowBadge(false)
        }
        manager.createNotificationChannel(channel)
    }

    private fun showForeground(text: String) {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, TripTrackingService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_trip)
            .setContentTitle("应变 · 行程中")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .addAction(0, "停止检测", stop)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_STOP = "com.example.yingbian.STOP_TRACKING"
        private const val CHANNEL_ID = "trip_tracking"
        private const val NOTIFICATION_ID = 4101
        private const val INTERVAL_MS = 60_000L
    }
}

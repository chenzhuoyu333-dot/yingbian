package com.example.yingbian.data

import android.content.Context
import com.example.yingbian.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Build-flavor defaults; runtime overrides live in [ApiSettings]. */
object ApiConfig {
    val defaultBase: String = BuildConfig.DEFAULT_BASE
    val defaultMock: Boolean = BuildConfig.DEFAULT_MOCK
}

/**
 * One place for the backend address and the mock switch.
 * Stored in SharedPreferences so a changed IP survives restarts and reinstalls of the same APK.
 */
class ApiSettings(context: Context) {
    private val prefs =
        context.applicationContext.getSharedPreferences("yingbian_api", Context.MODE_PRIVATE)

    /** 记住连成功过的地址，下次自动寻找先试这些（快很多） */
    var lastKnownBases: List<String>
        get() = prefs.getString(KEY_KNOWN, "")
            ?.split("|")
            ?.filter { it.isNotBlank() }
            .orEmpty()
        set(value) {
            val merged = (value + lastKnownBases).distinct().take(5)
            prefs.edit().putString(KEY_KNOWN, merged.joinToString("|")).apply()
        }

    var baseUrl: String
        get() = prefs.getString(KEY_BASE, null)?.takeIf { it.isNotBlank() } ?: ApiConfig.defaultBase
        set(value) = prefs.edit().putString(KEY_BASE, normalize(value)).apply()

    var useMock: Boolean
        get() = prefs.getBoolean(KEY_MOCK, ApiConfig.defaultMock)
        set(value) = prefs.edit().putBoolean(KEY_MOCK, value).apply()

    /** 上次打开的行程；重开 App 时接着看这一份，而不是回到内置演示 */
    var lastPlanId: String
        get() = prefs.getString(KEY_LAST_PLAN, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_LAST_PLAN, value.trim()).apply()

    /** 行程中后台自动检测位置（前台服务，会有常驻通知）。 */
    var trackingEnabled: Boolean
        get() = prefs.getBoolean(KEY_TRACKING, false)
        set(value) = prefs.edit().putBoolean(KEY_TRACKING, value).apply()

    /** 本机已确认到达的节点；只存在本机，不上传，也不等于“锁定”。 */
    fun arrivedNodes(planId: String): Set<String> {
        if (planId.isBlank()) return emptySet()
        return prefs.getString(KEY_ARRIVED + planId, "").orEmpty()
            .split("|")
            .filter { it.isNotBlank() }
            .toSet()
    }

    fun markArrived(planId: String, nodeId: String) {
        if (planId.isBlank() || nodeId.isBlank()) return
        val merged = arrivedNodes(planId) + nodeId
        prefs.edit().putString(KEY_ARRIVED + planId, merged.joinToString("|")).apply()
    }

    val hasCustomBase: Boolean
        get() = prefs.getString(KEY_BASE, null) != null

    /**
     * 多人协作的身份。memberId 首次使用时生成并持久化，
     * 昵称可以在设置页改 —— 演示时一台手机叫"张队长"、另一台叫"李队友"。
     */
    val memberId: String
        get() {
            val existing = prefs.getString(KEY_MEMBER_ID, null)
            if (!existing.isNullOrBlank()) return existing
            val generated = "u_" + java.util.UUID.randomUUID().toString().take(8)
            prefs.edit().putString(KEY_MEMBER_ID, generated).apply()
            return generated
        }

    var memberName: String
        get() = prefs.getString(KEY_MEMBER_NAME, null)?.takeIf { it.isNotBlank() }
            ?: ("成员" + memberId.takeLast(2))
        set(value) = prefs.edit().putString(KEY_MEMBER_NAME, value.trim()).apply()

    fun reset() {
        prefs.edit().remove(KEY_BASE).remove(KEY_MOCK).apply()
    }

    fun normalize(raw: String): String {
        var value = raw.trim()
        if (value.isEmpty()) return ""
        if (!value.startsWith("http://") && !value.startsWith("https://")) {
            value = "http://$value"
        }
        return value.trimEnd('/')
    }

    private companion object {
        private const val KEY_KNOWN = "known_bases"
        const val KEY_BASE = "base_url"
        const val KEY_MOCK = "use_mock"
        const val KEY_MEMBER_ID = "member_id"
        const val KEY_MEMBER_NAME = "member_name"
        const val KEY_LAST_PLAN = "last_plan_id"
        const val KEY_TRACKING = "trip_tracking"
        const val KEY_ARRIVED = "arrived_nodes_"
    }
}

/** Returns a human readable result, e.g. "通 · 周六古镇一日游（12 个节点）". */
suspend fun verifyConnection(base: String): String = withContext(Dispatchers.IO) {
    var connection: HttpURLConnection? = null
    try {
        val url = base.trim().trimEnd('/') + "/api/plan/p_sat_guzhen"
        connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = "GET"
        connection.connectTimeout = 5_000
        connection.readTimeout = 8_000
        val code = connection.responseCode
        val text = (if (code in 200..299) connection.inputStream else connection.errorStream)
            ?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        if (code !in 200..299) return@withContext "连不上：HTTP $code"
        val root = JSONObject(text)
        if (!root.optBoolean("ok", false)) {
            val message = root.optJSONObject("error")?.optString("message") ?: "返回异常"
            return@withContext "连不上：$message"
        }
        val plan = root.getJSONObject("data").getJSONObject("plan")
        val nodes = plan.optJSONArray("nodes")?.length() ?: 0
        "通 · ${plan.optString("title")}（$nodes 个节点）"
    } catch (exc: Exception) {
        "连不上：${exc.message ?: exc.javaClass.simpleName}"
    } finally {
        connection?.disconnect()
    }
}

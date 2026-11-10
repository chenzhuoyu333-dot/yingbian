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

    var baseUrl: String
        get() = prefs.getString(KEY_BASE, null)?.takeIf { it.isNotBlank() } ?: ApiConfig.defaultBase
        set(value) = prefs.edit().putString(KEY_BASE, normalize(value)).apply()

    var useMock: Boolean
        get() = prefs.getBoolean(KEY_MOCK, ApiConfig.defaultMock)
        set(value) = prefs.edit().putBoolean(KEY_MOCK, value).apply()

    val hasCustomBase: Boolean
        get() = prefs.getString(KEY_BASE, null) != null

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
        const val KEY_BASE = "base_url"
        const val KEY_MOCK = "use_mock"
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

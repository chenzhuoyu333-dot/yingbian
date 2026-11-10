package com.example.yingbian.data

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

interface PlanRepository {
    suspend fun loadPlan(): Plan
    suspend fun sendEvent(scenario: DemoScenario = DemoScenario.RAIN): Impact
    suspend fun repair(scenario: DemoScenario = DemoScenario.RAIN): RepairResult
    suspend fun applyScheme(scheme: RepairScheme): Plan
    suspend fun undo(): Plan
    suspend fun setLocked(nodeId: String, locked: Boolean): Plan
    suspend fun reset(): Plan
    suspend fun weather(): Weather
    fun cachedPlan(): Plan?
}

enum class DemoScenario { RAIN, CANCEL_LUNCH }

fun createRepository(context: Context): PlanRepository =
    createRepository(context, ApiSettings(context))

fun createRepository(context: Context, settings: ApiSettings): PlanRepository =
    if (settings.useMock) MockPlanRepository(context.applicationContext)
    else RemotePlanRepository(context.applicationContext, settings)

class MockPlanRepository(private val context: Context) : PlanRepository {
    private var current: Plan? = null
    private val history = mutableListOf<Plan>()
    private var blockedMode = false

    private fun readAsset(name: String): JSONObject {
        val text = context.assets.open("fixtures/$name").bufferedReader().use { it.readText() }
        return JSONObject(text)
    }

    override suspend fun loadPlan(): Plan {
        delay(600)
        return current ?: PlanJson
            .parsePlan(readAsset("plan-saturday.json").getJSONObject("data").getJSONObject("plan"))
            .also { current = it }
    }

    override suspend fun sendEvent(scenario: DemoScenario): Impact {
        delay(600)
        val name = if (scenario == DemoScenario.CANCEL_LUNCH) "event-cancel-T3.json" else "event-rain-T1.json"
        return PlanJson.parseImpact(readAsset(name).getJSONObject("data"))
    }

    override suspend fun repair(scenario: DemoScenario): RepairResult {
        delay(500)
        val name = when {
            blockedMode -> "blocked-T4.json"
            scenario == DemoScenario.CANCEL_LUNCH -> "repair-T3.json"
            else -> "repair-T1.json"
        }
        return PlanJson.parseRepair(readAsset(name).getJSONObject("data"))
    }

    override suspend fun applyScheme(scheme: RepairScheme): Plan {
        val base = current ?: loadPlan()
        history.add(base)
        val updated = applyActions(base, scheme.actions)
        current = updated
        return updated
    }

    override suspend fun undo(): Plan {
        val restored = if (history.isEmpty()) current ?: loadPlan() else history.removeAt(history.lastIndex)
        current = restored
        return restored
    }

    override suspend fun setLocked(nodeId: String, locked: Boolean): Plan {
        blockedMode = locked && nodeId == "n_sunset"
        val base = current ?: loadPlan()
        val updated = base.copy(
            nodes = base.nodes.map { node ->
                if (node.id == nodeId) node.copy(confirmed = locked) else node
            },
        )
        current = updated
        return updated
    }

    override suspend fun weather(): Weather {
        delay(200)
        return PlanJson.parseWeather(readAsset("weather.json").getJSONObject("data"))
    }

    override suspend fun reset(): Plan {
        history.clear()
        blockedMode = false
        current = PlanJson.parsePlan(
            readAsset("plan-saturday.json").getJSONObject("data").getJSONObject("plan"),
        )
        return current!!
    }

    override fun cachedPlan(): Plan? = current
}

class RemotePlanRepository(
    private val context: Context,
    private val settings: ApiSettings,
) : PlanRepository {
    private val prefs = context.getSharedPreferences("yingbian_cache", Context.MODE_PRIVATE)
    private val planId = "p_sat_guzhen"

    private fun rainBody(): JSONObject = JSONObject()
        .put("type", "rain")
        .put("from", "15:00")
        .put("to", "17:00")
        .put("prob", 0.7)

    private fun cancelBody(): JSONObject = JSONObject()
        .put("type", "cancel")
        .put("nodeId", "n_lunch")

    private fun eventBody(scenario: DemoScenario): JSONObject =
        if (scenario == DemoScenario.CANCEL_LUNCH) cancelBody() else rainBody()

    private suspend fun request(
        method: String,
        path: String,
        body: JSONObject? = null,
    ): JSONObject = withContext(Dispatchers.IO) {
        val connection = URL(settings.baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 4_000
            connection.readTimeout = 8_000
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            if (body != null) {
                connection.doOutput = true
                connection.outputStream.use { output ->
                    output.write(body.toString().toByteArray(Charsets.UTF_8))
                }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw IOException("HTTP $code：$text")
            val root = JSONObject(text)
            if (!root.optBoolean("ok", false)) {
                val message = root.optJSONObject("error")?.optString("message") ?: "请求失败"
                throw IOException(message)
            }
            root.getJSONObject("data")
        } finally {
            connection.disconnect()
        }
    }

    private fun savePlan(raw: JSONObject) {
        prefs.edit().putString("plan", raw.toString()).apply()
    }

    override suspend fun loadPlan(): Plan {
        val data = request("GET", "/api/plan/$planId")
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun sendEvent(scenario: DemoScenario): Impact =
        PlanJson.parseImpact(request("POST", "/api/plan/$planId/event", eventBody(scenario)))

    override suspend fun repair(scenario: DemoScenario): RepairResult {
        val schemes = JSONArray().put("A").put("B").put("C")
        val body = JSONObject().put("event", eventBody(scenario)).put("schemes", schemes)
        return PlanJson.parseRepair(request("POST", "/api/plan/$planId/repair", body))
    }

    override suspend fun applyScheme(scheme: RepairScheme): Plan {
        val actions = JSONArray()
        scheme.actions.forEach { action ->
            actions.put(
                JSONObject()
                    .put("nodeId", action.nodeId)
                    .put("action", action.action)
                    .put("payload", JSONObject(action.payload))
                    .put("reason", action.reason)
                    .put("sacrifice", action.sacrifice),
            )
        }
        val body = JSONObject().put("schemeId", scheme.id).put("actions", actions)
        val data = request("POST", "/api/plan/$planId/apply", body)
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun undo(): Plan {
        val data = request("POST", "/api/plan/$planId/undo")
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun setLocked(nodeId: String, locked: Boolean): Plan {
        val body = JSONObject()
            .put("planId", planId)
            .put("nodeId", nodeId)
            .put("confirmed", locked)
        val data = request("POST", "/api/debug/lock", body)
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun weather(): Weather =
        PlanJson.parseWeather(request("GET", "/api/weather?lat=30.1&lng=120.2"))

    override suspend fun reset(): Plan = loadPlan()

    override fun cachedPlan(): Plan? {
        val text = prefs.getString("plan", null) ?: return null
        return runCatching { PlanJson.parsePlan(JSONObject(text)) }.getOrNull()
    }
}

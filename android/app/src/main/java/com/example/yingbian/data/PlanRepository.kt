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
    /** 按偏好生成一份新行程（后端 /api/generate） */
    suspend fun generate(prefs: GeneratePrefs): Plan
    suspend fun sendEvent(scenario: DemoScenario = DemoScenario.RAIN): Impact
    suspend fun repair(scenario: DemoScenario = DemoScenario.RAIN): RepairResult
    suspend fun applyScheme(scheme: RepairScheme): Plan
    suspend fun undo(): Plan
    suspend fun setLocked(nodeId: String, locked: Boolean): Plan
    suspend fun reset(): Plan
    /** 取天气；有定位时传经纬度，没有时使用后端默认位置。 */
    suspend fun weather(lat: Double? = null, lng: Double? = null): Weather
    fun cachedPlan(): Plan?

    // ── 多人协作 ──────────────────────────────────
    /** 加入行程（幂等），返回当前成员列表 */
    suspend fun join(): List<MemberInfo>
    /** 当前投票轮次；没有进行中的投票返回 null */
    suspend fun voteState(): VoteState?
    /** 发起投票（影响大的变化不该由谁手快决定） */
    suspend fun startVote(defaultScheme: String = "B", ttlSec: Int = 300): VoteState
    /** 投一票 */
    suspend fun castVote(schemeId: String): VoteState
    /** 谁在什么时候改了什么 */
    suspend fun activity(): List<ActivityRow>
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

    /**
     * 离线模式下没有 POI 检索能力，所以生成只能拿内置示例顶替。
     * 界面上要靠 plan.source/note 让用户看出"这不是真生成"。
     */
    override suspend fun generate(prefs: GeneratePrefs): Plan {
        delay(600)
        history.clear()
        blockedMode = false
        val loaded = PlanJson.parsePlan(
            readAsset("plan-saturday.json").getJSONObject("data").getJSONObject("plan"),
        )
        current = loaded
        return loaded
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

    override suspend fun weather(lat: Double?, lng: Double?): Weather {
        delay(200)
        return PlanJson.parseWeather(readAsset("weather.json").getJSONObject("data"))
    }

    // 离线模式没有后端，多人协作不可用。这里如实报错，
    // 不返回假数据 —— 否则演示时会以为投票成功了。
    override suspend fun join(): List<MemberInfo> = emptyList()

    override suspend fun voteState(): VoteState? = null

    override suspend fun startVote(defaultScheme: String, ttlSec: Int): VoteState =
        throw IOException("离线模式不支持多人协作，请连上后端")

    override suspend fun castVote(schemeId: String): VoteState =
        throw IOException("离线模式不支持多人协作，请连上后端")

    override suspend fun activity(): List<ActivityRow> = emptyList()

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

    /**
     * 当前正在操作的计划 id。
     * 生成行程后会变（后端返回 p_generated），之后的 /event /repair /apply /undo
     * 都必须打到新计划上，否则会去改内置的那份，演示就串了。
     */
    @Volatile
    private var planId = "p_sat_guzhen"

    /** 客户端看到的最新版本号，apply 时作为 expectedVersion 发回去 */
    @Volatile
    private var planVersion = 1

    private fun rainBody(): JSONObject = JSONObject()
        .put("type", "rain")
        .put("from", "15:00")
        .put("to", "17:00")
        .put("prob", 0.7)

    private fun cancelBody(): JSONObject = JSONObject()
        .put("type", "cancel")
        .put("nodeId", "n_lunch")

    private fun eventBody(scenario: DemoScenario): JSONObject {
        val body = if (scenario == DemoScenario.CANCEL_LUNCH) cancelBody() else rainBody()
        return body.put("memberId", settings.memberId)
    }

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
        planVersion = raw.optInt("version", data.optInt("version", 1))
        return PlanJson.parsePlan(raw)
    }

    override suspend fun generate(prefs: GeneratePrefs): Plan {
        val body = JSONObject()
            .put("city", prefs.city)
            .put("date", prefs.date)
            .put("startTime", prefs.startTime)
            .put("endTime", prefs.endTime)
            .put("interests", JSONArray(prefs.interests))
            .put("mustVisit", JSONArray(prefs.mustVisit))
            .put("avoid", JSONArray(prefs.avoid))
            .put("pace", prefs.pace)
            .put("maxTransitMin", prefs.maxTransitMin)

        val data = request("POST", "/api/generate", body)
        val raw = data.getJSONObject("plan")
        // 切到新生成的计划：后面所有请求都要打到它身上
        planId = raw.optString("planId", planId).ifBlank { planId }
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
        val body = JSONObject()
            .put("schemeId", scheme.id)
            .put("actions", actions)
            .put("memberId", settings.memberId)
            // 乐观锁：带上我看到的那一版；别人已经改过就会被后端拒绝并提示刷新
            .put("expectedVersion", planVersion)
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

    override suspend fun weather(lat: Double?, lng: Double?): Weather {
        val query = if (lat != null && lng != null) {
            "?lat=$lat&lng=$lng"
        } else {
            "?lat=30.1&lng=120.2"
        }
        return PlanJson.parseWeather(request("GET", "/api/weather$query"))
    }

    // ── 多人协作 ──────────────────────────────────
    override suspend fun join(): List<MemberInfo> {
        val body = JSONObject()
            .put("memberId", settings.memberId)
            .put("name", settings.memberName)
        return PlanJson.parseMembers(request("POST", "/api/plan/$planId/members", body))
    }

    override suspend fun voteState(): VoteState? {
        val data = request("GET", "/api/plan/$planId/vote")
        val vote = data.optJSONObject("vote") ?: return null
        return PlanJson.parseVote(vote)
    }

    override suspend fun startVote(defaultScheme: String, ttlSec: Int): VoteState {
        val body = JSONObject()
            .put("memberId", settings.memberId)
            .put("event", eventBody(DemoScenario.RAIN))
            .put("defaultScheme", defaultScheme)
            .put("ttlSec", ttlSec)
        return PlanJson.parseVote(request("POST", "/api/plan/$planId/vote/start", body))
    }

    override suspend fun castVote(schemeId: String): VoteState {
        val body = JSONObject()
            .put("memberId", settings.memberId)
            .put("schemeId", schemeId)
        return PlanJson.parseVote(request("POST", "/api/plan/$planId/vote", body))
    }

    override suspend fun activity(): List<ActivityRow> =
        PlanJson.parseActivity(request("GET", "/api/plan/$planId/activity"))

    override suspend fun reset(): Plan = loadPlan()

    override fun cachedPlan(): Plan? {
        val text = prefs.getString("plan", null) ?: return null
        return runCatching { PlanJson.parsePlan(JSONObject(text)) }.getOrNull()
    }
}

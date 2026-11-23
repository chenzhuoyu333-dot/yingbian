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

    /** 某个节点延后若干分钟（管家的"来不及了/落后"提醒走这条路） */
    suspend fun sendDelay(nodeId: String, minutes: Int): Impact
    suspend fun repair(scenario: DemoScenario = DemoScenario.RAIN): RepairResult
    /** 主动到达打卡；晚到时后端返回影响和可执行方案，不共享实时轨迹。 */
    suspend fun checkin(
        nodeId: String?,
        minutes: Int,
        personId: String? = null,
    ): CheckinResult
    suspend fun applyScheme(scheme: RepairScheme): Plan
    suspend fun undo(): Plan
    /** 撤销前先取“会退回什么”，界面上弹确认框用 */
    suspend fun undoPreview(): UndoPreview
    /** 生成后补/改住宿：只重算酒店节点和紧邻通勤 */
    suspend fun updateLodging(lodging: String): Plan
    /** 调整某站停留时长，同一天后面的站点整体顺延 */
    suspend fun updateStay(nodeId: String, minutes: Int): Plan
    suspend fun setLocked(nodeId: String, locked: Boolean): Plan
    suspend fun reset(): Plan
    /** 取天气；有定位时传经纬度。行程天气请用 planWeather()。 */
    suspend fun weather(lat: Double? = null, lng: Double? = null): Weather

    /**
     * 按"这份行程在哪"取天气。
     * 返回 null 表示这份行程没有坐标（或还没生成）——
     * 这时界面就不展示天气，而不是拿默认城市冒充。
     */
    suspend fun planWeather(): Weather?

    fun cachedPlan(): Plan?

    // ── 首页：我的计划 ────────────────────────────
    /** 历史行程列表（最近改过的排前面） */
    suspend fun plans(): List<PlanSummary>
    /** 一句话新建：交给后端 AI 解析偏好再排行程 */
    suspend fun generateFromText(
        text: String,
        startDate: String? = null,
        endDate: String? = null,
        city: String? = null,
        days: Int? = null,
        lodging: String = "",
        pace: String = "normal",
        maxTransitMin: Int? = null,
        avoidWalking: Boolean = false,
        startPlace: String? = null,
        startLat: Double? = null,
        startLng: Double? = null,
    ): Plan
    /** 切换到某份已有行程 */
    suspend fun openPlan(planId: String): Plan
    /** 删除自己生成的行程 */
    suspend fun deletePlan(planId: String)

    /** 省 → 市清单，新建行程时选目的地用 */
    suspend fun regions(): List<Province>

    /** 主动巡检：不等用户点，先发现该改计划了 */
    suspend fun patrol(now: String? = null, lat: Double? = null, lng: Double? = null): PatrolResult

    /**
     * 按当前位置判断是否落后于计划。
     * now 传 "HH:mm" 可以在演示时模拟"现在是下午五点"；不传就用服务器当前时间。
     */
    suspend fun locate(lat: Double, lng: Double, now: String? = null): LocateResult

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


    override suspend fun sendDelay(nodeId: String, minutes: Int): Impact {
        // 离线演示：没有后端算延后，用内置事件的影响顶上，
        // 界面上仍能看到"影响 → 方案"的完整流程
        delay(300)
        return PlanJson.parseImpact(readAsset("event-rain-T1.json").getJSONObject("data"))
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

    override suspend fun checkin(
        nodeId: String?,
        minutes: Int,
        personId: String?,
    ): CheckinResult {
        delay(250)
        val base = current ?: loadPlan()
        val target = nodeId?.let { base.node(it) }
            ?: base.nodes.firstOrNull { personId != null && personId in it.persons }
            ?: base.nodes.firstOrNull()
            ?: throw IOException("行程里没有可打卡的节点")

        fun makeScheme(
            id: String,
            label: String,
            actions: List<RepairAction>,
            sacrifice: String,
        ): RepairScheme {
            val after = applyActions(base, actions)
            val locked = base.nodes.filter { it.confirmed }
            val kept = locked.count { node ->
                val now = after.node(node.id)
                now != null && now.start == node.start && now.end == node.end
            }
            val keepRate = if (locked.isEmpty()) 1.0 else kept.toDouble() / locked.size
            return RepairScheme(
                id = id,
                label = label,
                keepRate = keepRate,
                changedCount = actions.size,
                actions = actions,
                sacrifice = sacrifice,
            )
        }

        if (minutes <= 0) {
            return CheckinResult(
                nodeId = target.id,
                nodeTitle = target.title,
                status = "on_time",
                minutes = 0,
                message = "已记录到达：${target.title}",
                impact = null,
                schemes = emptyList(),
                blockedNode = null,
            )
        }

        val schemes = mutableListOf<RepairScheme>()
        if (target.durationMin - minutes >= 10) {
            schemes += makeScheme(
                id = "A",
                label = "缩短当前停留",
                actions = listOf(
                    RepairAction(
                        nodeId = target.id,
                        action = "trim",
                        payload = mapOf("minutes" to minutes.toString()),
                        reason = "把「${target.title}」的停留缩短 $minutes 分钟",
                        sacrifice = "少待 $minutes 分钟",
                    ),
                ),
                sacrifice = "少待 $minutes 分钟",
            )
        }

        val affected = base.nodes.filter { it.start >= target.start }
        val shifted = affected.isNotEmpty() && affected.none { it.confirmed }
        if (shifted) {
            val shifts = affected.map { node ->
                RepairAction(
                    nodeId = node.id,
                    action = "shift",
                    payload = mapOf("minutes" to minutes.toString()),
                    reason = "整体后移 $minutes 分钟",
                    sacrifice = "",
                )
            }
            schemes += makeScheme("B", "整体顺延", shifts, "")
        } else if (!target.confirmed) {
            schemes += makeScheme(
                id = "B",
                label = "跳过当前",
                actions = listOf(
                    RepairAction(
                        nodeId = target.id,
                        action = "drop",
                        payload = emptyMap(),
                        reason = "跳过「${target.title}」",
                        sacrifice = "放弃${target.title}",
                    ),
                ),
                sacrifice = "放弃${target.title}",
            )
        }

        val who = if (!personId.isNullOrBlank()) "$personId 晚到" else "你比计划晚到"
        val ordered = if (!personId.isNullOrBlank()) {
            schemes.sortedBy { if (it.id == "B") 0 else 1 }
        } else {
            schemes
        }
        return CheckinResult(
            nodeId = target.id,
            nodeTitle = target.title,
            status = if (!personId.isNullOrBlank()) "member_late" else "late",
            minutes = minutes,
            message = if (schemes.isEmpty()) {
                "$who $minutes 分钟，但没有安全的自动改法，需要你手动决定。"
            } else {
                "$who $minutes 分钟，下面是可以选的处理方式。"
            },
            impact = null,
            schemes = ordered,
            blockedNode = if (ordered.isEmpty()) target.id else null,
        )
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

    override suspend fun undoPreview(): UndoPreview {
        val canUndo = history.isNotEmpty()
        return UndoPreview(
            canUndo = canUndo,
            currentVersion = current?.version ?: 1,
            targetVersion = if (canUndo) (current?.version ?: 1) - 1 else (current?.version ?: 1),
            summary = if (canUndo) "将撤销最近一次改动，恢复上一版行程" else "没有可撤销的改动",
            changes = emptyList(),
        )
    }

    override suspend fun updateLodging(lodging: String): Plan =
        current ?: loadPlan()

    override suspend fun updateStay(nodeId: String, minutes: Int): Plan =
        current ?: loadPlan()

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

    override suspend fun planWeather(): Weather? = weather()

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

    // 离线只有内置那一份示例计划，"我的计划"里就一条
    override suspend fun plans(): List<PlanSummary> {
        val loaded = loadPlan()
        return listOf(
            PlanSummary(
                planId = loaded.planId,
                title = loaded.title,
                date = loaded.date,
                nodeCount = loaded.nodes.size,
                confirmedCount = loaded.nodes.count { it.confirmed },
                version = loaded.version,
                updatedAt = "",
                builtin = true,
            )
        )
    }

    override suspend fun generateFromText(
        text: String,
        startDate: String?,
        endDate: String?,
        city: String?,
        days: Int?,
        lodging: String,
        pace: String,
        maxTransitMin: Int?,
        avoidWalking: Boolean,
        startPlace: String?,
        startLat: Double?,
        startLng: Double?,
    ): Plan =
        throw IOException("离线模式无法按文字生成，请连上后端")

    override suspend fun openPlan(planId: String): Plan = loadPlan()

    override suspend fun deletePlan(planId: String) = Unit

    override suspend fun regions(): List<Province> = emptyList()

    override suspend fun patrol(now: String?, lat: Double?, lng: Double?): PatrolResult {
        // 离线也能演"管家主动提醒"：用内置计划的收口点算一条，
        // 文案里标"演示"，不冒充真实定位与真实天气
        val plan = current ?: loadPlan()
        val closing = plan.nodes.firstOrNull { node ->
            node.windowLatest != null && !node.confirmed
        }
        if (closing == null) {
            return PatrolResult(false, "none", "一切正常", emptyList())
        }
        val latest = closing.windowLatest ?: ""
        val alert = PatrolAlert(
            kind = "closing",
            title = "「" + closing.title + "」今天可能去不成了",
            detail = "最晚 " + latest + " 进去，离线演示数据（连上后端会按真实时间判断）",
            nodeId = closing.id,
            severity = "warn",
            action = "要不要去掉或换成附近别的地方",
        )
        return PatrolResult(
            needsAttention = true,
            severity = "warn",
            summary = alert.title,
            alerts = listOf(alert),
        )
    }

    override suspend fun locate(lat: Double, lng: Double, now: String?): LocateResult {
        // 离线演示：给一条确定的"落后 40 分钟"，方案复用内置素材，
        // 让"定位 → 落后 → 改法"这条链路在没有网络时也能演
        val plan = current ?: loadPlan()
        val stops = plan.nodes.filter { it.type == "place" && !it.confirmed }
        val at = stops.getOrNull(0)
        val should = stops.getOrNull(1)
        val repair = runCatching {
            PlanJson.parseRepair(readAsset("repair-T1.json").getJSONObject("data"))
        }.getOrNull()
        return LocateResult(
            status = "behind",
            message = "你还在「" + (at?.title ?: "上一站") + "」，计划早就该到「" +
                (should?.title ?: "下一站") + "」，已落后 40 分钟（离线演示数据）",
            atNodeTitle = at?.title ?: "",
            shouldNodeTitle = should?.title ?: "",
            driftMinutes = 40,
            schemes = repair?.schemes.orEmpty(),
        )
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
            connection.connectTimeout = 6_000
            // 生成两天以上的行程要多次查高德路径，手机上 8 秒经常不够。
            // 这里放宽到 60 秒，避免后端还在正常生成时客户端先断开。
            connection.readTimeout = 60_000
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
            if (code !in 200..299) {
                // 后端的错误是 {"ok":false,"error":{"message":"..."}}。
                // 直接把 message 显示给用户，不要把整段 JSON 糊到界面上。
                val message = runCatching {
                    JSONObject(text).optJSONObject("error")?.optString("message")
                }.getOrNull()
                throw IOException(message?.takeIf { it.isNotBlank() } ?: "HTTP $code：$text")
            }
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
        planVersion = raw.optInt("version", 1)
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun sendDelay(nodeId: String, minutes: Int): Impact {
        val body = JSONObject()
            .put("type", "delay")
            .put("nodeId", nodeId)
            .put("minutes", minutes)
            .put("label", "比计划晚 " + minutes + " 分钟")
        return PlanJson.parseImpact(request("POST", "/api/plan/$planId/event", body))
    }

    override suspend fun sendEvent(scenario: DemoScenario): Impact =
        PlanJson.parseImpact(request("POST", "/api/plan/$planId/event", eventBody(scenario)))

    override suspend fun repair(scenario: DemoScenario): RepairResult {
        val schemes = JSONArray().put("A").put("B")
        val body = JSONObject().put("event", eventBody(scenario)).put("schemes", schemes)
        return PlanJson.parseRepair(request("POST", "/api/plan/$planId/repair", body))
    }

    override suspend fun checkin(
        nodeId: String?,
        minutes: Int,
        personId: String?,
    ): CheckinResult {
        val body = JSONObject()
            .put("nodeId", nodeId.orEmpty())
            .put("minutes", minutes)
            .put("memberId", settings.memberId)
        if (!personId.isNullOrBlank()) body.put("personId", personId)
        return PlanJson.parseCheckin(request("POST", "/api/plan/$planId/checkin", body))
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
        planVersion = raw.optInt("version", planVersion + 1)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun undo(): Plan {
        val data = request("POST", "/api/plan/$planId/undo")
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        planVersion = raw.optInt("version", planVersion)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun undoPreview(): UndoPreview =
        PlanJson.parseUndoPreview(request("GET", "/api/plan/$planId/undo/preview"))

    override suspend fun updateLodging(lodging: String): Plan {
        val data = request(
            "POST",
            "/api/plan/$planId/lodging",
            JSONObject().put("lodging", lodging),
        )
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        planVersion = raw.optInt("version", planVersion)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun updateStay(nodeId: String, minutes: Int): Plan {
        val data = request(
            "POST",
            "/api/plan/$planId/node/$nodeId/stay",
            JSONObject().put("minutes", minutes),
        )
        val raw = data.getJSONObject("plan")
        savePlan(raw)
        planVersion = raw.optInt("version", planVersion)
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

    // ── 首页：我的计划 ────────────────────────────
    override suspend fun plans(): List<PlanSummary> =
        PlanJson.parsePlans(request("GET", "/api/plans"))

    override suspend fun generateFromText(
        text: String,
        startDate: String?,
        endDate: String?,
        city: String?,
        days: Int?,
        lodging: String,
        pace: String,
        maxTransitMin: Int?,
        avoidWalking: Boolean,
        startPlace: String?,
        startLat: Double?,
        startLng: Double?,
    ): Plan {
        val body = JSONObject().put("text", text)
        if (!startDate.isNullOrBlank()) {
            body.put("startDate", startDate).put("date", startDate)
        }
        if (!endDate.isNullOrBlank()) body.put("endDate", endDate)
        if (!city.isNullOrBlank()) body.put("city", city)
        if (!startPlace.isNullOrBlank()) body.put("startPlace", startPlace)
        if (startLat != null && startLng != null) {
            body.put("startLat", startLat).put("startLng", startLng)
        }
        if (days != null) body.put("days", days)
        if (lodging.isNotBlank()) body.put("lodging", lodging)
        if (pace.isNotBlank()) body.put("pace", pace)
        if (maxTransitMin != null) body.put("maxTransitMin", maxTransitMin)
        if (avoidWalking) body.put("avoidWalking", true)
        val data = request("POST", "/api/generate", body)
        val raw = data.getJSONObject("plan")
        // 每次生成是一个新计划，切到它，后面的下雨/方案都作用在它身上
        this.planId = raw.optString("planId", this.planId).ifBlank { this.planId }
        planVersion = raw.optInt("version", 1)
        savePlan(raw)
        return PlanJson.parsePlan(raw)
    }

    override suspend fun openPlan(planId: String): Plan {
        this.planId = planId
        return loadPlan()
    }

    override suspend fun regions(): List<Province> =
        PlanJson.parseRegions(request("GET", "/api/regions"))

    override suspend fun patrol(now: String?, lat: Double?, lng: Double?): PatrolResult {
        val query = buildString {
            append("/api/plan/").append(planId).append("/patrol?")
            if (!now.isNullOrBlank()) append("now=").append(now).append("&")
            if (lat != null && lng != null) append("lat=").append(lat).append("&lng=").append(lng)
        }
        return PlanJson.parsePatrol(request("GET", query.trimEnd('&', '?')))
    }

    override suspend fun locate(lat: Double, lng: Double, now: String?): LocateResult {
        val body = JSONObject()
            .put("memberId", settings.memberId)
            .put("lat", lat)
            .put("lng", lng)
        if (!now.isNullOrBlank()) body.put("now", now)
        return PlanJson.parseLocate(request("POST", "/api/plan/$planId/locate", body))
    }

    override suspend fun deletePlan(planId: String) {
        request("DELETE", "/api/plans/$planId")
        // 删掉的正好是当前这份，就退回默认计划
        if (planId == this.planId) {
            this.planId = "p_sat_guzhen"
        }
    }

    override suspend fun planWeather(): Weather? {
        val data = request("GET", "/api/plan/$planId/weather")
        if (!data.optBoolean("available", false)) return null
        return PlanJson.parseWeather(data)
    }

    override suspend fun reset(): Plan = loadPlan()

    override fun cachedPlan(): Plan? {
        val text = prefs.getString("plan", null) ?: return null
        return runCatching { PlanJson.parsePlan(JSONObject(text)) }.getOrNull()
    }
}

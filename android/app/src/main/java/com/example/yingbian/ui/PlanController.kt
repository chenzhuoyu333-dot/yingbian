package com.example.yingbian.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.yingbian.data.ActivityRow
import com.example.yingbian.data.ApiSettings
import com.example.yingbian.data.CheckinResult
import com.example.yingbian.data.Impact
import com.example.yingbian.data.DemoScenario
import com.example.yingbian.data.GeneratePrefs
import com.example.yingbian.data.LocateResult
import com.example.yingbian.data.MemberInfo
import com.example.yingbian.data.Plan
import com.example.yingbian.data.PlanRepository
import com.example.yingbian.data.PlanSummary
import com.example.yingbian.data.PatrolResult
import com.example.yingbian.data.Province
import com.example.yingbian.data.RepairAction
import com.example.yingbian.data.RepairScheme
import com.example.yingbian.data.VoteState
import com.example.yingbian.data.Weather

enum class AppScreen(val label: String) {
    Home("计划"),
    NewPlan("新建"),
    Plan("行程"),
    Scheme("方案"),
    Notify("通知"),
    Todo("待办"),
}

data class NotificationRow(
    val id: String,
    val title: String,
    val text: String,
    val level: String,
    val person: String,
)

data class TodoRow(
    val id: String,
    val text: String,
    val phone: String,
    val script: String,
)

class PlanController(
    private val repo: PlanRepository,
    private val settings: ApiSettings? = null,
) {
    var plan by mutableStateOf<Plan?>(null)
        private set
    var impact by mutableStateOf<Impact?>(null)
        private set
    var schemes by mutableStateOf<List<RepairScheme>>(emptyList())
        private set
    var selectedSchemeId by mutableStateOf<String?>(null)
        private set
    var weather by mutableStateOf<Weather?>(null)
        private set
    var weatherLocation by mutableStateOf("行程所在地")
        private set
    var weatherError by mutableStateOf<String?>(null)
        private set
    var weatherLoading by mutableStateOf(false)
        private set
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var empty by mutableStateOf(false)
        private set
    var offline by mutableStateOf(false)
        private set
    var screen by mutableStateOf(AppScreen.Home)
        private set
    var showImpact by mutableStateOf(false)
        private set
    var blockedMessage by mutableStateOf<String?>(null)
        private set
    var blockedNode by mutableStateOf<String?>(null)
        private set
    var notifications by mutableStateOf<List<NotificationRow>>(emptyList())
        private set
    var notificationSelection by mutableStateOf<Set<String>>(emptySet())
        private set
    var todos by mutableStateOf<List<TodoRow>>(emptyList())
        private set
    var todoDone by mutableStateOf<Set<String>>(emptySet())
        private set
    var lastScheme by mutableStateOf<RepairScheme?>(null)
        private set
    var checkinResult by mutableStateOf<CheckinResult?>(null)
        private set
    var checkinOpen by mutableStateOf(false)
        private set
    var checkinLoading by mutableStateOf(false)
        private set
    var checkinError by mutableStateOf<String?>(null)
        private set
    var checkinSelectedId by mutableStateOf<String?>(null)
        private set
    var eventTitle by mutableStateOf("降雨 15:00–17:00")
        private set
    /** 生成后的提示（例如"必去点排不进去"），界面上用 Toast 或角标展示 */
    var generateNote by mutableStateOf<String?>(null)
        private set

    // ── 多人协作 ──────────────────────────────────
    var members by mutableStateOf<List<MemberInfo>>(emptyList())
        private set
    var vote by mutableStateOf<VoteState?>(null)
        private set
    var activityRows by mutableStateOf<List<ActivityRow>>(emptyList())
        private set
    /** 别人改了计划时给个提示，让用户知道"这不是我改的" */
    var remoteChanged by mutableStateOf(false)
        private set

    /** 管家巡检结果：不用你问，它自己发现了什么 */
    var patrolResult by mutableStateOf<PatrolResult?>(null)
        private set
    var patrolDismissed by mutableStateOf(false)
        private set
    private var patrolTick = 0

    /** 定位检查结果：我在哪、计划该在哪、落后多少、能怎么改 */
    var locateResult by mutableStateOf<LocateResult?>(null)
        private set
    var locateLoading by mutableStateOf(false)
        private set

    val memberName: String
        get() = settings?.memberName ?: "我"

    /** 进入行程时登记自己（幂等），并拉一次协作状态 */
    suspend fun joinTrip() {
        runCatching { members = repo.join() }
        runCatching { vote = repo.voteState() }
        runCatching { activityRows = repo.activity() }
    }

    /**
     * 轮询：每 3 秒看一次别人的改动。
     *
     * 用轮询而不是长连接，是因为演示现场 WiFi 不稳，
     * 轮询失败最多晚 3 秒，WebSocket 断了要重连、更容易翻车。
     */
    suspend fun pollLoop() {
        while (true) {
            kotlinx.coroutines.delay(3_000)
            if (plan == null || loading) continue
            runCatching {
                val fresh = repo.loadPlan()
                if (fresh.version != plan?.version) {
                    plan = fresh
                    remoteChanged = true
                }
            }
            runCatching { vote = repo.voteState() }
            runCatching { activityRows = repo.activity() }

            // 巡检比轮询慢：每 20 次轮询（约 60 秒）看一眼就够了，
            // 免得每 3 秒都去请求一次天气和路径
            patrolTick += 1
            if (patrolTick % 20 == 0) {
                runCatching { runPatrol() }
            }
        }
    }

    suspend fun startVote() {
        loading = true
        error = null
        try {
            vote = repo.startVote(defaultScheme = "B", ttlSec = 300)
            activityRows = runCatching { repo.activity() }.getOrDefault(activityRows)
        } catch (exception: Exception) {
            error = exception.message ?: "发起投票失败"
        } finally {
            loading = false
        }
    }

    suspend fun castVote(schemeId: String) {
        try {
            vote = repo.castVote(schemeId)
            activityRows = runCatching { repo.activity() }.getOrDefault(activityRows)
        } catch (exception: Exception) {
            error = exception.message ?: "投票失败"
        }
    }

    suspend fun refreshActivity() {
        runCatching { activityRows = repo.activity() }
        runCatching { members = repo.join() }
    }

    fun clearRemoteChanged() {
        remoteChanged = false
    }

    /**
     * 定位检查：拿当前位置问后端"我现在该在哪"。
     * now 留空用服务器时间；演示时可以传 "17:00" 把场景演出来。
     */
    suspend fun checkLocation(lat: Double, lng: Double, now: String? = null) {
        locateLoading = true
        try {
            locateResult = repo.locate(lat, lng, now)
        } catch (exception: Exception) {
            error = exception.message ?: "定位检查失败"
        } finally {
            locateLoading = false
        }
    }

    fun clearLocateResult() {
        locateResult = null
    }

    /**
     * 主动巡检：不打扰地跑一遍，只有真有事才在界面上提示。
     * 界面上"知道了"之后本轮不再打扰（patrolDismissed），
     * 但下一次真正的变化仍会重新提醒。
     */
    suspend fun runPatrol() {
        if (plan == null) return
        runCatching { repo.patrol() }
            .onSuccess { result ->
                val changed = result.summary != patrolResult?.summary
                patrolResult = result
                if (changed) patrolDismissed = false
            }
    }

    fun dismissPatrol() {
        patrolDismissed = true
    }

    /** 采用定位检查给出的某个方案：直接打给后端并刷新界面 */
    suspend fun applyLocateScheme(scheme: RepairScheme) {
        val base = plan ?: return
        loading = true
        error = null
        try {
            val updated = repo.applyScheme(scheme)
            plan = updated
            planBeforeApply = base
            lastScheme = scheme
            notifications = buildNotifications(scheme, base)
            notificationSelection = notifications.map { it.id }.toSet()
            todos = emptyList()
            todoDone = emptySet()
            screen = AppScreen.Plan
        } catch (exception: Exception) {
            error = exception.message ?: "应用方案失败"
        } finally {
            loading = false
        }
    }

    // ── 首页：我的计划 ─────────────────────────────
    var homePlans by mutableStateOf<List<PlanSummary>>(emptyList())
        private set
    var homeLoading by mutableStateOf(false)
        private set

    // ── 新建行程页 ────────────────────────────────
    var regions by mutableStateOf<List<Province>>(emptyList())
        private set
    var regionsLoading by mutableStateOf(false)
        private set

    suspend fun loadRegions() {
        if (regions.isNotEmpty()) return
        regionsLoading = true
        try {
            regions = repo.regions()
        } catch (exception: Exception) {
            regions = emptyList()
        } finally {
            regionsLoading = false
        }
    }

    /**
     * 新建行程：目的地 + 起止日期 + 一句话偏好。
     * 日期只传起止，天数由后端算 —— 界面上不让用户再填"几天"。
     */
    suspend fun createTrip(
        city: String,
        startDate: String,
        endDate: String,
        text: String,
        startPlace: String = "",
        startLat: Double? = null,
        startLng: Double? = null,
    ) {
        loading = true
        error = null
        generateNote = null
        try {
            plan = repo.generateFromText(
                text = text,
                startDate = startDate,
                endDate = endDate,
                city = city,
                startPlace = startPlace.ifBlank { null },
                startLat = startLat,
                startLng = startLng,
            )
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            notificationSelection = emptySet()
            todos = emptyList()
            todoDone = emptySet()
            lastScheme = null
            planBeforeApply = null
            showImpact = false
            blockedMessage = null
            blockedNode = null
            screen = AppScreen.Plan
            weather = runCatching { repo.planWeather() }.getOrNull()
            generateNote = "已生成 ${plan?.nodes?.size ?: 0} 个节点"
            loadHome()
        } catch (exception: Exception) {
            error = exception.message ?: "生成失败"
        } finally {
            loading = false
        }
    }

    suspend fun loadHome() {
        homeLoading = true
        try {
            homePlans = repo.plans()
        } catch (exception: Exception) {
            // 首页拉不到不要紧，用户还能用内置计划
            homePlans = emptyList()
        } finally {
            homeLoading = false
        }
    }

    /**
     * 一句话新建行程：把文字交给后端，AI 解析成偏好，再用高德真实地点排成计划。
     * 成功后直接进这份新行程的行程页。
     */
    suspend fun createFromText(
        text: String,
        startDate: String? = null,
        days: Int? = null,
        lodging: String = "",
        avoidWalking: Boolean = false,
    ) {
        loading = true
        error = null
        generateNote = null
        try {
            plan = repo.generateFromText(
                text = text,
                startDate = startDate,
                days = days,
                lodging = lodging,
                avoidWalking = avoidWalking,
            )
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            notificationSelection = emptySet()
            todos = emptyList()
            todoDone = emptySet()
            lastScheme = null
            planBeforeApply = null
            showImpact = false
            blockedMessage = null
            blockedNode = null
            screen = AppScreen.Plan
            weather = runCatching { repo.planWeather() }.getOrNull()
            weather?.place?.takeIf { it.isNotBlank() }?.let { weatherLocation = it }
            generateNote = "已生成 ${plan?.days ?: days ?: 1} 天、${plan?.nodes?.size ?: 0} 个节点"
            loadHome()
        } catch (exception: Exception) {
            error = exception.message ?: "生成失败"
        } finally {
            loading = false
        }
    }

    /** 从首页打开一份已有的行程 */
    suspend fun openPlan(planId: String) {
        loading = true
        error = null
        try {
            plan = repo.openPlan(planId)
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            todos = emptyList()
            screen = AppScreen.Plan
            weather = runCatching { repo.planWeather() }.getOrNull()
            weather?.place?.takeIf { it.isNotBlank() }?.let { weatherLocation = it }
        } catch (exception: Exception) {
            error = exception.message ?: "打开失败"
        } finally {
            loading = false
        }
    }

    suspend fun removePlan(planId: String) {
        runCatching { repo.deletePlan(planId) }
        loadHome()
    }
    private var planBeforeApply: Plan? = null
    private var scenario = DemoScenario.RAIN

    val selectedScheme: RepairScheme?
        get() = schemes.firstOrNull { it.id == selectedSchemeId }

    private suspend fun loadWeather(lat: Double? = null, lng: Double? = null) {
        try {
            weather = repo.weather(lat, lng)
            weatherError = null
            weatherLocation = if (lat != null && lng != null) "我的位置" else "行程所在地"
        } catch (exception: Exception) {
            weatherError = exception.message ?: "天气获取失败"
        }
    }

    /** 用户点“用我的位置”后调用；失败时保留旧天气并显示原因。 */
    suspend fun refreshWeather(lat: Double, lng: Double) {
        weatherLoading = true
        weatherError = null
        try {
            weather = repo.weather(lat, lng)
            weatherLocation = "我的位置"
        } catch (exception: Exception) {
            weatherError = exception.message ?: "天气获取失败"
        } finally {
            weatherLoading = false
        }
    }

    suspend fun load() {
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        loading = true
        error = null
        empty = false
        offline = false
        clearCheckin()
        try {
            plan = repo.loadPlan()
            loadWeather()
        } catch (exception: Exception) {
            val cached = repo.cachedPlan()
            if (cached != null) {
                plan = cached
                offline = true
            } else {
                error = exception.message ?: "载入失败"
            }
        } finally {
            loading = false
        }
    }

    /** 把"来不及了/落后"变成一次延后事件，让引擎给出改法 */
    suspend fun reportDelay(nodeId: String, minutes: Int) {
        if (plan == null || nodeId.isBlank()) return
        loading = true
        error = null
        eventTitle = "「" + nodeId + "」延后 " + minutes + " 分钟"
        try {
            impact = repo.sendDelay(nodeId, minutes)
            showImpact = true
        } catch (exception: Exception) {
            error = exception.message ?: "重算失败"
        } finally {
            loading = false
        }
    }

    suspend fun simulateRain() {
        if (plan == null) return
        loading = true
        error = null
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        try {
            impact = repo.sendEvent(scenario)
            showImpact = true
        } catch (exception: Exception) {
            error = exception.message ?: "重算失败"
        } finally {
            loading = false
        }
    }

    /** 按偏好生成一份行程；成功后直接回到计划图屏 */
    suspend fun generate(prefs: GeneratePrefs) {
        loading = true
        error = null
        empty = false
        offline = false
        generateNote = null
        clearCheckin()
        try {
            plan = repo.generate(prefs)
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            notificationSelection = emptySet()
            todos = emptyList()
            todoDone = emptySet()
            lastScheme = null
            planBeforeApply = null
            scenario = DemoScenario.RAIN
            eventTitle = "降雨 15:00–17:00"
            showImpact = false
            blockedMessage = null
            blockedNode = null
            screen = AppScreen.Plan
            loadWeather()
            generateNote = "已生成 ${plan?.nodes?.size ?: 0} 个节点，其中 ${
                plan?.nodes?.count { it.confirmed } ?: 0
            } 个已锁定"
        } catch (exception: Exception) {
            error = exception.message ?: "生成失败"
        } finally {
            loading = false
        }
    }

    fun clearGenerateNote() {
        generateNote = null
    }

    suspend fun loadSchemes() {
        if (plan == null) return
        loading = true
        error = null
        showImpact = false
        blockedNode = null
        try {
            val result = repo.repair(scenario)
            if (result.status == "blocked") {
                blockedMessage = result.message.ifBlank { "有锁定项需要你确认" }
                blockedNode = result.blockedNode
            } else {
                schemes = result.schemes
                selectedSchemeId = result.schemes.firstOrNull()?.id
                screen = AppScreen.Scheme
            }
        } catch (exception: Exception) {
            error = exception.message ?: "生成方案失败"
        } finally {
            loading = false
        }
    }

    suspend fun applySelected() {
        val scheme = selectedScheme ?: return
        val base = plan ?: return
        loading = true
        error = null
        try {
            val updated = repo.applyScheme(scheme)
            plan = updated
            planBeforeApply = base
            lastScheme = scheme
            notifications = buildNotifications(scheme, base)
            notificationSelection = notifications.map { it.id }.toSet()
            todos = emptyList()
            todoDone = emptySet()
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            screen = AppScreen.Notify
            scenario = DemoScenario.RAIN
        } catch (exception: Exception) {
            error = exception.message ?: "应用方案失败"
        } finally {
            loading = false
        }
    }

    fun openCheckin() {
        if (plan == null) return
        checkinResult = null
        checkinError = null
        checkinSelectedId = null
        checkinOpen = true
    }

    fun closeCheckin() {
        if (checkinLoading) return
        checkinOpen = false
        checkinError = null
    }

    suspend fun submitCheckin(nodeId: String, minutes: Int, personId: String? = null) {
        checkinLoading = true
        checkinError = null
        try {
            val result = repo.checkin(nodeId, minutes, personId)
            checkinResult = result
            checkinSelectedId = result.schemes.firstOrNull()?.id
        } catch (exception: Exception) {
            checkinError = exception.message ?: "打卡失败"
        } finally {
            checkinLoading = false
        }
    }

    fun selectCheckinScheme(id: String) {
        checkinSelectedId = id
    }

    suspend fun applyCheckinScheme() {
        val result = checkinResult ?: return
        val scheme = result.schemes.firstOrNull { it.id == checkinSelectedId } ?: return
        val base = plan ?: return
        checkinLoading = true
        checkinError = null
        try {
            val updated = repo.applyScheme(scheme)
            plan = updated
            planBeforeApply = base
            lastScheme = scheme
            notifications = buildNotifications(scheme, base)
            notificationSelection = notifications.map { it.id }.toSet()
            todos = emptyList()
            todoDone = emptySet()
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            eventTitle = "到达晚到 ${result.minutes} 分钟"
            screen = AppScreen.Notify
            checkinOpen = false
            checkinResult = null
            checkinSelectedId = null
        } catch (exception: Exception) {
            checkinError = exception.message ?: "应用方案失败"
        } finally {
            checkinLoading = false
        }
    }

    suspend fun undo() {
        loading = true
        error = null
        clearCheckin()
        try {
            plan = repo.undo()
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            notificationSelection = emptySet()
            todos = emptyList()
            todoDone = emptySet()
            lastScheme = null
            planBeforeApply = null
            scenario = DemoScenario.RAIN
            eventTitle = "降雨 15:00–17:00"
            screen = AppScreen.Plan
        } catch (exception: Exception) {
            error = exception.message ?: "撤销失败"
        } finally {
            loading = false
        }
    }

    suspend fun unlockAndRepair() {
        val node = blockedNode
        blockedMessage = null
        if (node != null) {
            try {
                plan = repo.setLocked(node, false)
            } catch (exception: Exception) {
                error = exception.message ?: "解锁失败"
                return
            }
        }
        loadSchemes()
    }

    fun dismissBlocked() {
        blockedMessage = null
    }

    suspend fun demoBlocked() {
        loading = true
        error = null
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        try {
            plan = repo.setLocked("n_sunset", true)
            impact = repo.sendEvent(scenario)
            loadSchemes()
        } catch (exception: Exception) {
            error = exception.message ?: "阻断演示失败"
            loading = false
        }
    }

    suspend fun demoCancelLunch() {
        loading = true
        error = null
        showImpact = false
        scenario = DemoScenario.CANCEL_LUNCH
        eventTitle = "午餐 · 河边餐厅取消"
        try {
            plan = repo.setLocked("n_sunset", false)
            impact = repo.sendEvent(scenario)
            loading = false
            loadSchemes()
        } catch (exception: Exception) {
            error = exception.message ?: "取消演示失败"
            loading = false
        }
    }

    fun selectScheme(id: String) {
        selectedSchemeId = id
    }

    fun openScreen(target: AppScreen) {
        screen = target
    }

    fun openImpact() {
        showImpact = true
    }

    fun closeImpact() {
        showImpact = false
    }

    fun toggleNotification(id: String) {
        notificationSelection = if (id in notificationSelection) {
            notificationSelection - id
        } else {
            notificationSelection + id
        }
    }

    fun confirmNotifications() {
        val scheme = lastScheme ?: return
        val currentPlan = plan ?: return
        val beforePlan = planBeforeApply ?: currentPlan
        todos = buildTodos(scheme, beforePlan, currentPlan, notificationSelection)
        todoDone = emptySet()
        screen = AppScreen.Todo
    }

    fun toggleTodo(id: String) {
        todoDone = if (id in todoDone) todoDone - id else todoDone + id
    }

    fun completeAllTodos() {
        todoDone = todos.map { it.id }.toSet()
    }

    fun startEmpty() {
        plan = null
        impact = null
        empty = true
        error = null
        screen = AppScreen.Plan
    }

    fun forceFailure() {
        error = "后端连接超时（调试状态）"
    }

    fun useCache() {
        val cached = repo.cachedPlan()
        if (cached == null) {
            error = "没有可用的离线缓存"
            return
        }
        plan = cached
        offline = true
        error = null
        empty = false
    }

    fun resetDebugState() {
        empty = false
        error = null
        blockedMessage = null
        blockedNode = null
        offline = false
    }

    suspend fun resetDemo() {
        loading = true
        error = null
        empty = false
        offline = false
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        clearCheckin()
        try {
            plan = repo.reset()
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            notificationSelection = emptySet()
            todos = emptyList()
            todoDone = emptySet()
            lastScheme = null
            planBeforeApply = null
            screen = AppScreen.Plan
            loadWeather()
        } catch (exception: Exception) {
            error = exception.message ?: "恢复失败"
        } finally {
            loading = false
        }
    }

    private fun buildNotifications(scheme: RepairScheme, currentPlan: Plan): List<NotificationRow> =
        scheme.actions.mapIndexed { index, action ->
            val node = currentPlan.node(action.nodeId)
            val fromTitle = action.payload["fromTitle"] ?: node?.title ?: action.nodeId
            val toTitle = action.payload["toTitle"] ?: "新地点"
            val text = when (action.action) {
                "replace" -> "$fromTitle 已改去「$toTitle」"
                "drop" -> "$fromTitle 已取消"
                "trim" -> "$fromTitle 停留缩短 ${action.payload["minutes"] ?: "0"} 分钟"
                else -> "$fromTitle 后移 ${action.payload["minutes"] ?: "0"} 分钟"
            }
            val level = when {
                action.action == "drop" -> "打断"
                action.action == "replace" && node?.type == "reservation" -> "打断"
                else -> "知会"
            }
            val person = if (action.action == "replace" && !node?.contact.isNullOrBlank()) {
                "餐厅 / 场馆"
            } else {
                "同行 4 人"
            }
            NotificationRow(
                id = index.toString(),
                title = fromTitle,
                text = text,
                level = level,
                person = person,
            )
        }

    private fun buildTodos(
        scheme: RepairScheme,
        beforePlan: Plan,
        afterPlan: Plan,
        selectedIds: Set<String>,
    ): List<TodoRow> = scheme.actions.mapIndexedNotNull { index, action ->
        if (index.toString() !in selectedIds) return@mapIndexedNotNull null
        val beforeNode = beforePlan.node(action.nodeId)
        val afterNode = afterPlan.node(action.nodeId)
        val title = action.payload["fromTitle"] ?: beforeNode?.title ?: action.nodeId
        when {
            action.action == "replace" && !afterNode?.contact.isNullOrBlank() -> TodoRow(
                id = index.toString(),
                text = "电话确认：${afterNode?.place?.ifBlank { title } ?: title}",
                phone = afterNode?.contact.orEmpty(),
                script = "你好，我们原计划有变动，想确认 $title 还可以安排吗？",
            )

            action.action == "replace" -> TodoRow(
                id = index.toString(),
                text = "告知同行：$title 改为「${action.payload["toTitle"] ?: "新地点"}」",
                phone = "",
                script = "我们临时调整了行程，$title 改成「${action.payload["toTitle"] ?: "新地点"}」了。",
            )

            action.action == "drop" -> TodoRow(
                id = index.toString(),
                text = "告知同行：$title 取消",
                phone = "",
                script = "我们临时调整了行程，$title 这次先不去了，抱歉。",
            )

            action.action == "trim" -> TodoRow(
                id = index.toString(),
                text = "告知同行：$title 停留缩短 ${action.payload["minutes"] ?: "0"} 分钟",
                phone = "",
                script = "我们到得晚了一点，$title 的停留会缩短 ${action.payload["minutes"] ?: "0"} 分钟。",
            )

            else -> TodoRow(
                id = index.toString(),
                text = "告知同行：$title 后移 ${action.payload["minutes"] ?: "0"} 分钟",
                phone = "",
                script = "我们临时调整了时间，$title 延后 ${action.payload["minutes"] ?: "0"} 分钟。",
            )
        }
    }

    private fun clearCheckin() {
        checkinOpen = false
        checkinResult = null
        checkinError = null
        checkinSelectedId = null
        checkinLoading = false
    }
}

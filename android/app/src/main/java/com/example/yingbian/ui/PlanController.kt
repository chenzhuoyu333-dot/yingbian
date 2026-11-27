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
import com.example.yingbian.data.PatrolAlert
import com.example.yingbian.data.Province
import com.example.yingbian.data.RepairAction
import com.example.yingbian.data.RepairScheme
import com.example.yingbian.data.UndoPreview
import com.example.yingbian.data.VoteState
import com.example.yingbian.data.Weather
import com.example.yingbian.data.displayTitle
import com.example.yingbian.data.parseMinutes
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class AppScreen(val label: String) {
    Home("计划"),
    NewPlan("新建"),
    Plan("行程"),
    Scheme("方案"),
    Notify("提醒"),
    Todo("待办"),
    Profile("我的"),
}

data class NotificationRow(
    val id: String,
    val title: String,
    val text: String,
    val level: String,
    val person: String,
    /** auto：App 内成员自动收到；assist：需要你点一下打电话/发消息；info：只读知会 */
    val kind: String = "info",
    val phone: String = "",
    val script: String = "",
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
    /** 方案不再占一个页面：需要改行程时从底部弹出，关掉就回行程 */
    var schemeSheetOpen by mutableStateOf(false)
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
    /** 今天没有行程（首页空态用，不和"加载失败"混在一起） */
    var todayEmpty by mutableStateOf(false)
        private set
    var offline by mutableStateOf(false)
        private set
    var screen by mutableStateOf(AppScreen.Plan)
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
    var checkinInitialNodeId by mutableStateOf<String?>(null)
        private set
    var eventTitle by mutableStateOf("降雨 15:00–17:00")
        private set
    /** 生成后的提示（例如"必去点排不进去"），界面上用 Toast 或角标展示 */
    var generateNote by mutableStateOf<String?>(null)
        private set
    /** 撤销确认：先展示会退回哪一版、改了什么，用户确认后才真的撤销 */
    var undoPreview by mutableStateOf<UndoPreview?>(null)
        private set
    var undoPreviewOpen by mutableStateOf(false)
        private set

    // ── 多人协作 ──────────────────────────────────
    var members by mutableStateOf<List<MemberInfo>>(emptyList())
        private set
    var vote by mutableStateOf<VoteState?>(null)
        private set
    var activityRows by mutableStateOf<List<ActivityRow>>(emptyList())
        private set
    /** 单人模式也能看到的本地时间线：生成、打卡、采用方案、撤销、处理天气 */
    var localTimeline by mutableStateOf<List<ActivityRow>>(emptyList())
        private set
    val timelineRows: List<ActivityRow>
        get() = (localTimeline + activityRows).sortedBy { it.at }
    /** 别人改了计划时给个提示，让用户知道"这不是我改的" */
    var remoteChanged by mutableStateOf(false)
        private set

    /** 管家巡检结果：不用你问，它自己发现了什么 */
    var patrolResult by mutableStateOf<PatrolResult?>(null)
        private set
    var patrolDismissed by mutableStateOf(false)
        private set
    private var patrolTick = 0
    /** 天气真的会影响行程时，自动弹一次；同一场雨不反复弹 */
    var autoWeatherAlert by mutableStateOf<PatrolAlert?>(null)
        private set
    private var lastWeatherAlertKey: String = ""

    /** 定位检查结果：我在哪、计划该在哪、落后多少、能怎么改 */
    var locateResult by mutableStateOf<LocateResult?>(null)
        private set
    var locateLoading by mutableStateOf(false)
        private set
    /** 自动定位发现的“到了/落后了”，只做卡片提示，不弹大窗 */
    var locateHint by mutableStateOf<LocateResult?>(null)
        private set
    private var locateHintKey: String = ""
    /** 本机勾选“已到达”的节点（和“锁定”不是一回事） */
    private var arrivedRevision by mutableStateOf(0)
    val arrivedNodeIds: Set<String>
        get() {
            arrivedRevision
            return settings?.arrivedNodes(plan?.planId.orEmpty()).orEmpty()
        }
    var arrivalBusyNodeId by mutableStateOf<String?>(null)
        private set
    var arrivalNotice by mutableStateOf<String?>(null)
        private set
    /** 行程中后台自动检测；开着时状态栏会有一条常驻通知 */
    var trackingOn by mutableStateOf(settings?.trackingEnabled == true)
        private set

    val memberName: String
        get() = settings?.memberName ?: "我"

    private fun record(text: String, name: String? = null) {
        val at = SimpleDateFormat("HH:mm", Locale.CHINA).format(Date())
        localTimeline = localTimeline + ActivityRow(
            at = at,
            name = name ?: memberName,
            text = text,
        )
    }

    /** 进入行程时登记自己（幂等），并拉一次协作状态 */
    suspend fun joinTrip() {
        // 没有当前行程时不要请求 /api/plan//members：那会生成空计划 ID，
        // 在历史清空后的第一次启动里虽然被 runCatching 吞掉，但日志和状态都不干净。
        if (plan == null) return
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
                    todayEmpty = false
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
     * 前台自动检查：只在本机有定位权限时调用。
     * 到了目标点就提示打卡；落后超过容差就提示“要不要改行程”。
     * 同一个节点只提醒一次，避免每分钟弹同一句话。
     */
    suspend fun autoLocate(lat: Double, lng: Double, now: String? = null) {
        val result = runCatching { repo.locate(lat, lng, now) }.getOrNull() ?: return
        if (!result.arrived && !result.isBehind) {
            locateHint = null
            locateHintKey = ""
            return
        }
        val targetId = result.shouldNodeId.ifBlank { result.shouldNodeTitle }
        val key = if (result.arrived) "arrive:${result.atNodeId}" else "behind:$targetId"
        locateHint = result
        if (key == locateHintKey) return
        locateHintKey = key
        record(
            if (result.arrived) "定位到「${result.atNodeTitle}」，等你确认到达"
            else "定位发现落后 ${result.driftMinutes} 分钟"
        )
    }

    private fun resetAutoLocatePrompt() {
        locateHintKey = ""
        locateHint = null
    }

    fun dismissLocateHint() {
        locateHintKey = ""
        locateHint = null
    }

    /** 点卡片上的“看看怎么改”：接到已有的定位结果弹窗 */
    fun openLocateHintFix() {
        locateResult = locateHint
        locateHint = null
    }

    fun clearArrivalNotice() {
        arrivalNotice = null
    }

    fun setTracking(on: Boolean) {
        trackingOn = on
        settings?.trackingEnabled = on
    }

    /** 从通知栏“停止检测”回来时，把界面开关同步成真实状态 */
    fun syncTracking(on: Boolean) {
        trackingOn = on
    }

    /** 后台服务每 60 秒推来的结果，和前台自动检测走同一条展示逻辑 */
    fun applyBackgroundLocate(result: LocateResult) {
        if (!result.arrived && !result.isBehind) return
        locateHint = result
    }

    /**
     * 勾选“到了”：按当前时间自动算晚了几分钟，不需要用户再填。
     * 准时就直接打勾；晚到才把方案弹出来让用户选。
     */
    suspend fun arrive(nodeId: String) {
        val current = plan ?: return
        val node = current.node(nodeId) ?: return
        if (node.overnight || arrivalBusyNodeId != null) return
        arrivalBusyNodeId = nodeId
        arrivalNotice = null
        try {
            val minutes = lateMinutesFor(node, current)
            val result = repo.checkin(nodeId, minutes)
            markArrived(nodeId)
            locateHint = null
            locateHintKey = ""
            record(
                if (result.schemes.isEmpty()) "勾选到达「${node.displayTitle}」"
                else "勾选到达「${node.displayTitle}」，晚到 ${result.minutes} 分钟"
            )
            if (result.schemes.isNotEmpty()) {
                checkinResult = result
                checkinSelectedId = result.schemes.firstOrNull()?.id
                checkinInitialNodeId = nodeId
                checkinOpen = true
            } else {
                arrivalNotice = "已到达 · ${node.displayTitle}"
            }
        } catch (exception: Exception) {
            arrivalNotice = exception.message ?: "打卡失败"
        } finally {
            arrivalBusyNodeId = null
        }
    }

    private fun lateMinutesFor(node: com.example.yingbian.data.PlanNode, current: Plan): Int {
        val day = node.date.ifBlank { current.date }
        val today = todayIso()
        if (day.isNotBlank() && day != today) return 0
        return (currentMinuteOfDay() - parseMinutes(node.start)).coerceIn(0, 180)
    }

    private fun markArrived(nodeId: String) {
        val planId = plan?.planId.orEmpty()
        settings?.markArrived(planId, nodeId)
        arrivedRevision += 1
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
                val weather = result.alerts.firstOrNull { it.kind == "weather" }
                if (weather != null && result.needsAttention) {
                    val key = "${weather.nodeId}|${weather.detail}|${weather.title}"
                    if (key != lastWeatherAlertKey) {
                        lastWeatherAlertKey = key
                        autoWeatherAlert = weather
                        record("发现天气影响行程：${weather.title}")
                    }
                }
            }
    }

    fun dismissPatrol() {
        patrolDismissed = true
    }

    fun dismissAutoWeather() {
        autoWeatherAlert = null
    }

    /** 采用定位检查给出的某个方案：直接打给后端并刷新界面 */
    suspend fun applyLocateScheme(scheme: RepairScheme) {
        val base = plan ?: return
        loading = true
        error = null
        try {
            val updated = repo.applyScheme(scheme)
            plan = updated
            todayEmpty = false
            record("采用了方案「${scheme.label}」")
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
        lodging: String = "",
        pace: String = "normal",
        maxTransitMin: Int = 60,
    ) {
        resetAutoLocatePrompt()
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
                lodging = lodging,
                pace = pace,
                maxTransitMin = maxTransitMin,
            )
            localTimeline = emptyList()
            record("生成了 ${plan?.days ?: 1} 天、${plan?.nodes?.size ?: 0} 个地点的行程")
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
        resetAutoLocatePrompt()
        loading = true
        error = null
        try {
            plan = repo.openPlan(planId)
            todayEmpty = false
            localTimeline = emptyList()
            record("打开了行程「${plan?.title.orEmpty()}」")
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            todos = emptyList()
            screen = AppScreen.Plan
            weather = runCatching { repo.planWeather() }.getOrNull()
            weather?.place?.takeIf { it.isNotBlank() }?.let { weatherLocation = it }
            joinTrip()
        } catch (exception: Exception) {
            error = exception.message ?: "打开失败"
        } finally {
            loading = false
        }
    }

    suspend fun removePlan(planId: String) {
        runCatching { repo.deletePlan(planId) }
        if (plan?.planId == planId) {
            plan = null
            weather = null
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            notifications = emptyList()
            todos = emptyList()
            screen = AppScreen.Home
        }
        loadHome()
    }
    private var planBeforeApply: Plan? = null
    private var scenario = DemoScenario.RAIN

    val selectedScheme: RepairScheme?
        get() = schemes.firstOrNull { it.id == selectedSchemeId }

    /** 只按“这份行程在哪”查天气；没有坐标就不显示，不拿杭州默认值冒充 */
    suspend fun refreshPlanWeather() {
        weatherLoading = true
        weatherError = null
        try {
            weather = repo.planWeather()
            weatherLocation = weather?.place?.takeIf { it.isNotBlank() } ?: "行程所在地"
        } catch (exception: Exception) {
            weatherError = exception.message ?: "天气获取失败"
        } finally {
            weatherLoading = false
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

    /**
     * 首页 = 今天的行程。
     *
     * 产品上的取舍：打开 App 看到"今天要走的这份"，而不是"历史行程列表"。
     * 今天没有就明确说没有（并给当地天气），而不是停在上一份行程上。
     */
    suspend fun loadToday() {
        empty = false
        todayEmpty = false
        error = null
        offline = false
        loading = true
        try {
            val all = repo.plans()
            val today = todayIso()
            val mine = all.firstOrNull { !it.builtin && it.date == today }
            if (mine == null) {
                plan = null
                todayEmpty = true
                // 空态也要天气：界面会先用定位调 refreshWeather(lat,lng)，
                // 这里不再强行猜位置，取不到就留空（界面显示"取不到天气"）
            } else {
                openPlan(mine.planId)
            }
        } catch (exception: Exception) {
            val cached = repo.cachedPlan()
            if (cached != null) {
                plan = cached
                todayEmpty = false
                offline = true
            } else {
                error = exception.message ?: "载入失败"
            }
        } finally {
            loading = false
        }
    }

    suspend fun load() {
        resetAutoLocatePrompt()
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        loading = true
        error = null
        empty = false
        offline = false
        clearCheckin()
        try {
            val summaries = repo.plans()
            homePlans = summaries
            // 自己的行程优先；mock 模式才允许直接进内置演示
            val own = summaries.filterNot { it.builtin }
            val candidates = if (settings?.useMock == true) summaries else own
            val last = settings?.lastPlanId.orEmpty()
            val target = candidates.firstOrNull { it.planId == last } ?: candidates.firstOrNull()
            if (target == null) {
                plan = null
                weather = null
                weatherLocation = "行程所在地"
            } else {
                plan = repo.openPlan(target.planId)
                todayEmpty = false
                refreshPlanWeather()
            }
        } catch (exception: Exception) {
            val cached = repo.cachedPlan()
            if (cached != null) {
                plan = cached
                todayEmpty = false
                offline = true
                weather = null
            } else {
                plan = null
                error = exception.message ?: "载入失败"
            }
        } finally {
            loading = false
        }
    }

    /** 在当前方案上加一站 */
    suspend fun addNodeHere(title: String, afterNodeId: String? = null, stayMin: Int = 60) {
        if (title.isBlank()) return
        loading = true
        error = null
        try {
            val base = plan ?: return
            val result = repo.addNode(
                title = title,
                city = cityOf(base),
                afterNodeId = afterNodeId,
                stayMin = stayMin,
            )
            plan = result.plan
            todayEmpty = false
            record("加了一站「" + title + "」")
            result.warnings.firstOrNull()?.let { generateNote = it }
            // 增删站点不是一次"方案"，通知/待办重新等变化后再生成
            notifications = emptyList()
            todos = emptyList()
            todoDone = emptySet()
        } catch (exception: Exception) {
            error = exception.message ?: "加站失败"
        } finally {
            loading = false
        }
    }

    /** 提一句意见，直接改在当前方案上 */
    suspend fun refinePlan(text: String) {
        if (text.isBlank()) return
        loading = true
        error = null
        try {
            val base = plan ?: return
            val result = repo.refine(text, cityOf(base))
            plan = result.plan
            todayEmpty = false
            if (result.applied.isNotEmpty()) {
                record("按意见调整：" + result.applied.joinToString("、"))
                generateNote = result.applied.joinToString("、")
            } else {
                generateNote = result.unsupported.ifBlank { "这句没能改到方案上" }
            }
            notifications = emptyList()
            todos = emptyList()
            todoDone = emptySet()
        } catch (exception: Exception) {
            error = exception.message ?: "按意见修改失败"
        } finally {
            loading = false
        }
    }

    /** 删掉某一站 */
    suspend fun removeNodeAt(nodeId: String) {
        val base = plan ?: return
        val title = base.node(nodeId)?.title ?: ""
        loading = true
        error = null
        try {
            val result = repo.removeNode(nodeId)
            plan = result.plan
            todayEmpty = false
            record("删掉了「" + title + "」")
            notifications = emptyList()
            todos = emptyList()
            todoDone = emptySet()
        } catch (exception: Exception) {
            error = exception.message ?: "删除失败"
        } finally {
            loading = false
        }
    }

    /** 从标题里猜城市（"2026-11-25 杭州 3 日行程" → 杭州），猜不到给空 */
    private fun cityOf(plan: Plan): String {
        val parts = plan.title.replace("（据偏好生成）", "").trim().split(" ")
        return parts.firstOrNull { it.endsWith("市") || it.length in 2..3 && it !in listOf("日行程") }
            ?.removeSuffix("市")
            ?: ""
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
            todayEmpty = false
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
            refreshPlanWeather()
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
                schemeSheetOpen = true
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
            todayEmpty = false
            record("采用了方案「${scheme.label}」")
            planBeforeApply = base
            lastScheme = scheme
            notifications = buildNotifications(scheme, base)
            notificationSelection = notifications.map { it.id }.toSet()
            todos = emptyList()
            todoDone = emptySet()
            impact = null
            schemes = emptyList()
            selectedSchemeId = null
            schemeSheetOpen = false
            screen = AppScreen.Notify
            scenario = DemoScenario.RAIN
        } catch (exception: Exception) {
            error = exception.message ?: "应用方案失败"
        } finally {
            loading = false
        }
    }

    fun openCheckin(nodeId: String? = null) {
        if (plan == null) return
        checkinResult = null
        checkinError = null
        checkinSelectedId = null
        checkinInitialNodeId = nodeId
        checkinOpen = true
    }

    fun closeCheckin() {
        if (checkinLoading) return
        checkinOpen = false
        checkinError = null
        checkinInitialNodeId = null
    }

    suspend fun submitCheckin(nodeId: String, minutes: Int, personId: String? = null) {
        checkinLoading = true
        checkinError = null
        try {
            val result = repo.checkin(nodeId, minutes, personId)
            val title = plan?.node(nodeId)?.title ?: nodeId
            markArrived(nodeId)
            record(
                if (result.schemes.isEmpty()) "在「$title」打卡，时间正好"
                else "在「$title」打卡，晚到 ${result.minutes} 分钟"
            )
            if (result.schemes.isEmpty() && personId == null) {
                checkinOpen = false
                arrivalNotice = "已到达 · $title"
                return
            }
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
            todayEmpty = false
            record("采用了方案「${scheme.label}」")
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

    suspend fun requestUndo() {
        loading = true
        error = null
        try {
            undoPreview = repo.undoPreview()
            undoPreviewOpen = true
        } catch (exception: Exception) {
            error = exception.message ?: "读取撤销预览失败"
        } finally {
            loading = false
        }
    }

    fun cancelUndo() {
        undoPreviewOpen = false
        undoPreview = null
    }

    suspend fun updateLodging(nodeId: String, lodging: String) {
        loading = true
        error = null
        try {
            plan = repo.updateLodging(lodging, nodeId)
            todayEmpty = false
            record("住宿改为「$lodging」")
            generateNote = "住宿已改为 $lodging"
        } catch (exception: Exception) {
            error = exception.message ?: "修改住宿失败"
        } finally {
            loading = false
        }
    }

    suspend fun updateStay(nodeId: String, minutes: Int) {
        loading = true
        error = null
        try {
            val title = plan?.node(nodeId)?.title ?: nodeId
            plan = repo.updateStay(nodeId, minutes)
            todayEmpty = false
            record("把「$title」的停留改为 $minutes 分钟")
            generateNote = "停留已改为 $minutes 分钟，后面的站点已顺延"
        } catch (exception: Exception) {
            error = exception.message ?: "调整停留失败"
        } finally {
            loading = false
        }
    }

    suspend fun undo() {
        undoPreviewOpen = false
        undoPreview = null
        loading = true
        error = null
        clearCheckin()
        try {
            plan = repo.undo()
            todayEmpty = false
            record("撤销回到 v${plan?.version ?: 1}")
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
                todayEmpty = false
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
            todayEmpty = false
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
            todayEmpty = false
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

    fun closeSchemes() {
        schemeSheetOpen = false
        schemes = emptyList()
        selectedSchemeId = null
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
        todayEmpty = false
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
            todayEmpty = false
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
            refreshPlanWeather()
        } catch (exception: Exception) {
            error = exception.message ?: "恢复失败"
        } finally {
            loading = false
        }
    }

    private fun actionText(action: RepairAction, plan: Plan): String {
        val node = plan.node(action.nodeId)
        val title = action.payload["fromTitle"] ?: node?.title ?: action.nodeId
        val minutes = action.payload["minutes"] ?: "0"
        return when (action.action) {
            "shift_all" -> "后面 ${action.payload["count"] ?: "多"} 站一起顺延 $minutes 分钟"
            "replace" -> "$title 改去「${action.payload["toTitle"] ?: "新地点"}」"
            "drop" -> "$title 取消"
            "trim" -> "$title 停留缩短 $minutes 分钟"
            else -> "$title 后移 $minutes 分钟"
        }
    }

    /**
     * 一个事件只产生一条行动项。
     *
     * 同一件事不再同时进“通知”和“待办”两个列表：
     *   auto   → App 内成员自动收到，不需要你操作
     *   assist → 需要你点一下（打电话/发消息）才能通知到外部对象
     *   info   → 只读知会
     */
    private fun buildNotifications(scheme: RepairScheme, currentPlan: Plan): List<NotificationRow> {
        val contact = scheme.actions.firstNotNullOfOrNull { action ->
            currentPlan.node(action.nodeId)?.contact?.takeIf { it.isNotBlank() }
        }
        val needsManual = scheme.actions.any {
            it.action == "replace" && !currentPlan.node(it.nodeId)?.contact.isNullOrBlank()
        }
        val detail = scheme.actions.joinToString("；") { actionText(it, currentPlan) }
            .ifBlank { "行程有调整" }
        return listOf(
            NotificationRow(
                id = "scheme_${scheme.id}",
                title = "行程已调整：${scheme.label}",
                text = detail,
                level = if (scheme.actions.any { it.action == "drop" }) "打断" else "知会",
                person = if (needsManual) "餐厅 / 场馆" else "同行成员",
                kind = if (needsManual) "assist" else if (scheme.actions.isEmpty()) "info" else "auto",
                phone = contact.orEmpty(),
                script = "我们行程有调整：$detail。和你说一声，别白跑一趟。",
            )
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

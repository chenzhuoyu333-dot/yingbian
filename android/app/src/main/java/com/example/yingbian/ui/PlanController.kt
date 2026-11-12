package com.example.yingbian.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.example.yingbian.data.Impact
import com.example.yingbian.data.DemoScenario
import com.example.yingbian.data.GeneratePrefs
import com.example.yingbian.data.Plan
import com.example.yingbian.data.PlanRepository
import com.example.yingbian.data.RepairAction
import com.example.yingbian.data.RepairScheme
import com.example.yingbian.data.Weather

enum class AppScreen(val label: String) {
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

class PlanController(private val repo: PlanRepository) {
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
    var loading by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var empty by mutableStateOf(false)
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
    var eventTitle by mutableStateOf("降雨 15:00–17:00")
        private set
    /** 生成后的提示（例如"必去点排不进去"），界面上用 Toast 或角标展示 */
    var generateNote by mutableStateOf<String?>(null)
        private set
    private var planBeforeApply: Plan? = null
    private var scenario = DemoScenario.RAIN

    val selectedScheme: RepairScheme?
        get() = schemes.firstOrNull { it.id == selectedSchemeId }

    suspend fun load() {
        scenario = DemoScenario.RAIN
        eventTitle = "降雨 15:00–17:00"
        loading = true
        error = null
        empty = false
        offline = false
        try {
            plan = repo.loadPlan()
            weather = runCatching { repo.weather() }.getOrNull()
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
            weather = runCatching { repo.weather() }.getOrNull()
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

    suspend fun undo() {
        loading = true
        error = null
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
            weather = runCatching { repo.weather() }.getOrNull()
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

            else -> TodoRow(
                id = index.toString(),
                text = "告知同行：$title 后移 ${action.payload["minutes"] ?: "0"} 分钟",
                phone = "",
                script = "我们临时调整了时间，$title 延后 ${action.payload["minutes"] ?: "0"} 分钟。",
            )
        }
    }
}

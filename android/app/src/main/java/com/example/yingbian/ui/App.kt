package com.example.yingbian.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.example.yingbian.data.ApiConfig
import com.example.yingbian.data.ApiSettings
import com.example.yingbian.data.LocationHelper
import com.example.yingbian.data.PlanNode
import com.example.yingbian.data.PatrolAlert
import com.example.yingbian.data.ServerDiscovery
import com.example.yingbian.data.createRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YingBianRoot() {
    val context = LocalContext.current
    val settings = remember { ApiSettings(context) }
    var repoVersion by remember { mutableIntStateOf(0) }
    val controller = remember(repoVersion) { PlanController(createRepository(context, settings), settings) }
    val scope = rememberCoroutineScope()
    val locationHelper = remember { LocationHelper(context) }
    val lifecycleOwner = remember(context) { context as? ComponentActivity }
    var foreground by remember {
        mutableStateOf(
            lifecycleOwner?.lifecycle?.currentState?.isAtLeast(Lifecycle.State.RESUMED) == true,
        )
    }
    DisposableEffect(lifecycleOwner) {
        val owner = lifecycleOwner
        if (owner == null) {
            foreground = true
            onDispose { }
        } else {
            val observer = LifecycleEventObserver { _, _ ->
                foreground = owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
            }
            owner.lifecycle.addObserver(observer)
            foreground = owner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
            onDispose { owner.lifecycle.removeObserver(observer) }
        }
    }
    var debugOpen by remember { mutableStateOf(false) }
    var settingsOpen by remember { mutableStateOf(false) }
    var voteOpen by remember { mutableStateOf(false) }
    var activityOpen by remember { mutableStateOf(false) }
    var patrolOpen by remember { mutableStateOf(false) }
    // 队友的住宿/停留节点状态
    var lodgingOpen by remember { mutableStateOf(false) }
    var stayNode by remember { mutableStateOf<PlanNode?>(null) }
    // 我的自动寻找服务器状态
    var findingServer by remember { mutableStateOf(false) }
    var addNodeOpen by remember { mutableStateOf(false) }
    var addNodeText by remember { mutableStateOf("") }
    var findHint by remember { mutableStateOf("") }

    /** 把一条管家提醒映射成既有的变化处理流程 */
    fun handlePatrolAlert(alert: PatrolAlert) {
        scope.launch {
            when (alert.kind) {
                // 天气：直接走降雨事件（由真实降雨提示触发）
                "weather" -> controller.simulateRain()
                // 来不及了 / 落后：按该节点报一个延后事件，让引擎算方案
                "closing", "behind" -> {
                    controller.reportDelay(alert.nodeId, 30)
                }
                else -> Unit
            }
        }
    }

    /** 手动触发自动寻找（错误页上的按钮） */
    suspend fun findServerManually() {
        findingServer = true
        findHint = ""
        try {
            val found = withContext(Dispatchers.IO) {
                ServerDiscovery.find(
                    known = settings.lastKnownBases + settings.baseUrl,
                    onPhase = { phase -> findHint = phase },
                )
            }
            if (found != null) {
                settings.baseUrl = found
                settings.lastKnownBases = listOf(found)
                findHint = "找到 " + found + "，正在重载…"
                repoVersion += 1
            } else {
                findHint = "没找到。" + ServerDiscovery.describeNetworks()
            }
        } finally {
            findingServer = false
        }
    }

    /** 打开"新建行程"整屏，并顺手把省市清单拉回来 */
    suspend fun openNewPlanPage() {
        controller.openScreen(AppScreen.NewPlan)
        controller.loadRegions()
    }

    suspend fun refreshWeatherFromLocation() {
        val point = withContext(Dispatchers.IO) { locationHelper.currentLocation() }
        if (point == null) {
            Toast.makeText(context, "没取到定位，仍可查看行程本身", Toast.LENGTH_LONG).show()
        } else {
            controller.refreshWeather(point.first, point.second)
        }
    }

    val locationLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        if (grants.values.any { it }) {
            scope.launch { refreshWeatherFromLocation() }
        } else {
            Toast.makeText(context, "没有定位权限，仍可查看行程本身", Toast.LENGTH_SHORT).show()
        }
    }

    fun useMyLocation() {
        if (locationHelper.hasPermission()) {
            scope.launch { refreshWeatherFromLocation() }
        } else {
            locationLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ),
            )
        }
    }

    /** 定位检查：拿当前位置问后端我现在该在哪，落后就给改法 */
    suspend fun runLocateCheck() {
        val point = withContext(Dispatchers.IO) { locationHelper.currentLocation() }
        if (point == null) {
            Toast.makeText(
                context,
                "没取到定位：请确认手机定位已打开、并允许本应用使用定位",
                Toast.LENGTH_LONG,
            ).show()
        } else {
            controller.checkLocation(point.first, point.second)
        }
    }

    val locateLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        if (grants.values.any { it }) {
            scope.launch { runLocateCheck() }
        } else {
            Toast.makeText(context, "没有定位权限，无法判断你是否到达", Toast.LENGTH_SHORT).show()
        }
    }

    fun useMyLocationForLocate() {
        if (locationHelper.hasPermission()) {
            scope.launch { runLocateCheck() }
        } else {
            locateLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ),
            )
        }
    }

    // 空态也要天气：进到"今天没安排"时按定位取一次，取不到才显示"取不到天气"
    LaunchedEffect(controller.todayEmpty) {
        if (controller.todayEmpty && controller.weather == null) {
            withContext(Dispatchers.IO) { locationHelper.lastKnown() }?.let { point ->
                controller.refreshWeather(point.first, point.second)
            }
        }
    }

    LaunchedEffect(repoVersion) {
        controller.loadHome()
        controller.loadToday()
        controller.joinTrip()
        // 打开就把天气/收口查一遍，不用等第一轮 60 秒巡检
        controller.runPatrol()

        // 启动自愈：连不上就自己找后端（校园网 / 热点 / 任何 Wi-Fi 都试）
        if (!settings.useMock && controller.error != null) {
            val found = withContext(Dispatchers.IO) {
                ServerDiscovery.find(known = settings.lastKnownBases)
            }
            if (found != null) {
                settings.baseUrl = found
                settings.lastKnownBases = listOf(found)
                Toast.makeText(context, "已自动连接到 " + found, Toast.LENGTH_SHORT).show()
                // 地址变了，重建仓储再加载
                repoVersion += 1
                return@LaunchedEffect
            }
        }

        controller.pollLoop()
    }

    // 前台自动感知：有定位权限时每分钟看一次，到点提示打卡，偏离提示改行程。
    // 不做后台定位、不上传轨迹；App 不在前台就不会跑。
    LaunchedEffect(repoVersion, foreground) {
        if (!foreground) return@LaunchedEffect
        while (true) {
            delay(60_000)
            if (controller.plan == null || controller.loading) continue
            if (!locationHelper.hasPermission()) continue
            val point = withContext(Dispatchers.IO) { locationHelper.currentLocation(5_000) } ?: continue
            controller.autoLocate(point.first, point.second)
        }
    }

    BackHandler(enabled = controller.screen != AppScreen.Plan) {
        controller.openScreen(AppScreen.Plan)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = when (controller.screen) {
                                AppScreen.Home -> "我的计划"
                                AppScreen.NewPlan -> "新建行程"
                                AppScreen.Plan -> controller.plan?.title ?: "应变"
                                AppScreen.Scheme -> "两套方案对比"
                                AppScreen.Notify -> "提醒"
                                AppScreen.Todo -> "待办清单"
                                AppScreen.Profile -> "我的"
                            },
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        // 首页不再显示日期：日期在每张卡片上已经有了，标题下再挂一个纯属重复
                        if (controller.screen != AppScreen.Home && controller.screen != AppScreen.NewPlan) {
                            Text(
                                text = controller.plan?.let { plan ->
                                    if (plan.endDate.isNotBlank() && plan.endDate != plan.date) {
                                        "${plan.date} → ${plan.endDate}"
                                    } else {
                                        plan.date
                                    }
                                } ?: "行程变化助手",
                                fontSize = 11.sp,
                                color = Muted,
                            )
                        }
                    }
                },
                actions = {
                    // 只有一个入口：加号 → 输入一句话生成行程
                    IconButton(onClick = { scope.launch { openNewPlanPage() } }) {
                        Icon(Icons.Default.Add, contentDescription = "新建行程")
                    }
                    if ((controller.plan?.version ?: 1) > 1) {
                        TextButton(onClick = { scope.launch { controller.requestUndo() } }) {
                            Text("撤销", fontSize = 13.sp)
                        }
                    }
                    IconButton(onClick = { settingsOpen = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "设置")
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar {
                // 只留三个：行程（今天）/ 方案 / 我的
                // 历史列表挪到「我的」，「提醒」并进行程页顶部管家卡
                listOf(
                    AppScreen.Plan,
                    AppScreen.Scheme,
                    AppScreen.Profile,
                ).forEach { screen ->
                    NavigationBarItem(
                        selected = controller.screen == screen,
                        onClick = { controller.openScreen(screen) },
                        icon = { Icon(screenIcon(screen), contentDescription = screen.label) },
                        label = { Text(screen.label, fontSize = 11.sp) },
                    )
                }
            }
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            if (controller.loading && controller.plan != null) {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
            }
            Box(modifier = Modifier.weight(1f)) {
                when {
                    // 注意："今天没行程"必须在 AppScreen.Plan 分支里判断。
                    // 放在这里会拦掉所有 tab —— 现场表现就是"点哪个都没反应"。
                    controller.empty -> EmptyScreen(onLoad = { scope.launch { controller.load() } })
                    controller.error != null -> ErrorScreen(
                        message = controller.error ?: "",
                        onRetry = { scope.launch { controller.load() } },
                        onCache = { controller.useCache() },
                        onFind = { scope.launch { findServerManually() } },
                        finding = findingServer,
                        findHint = findHint,
                    )

                    controller.screen == AppScreen.Home -> HomeScreen(
                        plans = controller.homePlans,
                        loading = controller.homeLoading,
                        onOpen = { id -> scope.launch { controller.openPlan(id) } },
                        onCreate = { scope.launch { openNewPlanPage() } },
                        onDelete = { id -> scope.launch { controller.removePlan(id) } },
                    )

                    controller.screen == AppScreen.Profile -> ProfileScreen(
                        memberName = settings.memberName,
                        memberId = settings.memberId,
                        baseUrl = settings.baseUrl,
                        useMock = settings.useMock,
                        memberCount = controller.members.size,
                        planTitle = controller.plan?.title.orEmpty(),
                        onRename = { name ->
                            settings.memberName = name
                            repoVersion += 1
                        },
                        onOpenSettings = { settingsOpen = true },
                        onOpenDebug = { debugOpen = true },
                    )

                    // 新建页不依赖“当前已有行程”：历史清空后也必须能进入。
                    controller.screen == AppScreen.NewPlan -> NewPlanScreen(
                        regions = controller.regions,
                        busy = controller.loading,
                        error = controller.error,
                        onLocate = {
                            withContext(Dispatchers.IO) { locationHelper.lastKnown() }
                        },
                        onCreate = { city, start, end, text, place, lat, lng, lodging, pace, maxTransit ->
                            scope.launch {
                                controller.createTrip(
                                    city, start, end, text, place, lat, lng, lodging, pace, maxTransit,
                                )
                                val note = controller.generateNote
                                if (!note.isNullOrBlank()) {
                                    Toast.makeText(context, note, Toast.LENGTH_SHORT).show()
                                    controller.clearGenerateNote()
                                }
                            }
                        },
                    )

                    controller.plan == null -> NoActivePlanScreen(
                        onCreate = { scope.launch { openNewPlanPage() } },
                        onOpenHome = { controller.openScreen(AppScreen.Home) },
                    )

                    else -> {
                        val plan = controller.plan!!
                        when (controller.screen) {
                            // 首页在上面的分支已经处理掉了；这里兜底防止万一
                            AppScreen.Home -> LoadingScreen()

                            // 新建页已在外层提前处理，这里只是保证 when 完整。
                            AppScreen.NewPlan -> LoadingScreen()

                            AppScreen.Plan -> if (controller.todayEmpty) {
                                NoPlanTodayScreen(
                                    weather = controller.weather,
                                    weatherLoading = controller.weatherLoading,
                                    weatherError = controller.weatherError,
                                    today = todayIso(),
                                    onNewPlan = { scope.launch { openNewPlanPage() } },
                                    onRefreshWeather = {
                                        scope.launch { refreshWeatherFromLocation() }
                                    },
                                )
                            } else PlanScreen(
                                plan = plan,
                                impact = controller.impact,
                                weather = controller.weather,
                                eventTitle = controller.eventTitle,
                                loading = controller.loading,
                                offline = controller.offline,
                                onRain = { scope.launch { controller.simulateRain() } },
                                onImpact = { controller.openImpact() },
                                onSchemes = { scope.launch { controller.loadSchemes() } },
                                onDepart = {
                                    Toast.makeText(
                                        context,
                                        "已记录出发；到下一站时点「我到了」",
                                        Toast.LENGTH_SHORT,
                                    ).show()
                                },
                                onCheckin = { controller.openCheckin() },
                                weatherLocation = controller.weatherLocation,
                                weatherError = controller.weatherError,
                                weatherLoading = controller.weatherLoading,
                                onUseLocation = { useMyLocation() },
                                onRefreshWeather = { scope.launch { controller.refreshPlanWeather() } },
                                onVote = {
                                    scope.launch {
                                        controller.startVote()
                                        voteOpen = true
                                    }
                                },
                                onActivity = { activityOpen = true },
                                onLocate = { useMyLocationForLocate() },
                                locateLoading = controller.locateLoading,
                                patrol = controller.patrolResult,
                                patrolDismissed = controller.patrolDismissed,
                                onOpenPatrol = { patrolOpen = true },
                                onDismissPatrol = { controller.dismissPatrol() },
                                memberCount = controller.members.size,
                                voteOpen = controller.vote?.isOpen == true,
                                onEditLodging = { lodgingOpen = true },
                                onAdjustStay = { node ->
                                    if (node.stayBasis.isNotBlank()) stayNode = node
                                    else Toast.makeText(context, "这一站没有可调停留信息", Toast.LENGTH_SHORT).show()
                                },
                            )

                            AppScreen.Scheme -> SchemeScreen(
                                plan = plan,
                                schemes = controller.schemes,
                                selectedId = controller.selectedSchemeId,
                                loading = controller.loading,
                                onSelect = { controller.selectScheme(it) },
                                onApply = { scope.launch { controller.applySelected() } },
                            )

                            AppScreen.Notify -> NotifyScreen(
                                notifications = controller.notifications,
                                onCall = { callNotification(context, it) },
                                onCopy = { copyNotification(context, it) },
                                onBack = { controller.openScreen(AppScreen.Plan) },
                            )

                            AppScreen.Todo -> TodoScreen(
                                todos = controller.todos,
                                done = controller.todoDone,
                                onToggle = { controller.toggleTodo(it) },
                                onCall = { call(context, it) },
                                onCopy = { copyScript(context, it) },
                                onCompleteAll = { controller.completeAllTodos() },
                                onBack = { controller.openScreen(AppScreen.Plan) },
                            )

                            AppScreen.Profile -> ProfileScreen(
                                memberName = settings.memberName,
                                memberId = settings.memberId,
                                baseUrl = settings.baseUrl,
                                useMock = settings.useMock,
                                memberCount = controller.members.size,
                                planTitle = plan.title,
                                onRename = { name ->
                                    settings.memberName = name
                                    repoVersion += 1
                                },
                                onOpenSettings = { settingsOpen = true },
                                onOpenDebug = { debugOpen = true },
                            )
                        }
                    }
                }
            }
        }
    }

    val currentPlan = controller.plan
    val currentImpact = controller.impact
    if (controller.undoPreviewOpen) {
        UndoDialog(
            preview = controller.undoPreview,
            onConfirm = {
                scope.launch {
                    controller.undo()
                    Toast.makeText(context, "已撤销到上一版", Toast.LENGTH_SHORT).show()
                }
            },
            onDismiss = { controller.cancelUndo() },
        )
    }
    controller.autoPrompt?.let { result ->
        AutoLocateDialog(
            result = result,
            onCheckin = {
                controller.dismissAutoPrompt()
                controller.openCheckin(result.atNodeId)
            },
            onFix = { controller.openAutoPromptFix() },
            onDismiss = { controller.dismissAutoPrompt() },
        )
    }
    controller.autoWeatherAlert?.let { alert ->
        WeatherChangeDialog(
            alert = alert,
            onFix = {
                controller.dismissAutoWeather()
                handlePatrolAlert(alert)
            },
            onDismiss = { controller.dismissAutoWeather() },
        )
    }
    if (controller.schemeSheetOpen && currentPlan != null) {
        SchemeSheet(
            plan = currentPlan,
            schemes = controller.schemes,
            selectedId = controller.selectedSchemeId,
            loading = controller.loading,
            onSelect = { controller.selectScheme(it) },
            onApply = {
                scope.launch {
                    controller.applySelected()
                    Toast.makeText(context, "已采用方案", Toast.LENGTH_SHORT).show()
                }
            },
            onDismiss = { controller.closeSchemes() },
        )
    }
    if (controller.showImpact && currentPlan != null && currentImpact != null) {
        ImpactSheet(
            plan = currentPlan,
            impact = currentImpact,
            eventTitle = controller.eventTitle,
            onDismiss = { controller.closeImpact() },
            onSchemes = { scope.launch { controller.loadSchemes() } },
        )
    }

    controller.blockedMessage?.let { message ->
        BlockedDialog(
            message = message,
            onUnlock = { scope.launch { controller.unlockAndRepair() } },
            onKeep = { controller.dismissBlocked() },
        )
    }

    if (controller.checkinOpen && currentPlan != null) {
        CheckinSheet(
            plan = currentPlan,
            result = controller.checkinResult,
            loading = controller.checkinLoading,
            error = controller.checkinError,
            selectedSchemeId = controller.checkinSelectedId,
            initialNodeId = controller.checkinInitialNodeId,
            onCheckin = { nodeId, minutes, personId ->
                scope.launch { controller.submitCheckin(nodeId, minutes, personId) }
            },
            onSelectScheme = { controller.selectCheckinScheme(it) },
            onApply = { scope.launch { controller.applyCheckinScheme() } },
            onDismiss = { controller.closeCheckin() },
        )
    }

    if (lodgingOpen && currentPlan != null) {
        LodgingDialog(
            initial = currentPlan.nodes.firstOrNull { it.overnight }?.place.orEmpty(),
            busy = controller.loading,
            onSave = { name ->
                scope.launch {
                    controller.updateLodging(name)
                    if (controller.error == null) {
                        lodgingOpen = false
                        controller.generateNote?.let {
                            Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
                            controller.clearGenerateNote()
                        }
                    }
                }
            },
            onDismiss = { lodgingOpen = false },
        )
    }

    stayNode?.let { node ->
        StayDialog(
            node = node,
            busy = controller.loading,
            onSave = { minutes ->
                scope.launch {
                    controller.updateStay(node.id, minutes)
                    if (controller.error == null) {
                        stayNode = null
                        controller.generateNote?.let {
                            Toast.makeText(context, it, Toast.LENGTH_SHORT).show()
                            controller.clearGenerateNote()
                        }
                    }
                }
            },
            onDismiss = { stayNode = null },
        )
    }

    controller.locateResult?.let { result ->
        LocateDialog(
            result = result,
            onUseScheme = { scheme ->
                scope.launch {
                    controller.applyLocateScheme(scheme)
                    controller.clearLocateResult()
                }
            },
            onDismiss = { controller.clearLocateResult() },
        )
    }

    if (voteOpen) {
        val vote = controller.vote
        if (vote != null) {
            VoteSheet(
                vote = vote,
                memberName = controller.memberName,
                members = controller.members,
                onVote = { schemeId -> scope.launch { controller.castVote(schemeId) } },
                onDismiss = { voteOpen = false },
            )
        } else {
            voteOpen = false
        }
    }

    if (activityOpen) {
        ActivityDialog(
            rows = controller.timelineRows,
            members = controller.members,
            onDismiss = { activityOpen = false },
        )
    }

    if (patrolOpen) {
        controller.patrolResult?.let { result ->
            PatrolDialog(
                result = result,
                onHandle = { alert ->
                    patrolOpen = false
                    handlePatrolAlert(alert)
                },
                onDismiss = { patrolOpen = false },
            )
        }
    }

    if (addNodeOpen) {
        AlertDialog(
            onDismissRequest = { addNodeOpen = false },
            title = { Text("加一站") },
            text = {
                Column {
                    Text("写个地名，我按真实通勤插进去，后面的点会顺延。", fontSize = 12.sp, color = Muted)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = addNodeText,
                        onValueChange = { addNodeText = it },
                        placeholder = { Text("比如「西湖音乐喷泉」", fontSize = 12.sp) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val title = addNodeText.trim()
                        if (title.isNotBlank()) {
                            addNodeOpen = false
                            scope.launch {
                                controller.addNodeHere(title)
                                val err = controller.error
                                if (err != null) {
                                    Toast.makeText(context, err, Toast.LENGTH_LONG).show()
                                } else {
                                    Toast.makeText(context, "已加上「" + title + "」", Toast.LENGTH_SHORT).show()
                                }
                                controller.clearGenerateNote()
                            }
                        }
                    },
                ) { Text("加上") }
            },
            dismissButton = { TextButton(onClick = { addNodeOpen = false }) { Text("取消") } },
        )
    }

    if (settingsOpen) {
        SettingsDialog(
            initialBase = settings.baseUrl,
            initialMock = settings.useMock,
            defaultBase = ApiConfig.defaultBase,
            defaultMock = ApiConfig.defaultMock,
            onSave = { base, mock ->
                if (!mock && base.isBlank()) {
                    Toast.makeText(context, "请先填写服务器地址", Toast.LENGTH_SHORT).show()
                } else {
                    settings.baseUrl = base
                    settings.useMock = mock
                    settingsOpen = false
                    repoVersion += 1
                }
            },
            onDebug = {
                settingsOpen = false
                debugOpen = true
            },
            onDismiss = { settingsOpen = false },
        )
    }

    if (debugOpen) {
        DebugDialog(
            onEmpty = {
                debugOpen = false
                controller.startEmpty()
            },
            onFailure = {
                debugOpen = false
                controller.forceFailure()
            },
            onBlocked = {
                debugOpen = false
                scope.launch { controller.demoBlocked() }
            },
            onCancelLunch = {
                debugOpen = false
                scope.launch { controller.demoCancelLunch() }
            },
            onReset = {
                debugOpen = false
                scope.launch { controller.resetDemo() }
            },
            onDismiss = { debugOpen = false },
        )
    }
}

private fun screenIcon(screen: AppScreen): ImageVector = when (screen) {
    AppScreen.Home -> Icons.Default.Menu
    AppScreen.NewPlan -> Icons.Default.Add
    AppScreen.Plan -> Icons.Default.Home
    AppScreen.Scheme -> Icons.Default.List
    AppScreen.Notify -> Icons.Default.Notifications
    AppScreen.Todo -> Icons.Default.CheckCircle
    AppScreen.Profile -> Icons.Default.Person
}

private fun call(context: Context, item: TodoRow) {
    runCatching {
        context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${item.phone}")))
    }
}

private fun copyScript(context: Context, item: TodoRow) {
    val manager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    manager.setPrimaryClip(ClipData.newPlainText("话术", item.script))
    Toast.makeText(context, "话术已复制", Toast.LENGTH_SHORT).show()
}

private fun callNotification(context: Context, item: NotificationRow) {
    if (item.phone.isBlank()) return
    runCatching {
        context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:${item.phone}")))
    }
}

private fun copyNotification(context: Context, item: NotificationRow) {
    val manager = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    manager.setPrimaryClip(ClipData.newPlainText("话术", item.script))
    Toast.makeText(context, "话术已复制", Toast.LENGTH_SHORT).show()
}

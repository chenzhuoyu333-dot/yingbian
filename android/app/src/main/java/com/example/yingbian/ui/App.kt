package com.example.yingbian.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
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
import com.example.yingbian.data.ApiConfig
import com.example.yingbian.data.ApiSettings
import com.example.yingbian.data.LocationHelper
import com.example.yingbian.data.createRepository
import kotlinx.coroutines.Dispatchers
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
    var debugOpen by remember { mutableStateOf(false) }
    var settingsOpen by remember { mutableStateOf(false) }
    var voteOpen by remember { mutableStateOf(false) }
    var newPlanOpen by remember { mutableStateOf(false) }
    var activityOpen by remember { mutableStateOf(false) }

    /** 打开"新建行程"整屏，并顺手把省市清单拉回来 */
    suspend fun openNewPlanPage() {
        controller.openScreen(AppScreen.NewPlan)
        controller.loadRegions()
    }

    /** 定位检查：拿当前位置问后端我现在该在哪，落后就给改法 */
    suspend fun useMyLocationForLocate() {
        val point = withContext(Dispatchers.IO) { locationHelper.lastKnown() }
        if (point == null) {
            Toast.makeText(context, "没取到定位，无法做定位检查", Toast.LENGTH_LONG).show()
        } else {
            controller.checkLocation(point.first, point.second)
        }
    }

    suspend fun refreshWeatherFromLocation() {
        val point = withContext(Dispatchers.IO) { locationHelper.lastKnown() }
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

    LaunchedEffect(repoVersion) {
        controller.loadHome()
        controller.load()
        controller.joinTrip()
        controller.pollLoop()
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
                                AppScreen.Notify -> "通知预览"
                                AppScreen.Todo -> "待办清单"
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
                        TextButton(onClick = { scope.launch { controller.undo() } }) {
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
                AppScreen.entries.filter { it != AppScreen.NewPlan }.forEach { screen ->
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
                    controller.empty -> EmptyScreen(onLoad = { scope.launch { controller.load() } })
                    controller.error != null -> ErrorScreen(
                        message = controller.error ?: "",
                        onRetry = { scope.launch { controller.load() } },
                        onCache = { controller.useCache() },
                    )

                    controller.screen == AppScreen.Home -> HomeScreen(
                        plans = controller.homePlans,
                        loading = controller.homeLoading,
                        onOpen = { id -> scope.launch { controller.openPlan(id) } },
                        onCreate = { scope.launch { openNewPlanPage() } },
                        onDelete = { id -> scope.launch { controller.removePlan(id) } },
                    )

                    controller.plan == null -> LoadingScreen()
                    else -> {
                        val plan = controller.plan!!
                        when (controller.screen) {
                            // 首页在上面的分支已经处理掉了；这里兜底防止万一
                            AppScreen.Home -> LoadingScreen()

                            AppScreen.NewPlan -> NewPlanScreen(
                                regions = controller.regions,
                                busy = controller.loading,
                                error = controller.error,
                                onLocate = {
                                    withContext(Dispatchers.IO) { locationHelper.lastKnown() }
                                },
                                onCreate = { city, start, end, text, place, lat, lng ->
                                    scope.launch {
                                        controller.createTrip(
                                            city, start, end, text, place, lat, lng,
                                        )
                                        val note = controller.generateNote
                                        if (!note.isNullOrBlank()) {
                                            Toast.makeText(context, note, Toast.LENGTH_SHORT).show()
                                            controller.clearGenerateNote()
                                        }
                                    }
                                },
                            )

                            AppScreen.Plan -> PlanScreen(
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
                                onVote = {
                                    scope.launch {
                                        controller.startVote()
                                        voteOpen = true
                                    }
                                },
                                onActivity = { activityOpen = true },
                                onLocate = { scope.launch { useMyLocationForLocate() } },
                                locateLoading = controller.locateLoading,
                                memberCount = controller.members.size,
                                voteOpen = controller.vote?.isOpen == true,
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
                                selection = controller.notificationSelection,
                                onToggle = { controller.toggleNotification(it) },
                                onConfirm = { controller.confirmNotifications() },
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
                        }
                    }
                }
            }
        }
    }

    val currentPlan = controller.plan
    val currentImpact = controller.impact
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
            onCheckin = { nodeId, minutes, personId ->
                scope.launch { controller.submitCheckin(nodeId, minutes, personId) }
            },
            onSelectScheme = { controller.selectCheckinScheme(it) },
            onApply = { scope.launch { controller.applyCheckinScheme() } },
            onDismiss = { controller.closeCheckin() },
        )
    }

    if (newPlanOpen) {
        NewPlanDialog(
            busy = controller.loading,
            error = controller.error,
            onGenerate = { text, startDate, days, lodging, avoidWalking ->
                scope.launch {
                    controller.createFromText(text, startDate, days, lodging, avoidWalking)
                    if (controller.error == null) {
                        newPlanOpen = false
                        controller.generateNote?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() }
                        controller.clearGenerateNote()
                    }
                }
            },
            onDismiss = { newPlanOpen = false },
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
            rows = controller.activityRows,
            members = controller.members,
            onDismiss = { activityOpen = false },
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

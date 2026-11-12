package com.example.yingbian.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Home
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
import com.example.yingbian.data.GeneratePrefs
import com.example.yingbian.data.createRepository
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun YingBianRoot() {
    val context = LocalContext.current
    val settings = remember { ApiSettings(context) }
    var repoVersion by remember { mutableIntStateOf(0) }
    val controller = remember(repoVersion) { PlanController(createRepository(context, settings)) }
    val scope = rememberCoroutineScope()
    var debugOpen by remember { mutableStateOf(false) }
    var settingsOpen by remember { mutableStateOf(false) }
    var generateOpen by remember { mutableStateOf(false) }

    LaunchedEffect(repoVersion) { controller.load() }

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
                                AppScreen.Plan -> controller.plan?.title ?: "应变"
                                AppScreen.Scheme -> "三方案对比"
                                AppScreen.Notify -> "通知预览"
                                AppScreen.Todo -> "待办清单"
                            },
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            text = controller.plan?.date ?: "行程变化助手",
                            fontSize = 11.sp,
                            color = Muted,
                        )
                    }
                },
                actions = {
                    TextButton(onClick = { generateOpen = true }) {
                        Text("生成行程", fontSize = 13.sp)
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
                AppScreen.entries.forEach { screen ->
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

                    controller.plan == null -> LoadingScreen()
                    else -> {
                        val plan = controller.plan!!
                        when (controller.screen) {
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

    if (generateOpen) {
        GenerateDialog(
            initial = remember { GeneratePrefs() },
            busy = controller.loading,
            error = controller.error,
            onGenerate = { prefs ->
                scope.launch {
                    controller.generate(prefs)
                    if (controller.error == null) {
                        generateOpen = false
                        val note = controller.generateNote
                        if (!note.isNullOrBlank()) {
                            Toast.makeText(context, note, Toast.LENGTH_SHORT).show()
                        }
                        controller.clearGenerateNote()
                    }
                }
            },
            onDismiss = { generateOpen = false },
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

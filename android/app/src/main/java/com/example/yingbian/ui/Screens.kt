package com.example.yingbian.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.yingbian.data.ActivityRow
import com.example.yingbian.data.CheckinResult
import com.example.yingbian.data.GeneratePrefs
import com.example.yingbian.data.Impact
import com.example.yingbian.data.MemberInfo
import com.example.yingbian.data.Plan
import com.example.yingbian.data.PlanNode
import com.example.yingbian.data.RepairScheme
import com.example.yingbian.data.VoteState
import com.example.yingbian.data.Weather

@Composable
fun PlanScreen(
    plan: Plan,
    impact: Impact?,
    weather: Weather?,
    eventTitle: String,
    loading: Boolean,
    offline: Boolean,
    onRain: () -> Unit,
    onImpact: () -> Unit,
    onSchemes: () -> Unit,
    onDepart: () -> Unit = {},
    onCheckin: () -> Unit = {},
    onVote: () -> Unit = {},
    onActivity: () -> Unit = {},
    memberCount: Int = 0,
    voteOpen: Boolean = false,
    weatherLocation: String = "默认位置",
    weatherError: String? = null,
    weatherLoading: Boolean = false,
    onUseLocation: () -> Unit = {},
) {
    Column(modifier = Modifier.fillMaxSize()) {
        WeatherCard(weather, weatherLocation, weatherError, weatherLoading, onUseLocation)
        if (offline) OfflineBanner()
        CollabBar(
            memberCount = memberCount,
            voteOpen = voteOpen,
            onVote = onVote,
            onActivity = onActivity,
        )
        if (plan.unresolvedMustVisit.isNotEmpty() || plan.generationWarnings.isNotEmpty()) {
            GenerateNotice(plan)
        }
        impact?.let { ImpactSummary(it, eventTitle, onImpact) }
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        ) {
            item {
                SectionHeader(
                    title = "今日行程",
                    subtitle = "${plan.nodes.size} 个节点 · 版本 ${plan.version}",
                )
            }
            itemsIndexed(plan.nodes, key = { _, node -> node.id }) { index, node ->
                NodeCard(
                    node = node,
                    state = impact?.stateOf(node.id) ?: "ok",
                    shift = impact?.shiftOf(node.id) ?: 0,
                )
                if (index < plan.nodes.lastIndex) {
                    EdgeLine(gapBetween(plan, node, plan.nodes[index + 1]))
                }
            }
            item { Spacer(Modifier.height(8.dp)) }
        }
        PlanBottomBar(
            impact = impact,
            loading = loading,
            offline = offline,
            onRain = onRain,
            onImpact = onImpact,
            onSchemes = onSchemes,
            onDepart = onDepart,
            onCheckin = onCheckin,
        )
    }
}

private fun gapBetween(plan: Plan, from: PlanNode, to: PlanNode): Int =
    plan.edges.firstOrNull { it.from == from.id && it.to == to.id }?.minGapMin ?: 0

@Composable
private fun WeatherCard(
    weather: Weather?,
    weatherLocation: String,
    weatherError: String?,
    weatherLoading: Boolean,
    onUseLocation: () -> Unit,
) {
    val demo = weather?.isDemo == true
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        color = if (demo) Color(0xFFFFF8E1) else SoftBlue,
        shape = RoundedCornerShape(16.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("天气", fontSize = 11.sp, color = Muted)
                    // 演示数据必须能一眼看出来，不能让假数据冒充真实预报
                    if (demo) {
                        Text(
                            text = "  演示数据",
                            fontSize = 11.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = Color(0xFF8A5A00),
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    if (weatherLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(14.dp),
                            strokeWidth = 2.dp,
                        )
                    }
                    TextButton(
                        onClick = onUseLocation,
                        contentPadding = PaddingValues(horizontal = 4.dp, vertical = 0.dp),
                    ) {
                        Text(
                            text = if (weatherLoading) "定位中" else "用我的位置",
                            fontSize = 11.sp,
                        )
                    }
                }
                Text(
                    text = weather?.text ?: if (weatherError != null) "天气获取失败" else "天气加载中",
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Ink,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Text(
                    text = buildString {
                        append(weather?.source ?: "等待获取")
                        append(" · ")
                        append(weatherLocation)
                        append(" · 更新于 ")
                        append(weather?.fetchedAt?.replace("T", " ") ?: "--")
                    },
                    fontSize = 10.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 2.dp),
                )
                // 依据：这个概率是怎么算出来的（真实来源时显示 pop，估算时显示规则）
                val basis = weather?.basis.orEmpty()
                if (basis.isNotBlank()) {
                    Text(
                        text = "依据：$basis",
                        fontSize = 9.sp,
                        color = Muted,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                val note = weather?.note.orEmpty()
                if (note.isNotBlank()) {
                    Text(
                        text = "说明：$note",
                        fontSize = 9.sp,
                        color = Color(0xFF8A5A00),
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
                if (!weatherError.isNullOrBlank()) {
                    Text(
                        text = "获取失败：$weatherError",
                        fontSize = 9.sp,
                        color = ConflictOrange,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
            }
            Text(
                text = "${((weather?.rainProb ?: 0.0) * 100).toInt()}%",
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
                color = if ((weather?.rainProb ?: 0.0) >= 0.6) ConflictOrange else OkGreen,
            )
        }
    }
}

/**
 * 生成提示：告诉用户"你点名的必去点没排进去"或"自检发现了什么"。
 *
 * 这一块是必须的 —— 生成器静默丢掉必去点，用户会以为计划里已经有它了，
 * 到现场才发现没排，比不生成还糟。
 */
@Composable
private fun GenerateNotice(plan: Plan) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        color = Color(0xFFFFF1F0),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            if (plan.unresolvedMustVisit.isNotEmpty()) {
                Text(
                    text = "必去点待确认：${plan.unresolvedMustVisit.joinToString("、")}",
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = ConflictOrange,
                )
                Text(
                    text = "这些地点没搜到，暂时没排进行程，需要你手动确认",
                    fontSize = 10.sp,
                    color = Muted,
                )
            }
            plan.generationWarnings.take(3).forEach { warning ->
                Text(
                    text = "· $warning",
                    fontSize = 10.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
    }
}

/**
 * 协作条：谁在一起出行、现在有没有在投票。
 *
 * 放在天气卡下面而不是藏进设置，因为多人是这件产品的核心之一，
 * 演示时要一眼能看到"还有谁在"。
 */
@Composable
private fun CollabBar(
    memberCount: Int,
    voteOpen: Boolean,
    onVote: () -> Unit,
    onActivity: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
        color = Color(0xFFF3F0FF),
        shape = RoundedCornerShape(12.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = if (memberCount > 1) "$memberCount 人同行" else "单人演示",
                fontSize = 11.sp,
                color = Muted,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onActivity) { Text("协作记录", fontSize = 11.sp) }
            TextButton(onClick = onVote) {
                Text(if (voteOpen) "投票中…" else "发起投票", fontSize = 11.sp)
            }
        }
    }
}

@Composable
fun OfflineBanner() {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color(0xFFFFF8E1),
    ) {
        Text(
            text = "离线：显示上次缓存，暂时无法重算",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 7.dp),
            fontSize = 12.sp,
            color = Color(0xFF8A5A00),
        )
    }
}

@Composable
private fun PlanBottomBar(
    impact: Impact?,
    loading: Boolean,
    offline: Boolean,
    onRain: () -> Unit,
    onImpact: () -> Unit,
    onSchemes: () -> Unit,
    onDepart: () -> Unit,
    onCheckin: () -> Unit,
) {
    Surface(color = Color.White, shadowElevation = 10.dp) {
        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            val enabled = !loading && !offline
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = onDepart,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 4.dp, vertical = 8.dp),
                ) {
                    Text("我出发了", fontSize = 12.sp)
                }
                Button(
                    onClick = onCheckin,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 4.dp, vertical = 8.dp),
                ) {
                    Text("我到了", fontSize = 12.sp)
                }
                OutlinedButton(
                    onClick = onRain,
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                    contentPadding = PaddingValues(horizontal = 4.dp, vertical = 8.dp),
                ) {
                    Text(if (impact == null) "下雨演示" else "再算降雨", fontSize = 12.sp)
                }
            }
            if (loading) {
                Text(
                    text = "正在重算…",
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    fontSize = 11.sp,
                    color = Muted,
                    textAlign = TextAlign.Center,
                )
            } else if (impact != null) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(
                        onClick = onImpact,
                        enabled = !offline,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("看影响")
                    }
                    Button(
                        onClick = onSchemes,
                        enabled = !offline,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text("看方案")
                    }
                }
            } else if (offline) {
                Text(
                    text = "离线，只能查看缓存，不能重算或打卡",
                    modifier = Modifier.padding(top = 6.dp),
                    fontSize = 11.sp,
                    color = Muted,
                )
            }
        }
    }
}

/**
 * 主动到达打卡。位置只用于这一次打卡，不持续定位、不共享轨迹。
 * 晚到后才展示可执行方案，用户确认前不改行程。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheckinSheet(
    plan: Plan,
    result: CheckinResult?,
    loading: Boolean,
    error: String?,
    selectedSchemeId: String?,
    onCheckin: (nodeId: String, minutes: Int, personId: String?) -> Unit,
    onSelectScheme: (String) -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var nodeId by remember(plan.planId) {
        mutableStateOf(
            plan.nodes.firstOrNull { !it.confirmed }?.id
                ?: plan.nodes.firstOrNull()?.id.orEmpty(),
        )
    }
    var minutes by remember { mutableStateOf(0) }
    var memberLate by remember { mutableStateOf(false) }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .padding(bottom = 28.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Text("我到了", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
            Text(
                "只记录这一次主动打卡，不共享位置轨迹；晚到方案要你确认后才会改行程。",
                fontSize = 11.sp,
                color = Muted,
                modifier = Modifier.padding(top = 4.dp),
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))

            if (result == null) {
                Text("到达哪个节点", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(6.dp))
                plan.nodes.forEach { node ->
                    val picked = node.id == nodeId
                    val label = "${node.start}  ${node.title}${if (node.confirmed) "  · 已锁定" else ""}"
                    if (picked) {
                        Button(
                            onClick = { nodeId = node.id },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                        ) {
                            Text(label, fontSize = 12.sp, modifier = Modifier.fillMaxWidth())
                        }
                    } else {
                        OutlinedButton(
                            onClick = { nodeId = node.id },
                            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 6.dp),
                        ) {
                            Text(label, fontSize = 12.sp, modifier = Modifier.fillMaxWidth())
                        }
                    }
                }

                Spacer(Modifier.height(12.dp))
                Text("谁晚到", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = { memberLate = false },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(if (memberLate) "我晚到" else "✓ 我晚到", fontSize = 12.sp)
                    }
                    OutlinedButton(
                        onClick = { memberLate = true },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(if (memberLate) "✓ 同行人晚到" else "同行人晚到", fontSize = 12.sp)
                    }
                }
                if (memberLate) {
                    Text(
                        "只同步“同行人晚到”这个状态，不发送对方位置。",
                        fontSize = 10.sp,
                        color = Muted,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }

                Spacer(Modifier.height(12.dp))
                Text("晚到多久", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.height(6.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(0 to "准时", 10 to "10 分", 20 to "20 分", 30 to "30 分").forEach { (value, label) ->
                        if (minutes == value) {
                            Button(
                                onClick = { minutes = value },
                                modifier = Modifier.weight(1f),
                                contentPadding = PaddingValues(horizontal = 2.dp, vertical = 8.dp),
                            ) {
                                Text(label, fontSize = 11.sp)
                            }
                        } else {
                            OutlinedButton(
                                onClick = { minutes = value },
                                modifier = Modifier.weight(1f),
                                contentPadding = PaddingValues(horizontal = 2.dp, vertical = 8.dp),
                            ) {
                                Text(label, fontSize = 11.sp)
                            }
                        }
                    }
                }

                if (!error.isNullOrBlank()) {
                    Text(
                        "打卡失败：$error",
                        fontSize = 12.sp,
                        color = ConflictOrange,
                        modifier = Modifier.padding(top = 10.dp),
                    )
                }
                Spacer(Modifier.height(14.dp))
                Button(
                    onClick = {
                        onCheckin(
                            nodeId,
                            minutes,
                            if (memberLate) "同行人" else null,
                        )
                    },
                    enabled = !loading && nodeId.isNotBlank(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = Color.White,
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(if (loading) "正在计算影响…" else "确认到达")
                }
                TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                    Text("取消")
                }
            } else {
                Text(result.message, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                result.impact?.let { impact ->
                    Text(
                        "影响 ${impact.affectedCount}/${impact.totalCount} 个节点 · ${pathLabel(impact.path)}",
                        fontSize = 11.sp,
                        color = Muted,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))

                if (result.schemes.isEmpty()) {
                    Text(
                        "没有安全的自动改法。你可以先不改，晚一点再手动调整。",
                        fontSize = 13.sp,
                        color = Muted,
                    )
                } else {
                    result.schemes.forEach { scheme ->
                        SchemeCard(
                            scheme = scheme,
                            plan = plan,
                            selected = scheme.id == selectedSchemeId,
                            onClick = { onSelectScheme(scheme.id) },
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                }

                if (!error.isNullOrBlank()) {
                    Text(
                        "应用失败：$error",
                        fontSize = 12.sp,
                        color = ConflictOrange,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(
                        onClick = onDismiss,
                        enabled = !loading,
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(if (result.schemes.isEmpty()) "知道了" else "先不改")
                    }
                    if (result.schemes.isNotEmpty()) {
                        Button(
                            onClick = onApply,
                            enabled = !loading && selectedSchemeId != null,
                            modifier = Modifier.weight(1f),
                        ) {
                            Text(if (loading) "应用中…" else "采用选中方案")
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SchemeScreen(
    plan: Plan,
    schemes: List<RepairScheme>,
    selectedId: String?,
    loading: Boolean,
    onSelect: (String) -> Unit,
    onApply: () -> Unit,
) {
    if (schemes.isEmpty()) {
        EmptyHint("还没有方案，先在行程页模拟一次下雨")
        return
    }
    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "按“保时间 / 保体验 / 保少改动”生成，选一套采用",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            fontSize = 12.sp,
            color = Muted,
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            items(schemes, key = { it.id }) { scheme ->
                SchemeCard(
                    scheme = scheme,
                    plan = plan,
                    selected = scheme.id == selectedId,
                    onClick = { onSelect(scheme.id) },
                )
            }
            item { Spacer(Modifier.height(6.dp)) }
        }
        Surface(color = Color.White, shadowElevation = 10.dp) {
            Button(
                onClick = onApply,
                enabled = selectedId != null && !loading,
                modifier = Modifier.fillMaxWidth().padding(16.dp),
            ) {
                Text("采用选中的方案")
            }
        }
    }
}

@Composable
fun NotifyScreen(
    notifications: List<NotificationRow>,
    selection: Set<String>,
    onToggle: (String) -> Unit,
    onConfirm: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "通知对象由你确认，系统不替你猜谁该被通知",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            fontSize = 12.sp,
            color = Muted,
        )
        Text(
            text = "已选 ${selection.size} / ${notifications.size} 条通知",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            fontSize = 12.sp,
            color = Muted,
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(notifications, key = { it.id }) { row ->
                NotifyRow(
                    row = row,
                    checked = row.id in selection,
                    onCheckedChange = { onToggle(row.id) },
                )
            }
            item { Spacer(Modifier.height(6.dp)) }
        }
        Surface(color = Color.White, shadowElevation = 10.dp) {
            Button(
                onClick = onConfirm,
                enabled = selection.isNotEmpty(),
                modifier = Modifier.fillMaxWidth().padding(16.dp),
            ) {
                Text("确认并生成待办")
            }
        }
    }
}

@Composable
fun TodoScreen(
    todos: List<TodoRow>,
    done: Set<String>,
    onToggle: (String) -> Unit,
    onCall: (TodoRow) -> Unit,
    onCopy: (TodoRow) -> Unit,
    onCompleteAll: () -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "已完成 ${done.size}/${todos.size} 件",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            fontSize = 12.sp,
            color = Muted,
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(todos, key = { it.id }) { item ->
                ActionRow(
                    item = item,
                    done = item.id in done,
                    onToggle = { onToggle(item.id) },
                    onCall = { onCall(item) },
                    onCopy = { onCopy(item) },
                )
            }
            item { Spacer(Modifier.height(6.dp)) }
        }
        Row(
            modifier = Modifier.fillMaxWidth().padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedButton(onClick = onCompleteAll, modifier = Modifier.weight(1f)) {
                Text("全部完成")
            }
            Button(onClick = onBack, modifier = Modifier.weight(1f)) {
                Text("返回行程")
            }
        }
    }
}

@Composable
fun SectionHeader(title: String, subtitle: String) {
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Text(subtitle, fontSize = 12.sp, color = Muted, modifier = Modifier.padding(top = 2.dp))
    }
}

@Composable
fun EmptyHint(message: String) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = message,
            modifier = Modifier.padding(32.dp),
            textAlign = TextAlign.Center,
            fontSize = 14.sp,
            color = Muted,
        )
    }
}

@Composable
fun EmptyScreen(onLoad: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("还没有行程", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Text(
            "载入示例计划开始演示",
            fontSize = 13.sp,
            color = Muted,
            modifier = Modifier.padding(top = 6.dp, bottom = 18.dp),
        )
        Button(onClick = onLoad) { Text("载入示例") }
    }
}

@Composable
fun LoadingScreen() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            CircularProgressIndicator()
            Text("正在载入行程…", fontSize = 13.sp, color = Muted, modifier = Modifier.padding(top = 12.dp))
        }
    }
}

@Composable
fun ErrorScreen(message: String, onRetry: () -> Unit, onCache: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("出了点问题", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Text(
            message,
            fontSize = 13.sp,
            color = InvalidRed,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp, bottom = 18.dp),
        )
        Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("重试") }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onCache, modifier = Modifier.fillMaxWidth()) { Text("用离线缓存") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImpactSheet(
    plan: Plan,
    impact: Impact,
    eventTitle: String,
    onDismiss: () -> Unit,
    onSchemes: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp),
        ) {
            Text(eventTitle, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
            Text(
                "影响 ${impact.affectedCount}/${impact.totalCount} 个节点 · " +
                    "${Math.round(impact.ratio * 100)}% · ${pathLabel(impact.path)}",
                fontSize = 12.sp,
                color = Muted,
                modifier = Modifier.padding(top = 4.dp),
            )
            HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))
            val affected = plan.nodes.filter { impact.stateOf(it.id) != "ok" }
            if (affected.isEmpty()) {
                Text("没有节点受影响", fontSize = 13.sp, color = Muted)
            } else {
                affected.forEach { node ->
                    ImpactRow(
                        node = node,
                        state = impact.stateOf(node.id),
                        reason = impactReason(node, impact.stateOf(node.id)),
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                OutlinedButton(onClick = onDismiss, modifier = Modifier.weight(1f)) {
                    Text("先不改")
                }
                Button(onClick = onSchemes, modifier = Modifier.weight(1f)) {
                    Text("看方案")
                }
            }
        }
    }
}

private fun impactReason(node: PlanNode, state: String): String = when (state) {
    "at_risk" -> if (!node.indoor) "室外，降雨概率 70%" else "受上游变化影响"
    "invalid" -> node.windowLatest?.let { "最晚 $it 开始，当前时间装不下" } ?: "已取消或临时关闭"
    "conflict" -> "你锁定了这个节点，需要你确认"
    else -> "正常"
}

@Composable
fun BlockedDialog(
    message: String,
    onUnlock: () -> Unit,
    onKeep: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onKeep,
        title = { Text("需要你决定") },
        text = { Text(message, fontSize = 14.sp, color = Ink) },
        confirmButton = {
            Button(onClick = onUnlock) { Text("解锁并重算") }
        },
        dismissButton = {
            TextButton(onClick = onKeep) { Text("保持不变") }
        },
    )
}

@Composable
fun DebugDialog(
    onEmpty: () -> Unit,
    onFailure: () -> Unit,
    onBlocked: () -> Unit,
    onCancelLunch: () -> Unit,
    onReset: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("调试状态") },
        text = {
            Column {
                Text("演示用，正式答辩时不点这里。", fontSize = 12.sp, color = Muted)
                Spacer(Modifier.height(8.dp))
                DebugAction("空状态：没有行程", onEmpty)
                DebugAction("失败状态：后端超时", onFailure)
                DebugAction("阻断演示：锁定日落点 + 降雨", onBlocked)
                DebugAction("餐厅取消：生成可拨号的待办", onCancelLunch)
                DebugAction("恢复：重新载入", onReset)
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("关闭") }
        },
    )
}

/**
 * 投票面板：影响大的变化不该由"谁手快"决定。
 *
 * 显示票数、剩余时间、我投了哪个，结束后显示结论与判定方式
 * （全员已投 / 超时兜底 / 平票兜底）——判定方式必须让用户看得见，
 * 否则"为什么是这个方案"又要吵一轮。
 */
@Composable
fun VoteSheet(
    vote: VoteState,
    memberName: String,
    members: List<MemberInfo>,
    onVote: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val label = mapOf("A" to "保时间", "B" to "保体验", "C" to "保少改动")
    val myVote = vote.votes.entries.firstOrNull { it.value.isNotBlank() }?.value

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(if (vote.isOpen) "投票决定怎么改" else "投票已结束")
        },
        text = {
            Column {
                Text(vote.event, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Text(
                    text = "已投 ${vote.totalVotes}/${members.size} 人" +
                        if (vote.isOpen) " · 剩余 ${vote.remainingSec} 秒" else "",
                    fontSize = 11.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Spacer(Modifier.height(10.dp))

                vote.options.forEach { option ->
                    val count = vote.tally[option] ?: 0
                    val picked = vote.winner == option
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "$option ${label[option] ?: ""}",
                            fontSize = 12.sp,
                            fontWeight = if (picked) FontWeight.Bold else FontWeight.Normal,
                            color = if (picked) OkGreen else Ink,
                            modifier = Modifier.width(96.dp),
                        )
                        Text(
                            text = "$count 票",
                            fontSize = 12.sp,
                            color = if (count > 0) Ink else Muted,
                            modifier = Modifier.weight(1f),
                        )
                        if (vote.isOpen) {
                            OutlinedButton(onClick = { onVote(option) }) {
                                Text(if (myVote == option) "已投" else "投它", fontSize = 11.sp)
                            }
                        }
                    }
                }

                if (!vote.isOpen) {
                    Spacer(Modifier.height(10.dp))
                    val reason = when (vote.decidedBy) {
                        "all-voted" -> "全员已投"
                        "majority" -> "超时按当前票数"
                        "tie-default" -> "平票，按默认方案"
                        "timeout-default" -> "超时无人领先，按默认方案"
                        else -> vote.decidedBy
                    }
                    Text(
                        text = "结论：方案 ${vote.winner ?: "-"} 通过（$reason）",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = OkGreen,
                    )
                } else if (myVote == null) {
                    Spacer(Modifier.height(8.dp))
                    Text("你还没投 —— $memberName", fontSize = 11.sp, color = ConflictOrange)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) { Text("关闭") }
        },
    )
}

/** 活动记录：谁在什么时候改了什么，替代群聊刷屏 */
@Composable
fun ActivityDialog(
    rows: List<ActivityRow>,
    members: List<MemberInfo>,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("协作记录") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                if (members.isNotEmpty()) {
                    Text(
                        text = "参与：${members.joinToString("、") { it.name }}",
                        fontSize = 11.sp,
                        color = Muted,
                    )
                    Spacer(Modifier.height(8.dp))
                }
                if (rows.isEmpty()) {
                    Text("还没有记录", fontSize = 12.sp, color = Muted)
                }
                rows.take(20).forEach { row ->
                    Text(
                        text = "${row.at.takeLast(5)}  ${row.name}：${row.text}",
                        fontSize = 11.sp,
                        color = Ink,
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
private fun DebugAction(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Text(label, fontSize = 13.sp, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Start)
    }
}

/**
 * 按偏好生成行程。
 *
 * 只做输入，不做排程 —— 排程在后端（Python 的 generate.py），
 * 这样"为什么这样排"有唯一一处可解释的实现，App 只负责把偏好送出去、把结果画出来。
 */
@Composable
fun GenerateDialog(
    initial: GeneratePrefs,
    busy: Boolean,
    error: String?,
    onGenerate: (GeneratePrefs) -> Unit,
    onDismiss: () -> Unit,
) {
    var city by remember { mutableStateOf(initial.city) }
    var date by remember { mutableStateOf(initial.date) }
    var start by remember { mutableStateOf(initial.startTime) }
    var end by remember { mutableStateOf(initial.endTime) }
    var interests by remember { mutableStateOf(initial.interests.joinToString("、")) }
    var mustVisit by remember { mutableStateOf(initial.mustVisit.joinToString("、")) }
    var avoid by remember { mutableStateOf(initial.avoid.joinToString("、")) }
    var pace by remember { mutableStateOf(initial.pace) }
    var maxTransit by remember { mutableStateOf(initial.maxTransitMin.toString()) }

    fun split(text: String): List<String> =
        text.split("、", ",", "，", " ")
            .map { it.trim() }
            .filter { it.isNotEmpty() }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("按偏好生成行程") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(
                    text = "地点来自高德 POI 检索，停留时长为经验值，通勤为估算 —— 生成后每个都会标「待确认」，请自己过一遍。",
                    fontSize = 11.sp,
                    color = Muted,
                )
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = city,
                    onValueChange = { city = it },
                    label = { Text("城市") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = date,
                        onValueChange = { date = it },
                        label = { Text("日期") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(8.dp))

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = start,
                        onValueChange = { start = it },
                        label = { Text("几点出发") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = end,
                        onValueChange = { end = it },
                        label = { Text("几点结束") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(8.dp))

                OutlinedTextField(
                    value = interests,
                    onValueChange = { interests = it },
                    label = { Text("想去的类型（用、分隔）") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))

                OutlinedTextField(
                    value = mustVisit,
                    onValueChange = { mustVisit = it },
                    label = { Text("必去地点名（会被锁定）") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))

                OutlinedTextField(
                    value = avoid,
                    onValueChange = { avoid = it },
                    label = { Text("不想要的（如 爬山）") },
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))

                Text("节奏", fontSize = 12.sp, color = Muted)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("relaxed" to "轻松", "normal" to "适中", "packed" to "紧凑").forEach { (value, label) ->
                        val picked = pace == value
                        OutlinedButton(
                            onClick = { pace = value },
                            modifier = Modifier.weight(1f),
                        ) {
                            Text(
                                text = label,
                                fontSize = 12.sp,
                                fontWeight = if (picked) FontWeight.Bold else FontWeight.Normal,
                                color = if (picked) Ink else Muted,
                            )
                        }
                    }
                }
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = maxTransit,
                    onValueChange = { maxTransit = it.filter { ch -> ch.isDigit() } },
                    label = { Text("相邻两站最多走几分钟") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                if (!error.isNullOrBlank()) {
                    Spacer(Modifier.height(10.dp))
                    Text(text = "生成失败：$error", fontSize = 12.sp, color = ConflictOrange)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onGenerate(
                        GeneratePrefs(
                            city = city.trim().ifBlank { "杭州" },
                            date = date.trim().ifBlank { "2026-11-14" },
                            startTime = start.trim().ifBlank { "09:30" },
                            endTime = end.trim().ifBlank { "20:00" },
                            interests = split(interests).ifEmpty { listOf("景点", "公园", "咖啡") },
                            mustVisit = split(mustVisit),
                            avoid = split(avoid),
                            pace = pace,
                            maxTransitMin = maxTransit.toIntOrNull() ?: 45,
                        ),
                    )
                },
                enabled = !busy,
            ) {
                Text(if (busy) "生成中…" else "生成")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("取消") }
        },
    )
}

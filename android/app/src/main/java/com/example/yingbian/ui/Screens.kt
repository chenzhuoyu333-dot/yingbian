package com.example.yingbian.ui

import androidx.compose.foundation.background
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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.yingbian.data.Impact
import com.example.yingbian.data.Plan
import com.example.yingbian.data.PlanNode
import com.example.yingbian.data.RepairScheme
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
) {
    Column(modifier = Modifier.fillMaxSize()) {
        WeatherCard(weather)
        if (offline) OfflineBanner()
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
        )
    }
}

private fun gapBetween(plan: Plan, from: PlanNode, to: PlanNode): Int =
    plan.edges.firstOrNull { it.from == from.id && it.to == to.id }?.minGapMin ?: 0

@Composable
private fun WeatherCard(weather: Weather?) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        color = SoftBlue,
        shape = RoundedCornerShape(16.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("天气", fontSize = 11.sp, color = Muted)
                Text(
                    text = weather?.text ?: "天气加载中",
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Ink,
                    modifier = Modifier.padding(top = 2.dp),
                )
                Text(
                    text = buildString {
                        append(weather?.source ?: "本地示例")
                        append(" · 更新于 ")
                        append(weather?.fetchedAt?.replace("T", " ") ?: "--")
                    },
                    fontSize = 10.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 2.dp),
                )
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
) {
    Surface(color = Color.White, shadowElevation = 10.dp) {
        Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            if (loading) {
                Button(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth()) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = Color.White,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("正在重算…")
                }
            } else if (impact == null) {
                Button(
                    onClick = onRain,
                    enabled = !offline,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (offline) "离线，无法重算" else "模拟下雨（15:00–17:00）")
                }
            } else {
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

@Composable
private fun DebugAction(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Text(label, fontSize = 13.sp, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Start)
    }
}

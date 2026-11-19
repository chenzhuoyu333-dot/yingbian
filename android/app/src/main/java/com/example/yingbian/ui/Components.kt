package com.example.yingbian.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.yingbian.data.Impact
import com.example.yingbian.data.Plan
import com.example.yingbian.data.PlanEdge
import com.example.yingbian.data.PlanNode
import com.example.yingbian.data.RepairAction
import com.example.yingbian.data.RepairScheme
import java.util.Locale

val OkGreen = Color(0xFF2E7D32)
val RiskAmber = Color(0xFFF9A825)
val InvalidRed = Color(0xFFC62828)
val ConflictOrange = Color(0xFFEF6C00)
val Ink = Color(0xFF1F2933)
val Muted = Color(0xFF6B7280)
val LineGrey = Color(0xFFD5DBDB)
val SoftBlue = Color(0xFFEFF6FF)

fun stateColor(state: String): Color = when (state) {
    "at_risk" -> RiskAmber
    "invalid" -> InvalidRed
    "conflict" -> ConflictOrange
    else -> OkGreen
}

fun stateLabel(state: String): String = when (state) {
    "at_risk" -> "有风险"
    "invalid" -> "不可行"
    "conflict" -> "锁定冲突"
    else -> "正常"
}

fun pathLabel(path: String): String = when (path) {
    "vote" -> "发起变更投票"
    "global" -> "全体共同变更"
    else -> "局部修复"
}

fun actionSummary(action: RepairAction, plan: Plan): String {
    val from = action.payload["fromTitle"] ?: plan.node(action.nodeId)?.title ?: action.nodeId
    return when (action.action) {
        "replace" -> "$from → ${action.payload["toTitle"] ?: "备选"}"
        "drop" -> "$from：取消"
        "shift" -> "$from：后移 ${action.payload["minutes"] ?: "0"} 分钟"
        "trim" -> "$from：停留缩短 ${action.payload["minutes"] ?: "0"} 分钟"
        else -> "$from：${action.reason}"
    }
}

@Composable
fun StateBadge(state: String) {
    val color = stateColor(state)
    Surface(
        color = color.copy(alpha = 0.13f),
        contentColor = color,
        shape = RoundedCornerShape(50),
    ) {
        Text(
            text = stateLabel(state),
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun NodeCard(node: PlanNode, state: String, shift: Int) {
    val accent = stateColor(state)
    val overnight = node.overnight
    val hotelUnknown = overnight && node.place.isBlank()
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.width(56.dp),
            horizontalAlignment = Alignment.End,
        ) {
            Text(
                text = when {
                    hotelUnknown -> "过夜"
                    overnight -> node.startWithShift(shift)
                    else -> node.startWithShift(shift)
                },
                fontSize = if (overnight) 13.sp else 15.sp,
                fontWeight = FontWeight.Bold,
                color = if (state == "ok") Ink else accent,
            )
            Text(
                text = when {
                    hotelUnknown -> "住宿待定"
                    overnight -> "到店"
                    else -> node.endWithShift(shift)
                },
                fontSize = if (overnight) 9.sp else 11.sp,
                color = Muted,
            )
        }
        Box(modifier = Modifier.width(24.dp), contentAlignment = Alignment.Center) {
            Box(
                modifier = Modifier
                    .size(if (state == "ok") 8.dp else 12.dp)
                    .background(accent, CircleShape),
            )
        }
        Card(
            modifier = Modifier.weight(1f),
            shape = RoundedCornerShape(14.dp),
            colors = CardDefaults.cardColors(
                containerColor = if (state == "ok") Color.White else accent.copy(alpha = 0.08f),
            ),
            elevation = CardDefaults.cardElevation(defaultElevation = if (state == "ok") 1.dp else 0.dp),
        ) {
            Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = node.title,
                        modifier = Modifier.weight(1f),
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = Ink,
                    )
                    if (node.confirmed) {
                        Icon(
                            imageVector = Icons.Default.Lock,
                            contentDescription = "已锁定",
                            modifier = Modifier.size(14.dp),
                            tint = Muted,
                        )
                        Spacer(Modifier.width(6.dp))
                    }
                    if (state != "ok") StateBadge(state)
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    text = if (hotelUnknown) {
                        "具体酒店待定 · 入住时间与酒店通勤未计入"
                    } else if (overnight) {
                        listOf(
                            node.place,
                            "过夜",
                            "次日从这里出发",
                        ).filter { it.isNotBlank() }.joinToString(" · ")
                    } else {
                        listOf(
                            node.place,
                            if (node.indoor) "室内" else "室外",
                            "${node.durationMin} 分钟",
                        ).filter { it.isNotBlank() }.joinToString(" · ")
                    },
                    fontSize = 12.sp,
                    color = Muted,
                )
            }
        }
    }
}

@Composable
fun EdgeLine(edge: PlanEdge?) {
    val transport = edge?.transport
    val detail = when {
        transport?.source == "placeholder" -> transport.text.ifBlank { "酒店待定，通勤时间未估算" }
        transport != null -> {
            val distance = when {
                transport.distanceM <= 0 -> ""
                transport.distanceM < 1000 -> "${transport.distanceM} 米"
                else -> String.format(Locale.CHINA, "%.1f 公里", transport.distanceM / 1000.0)
            }
            listOf(
                transport.label.ifBlank { transport.text },
                distance,
                if (transport.durationMin > 0) "约 ${transport.durationMin} 分钟" else "",
                if (transport.walkM > 0 && transport.mode != "walk") "步行 ${transport.walkM} 米" else "",
                if (transport.fromMap) "高德预估" else "估算",
            ).filter { it.isNotBlank() }.joinToString(" · ")
        }
        (edge?.minGapMin ?: 0) > 0 -> "缓冲 ${edge?.minGapMin} 分钟"
        else -> ""
    }
    Row(modifier = Modifier.height(38.dp)) {
        Spacer(Modifier.width(56.dp))
        Box(modifier = Modifier.width(24.dp).fillMaxHeight()) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val x = size.width / 2f
                drawLine(
                    color = LineGrey,
                    start = Offset(x, 0f),
                    end = Offset(x, size.height),
                    strokeWidth = 3f,
                )
            }
        }
        if (detail.isNotBlank()) {
            Column(
                modifier = Modifier.padding(start = 8.dp).align(Alignment.CenterVertically),
            ) {
                Text(
                    text = detail,
                    fontSize = 10.sp,
                    color = if (transport?.fromMap == true) OkGreen else Muted,
                )
                if (transport != null && transport.source == "estimate") {
                    Text("地图不可用，已留出保守余量", fontSize = 9.sp, color = Muted)
                }
                if (transport != null && transport.source != "placeholder" && transport.chosenBy.isNotBlank()) {
                    Text(transport.chosenBy, fontSize = 9.sp, color = Muted)
                }
            }
        }
    }
}

@Composable
fun SchemeCard(
    scheme: RepairScheme,
    plan: Plan,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        border = if (selected) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else null,
        colors = CardDefaults.cardColors(
            containerColor = if (selected) MaterialTheme.colorScheme.primaryContainer.copy(alpha = 0.4f)
            else MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("方案 ${scheme.id}", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Ink)
                Spacer(Modifier.width(8.dp))
                Text(scheme.label, fontSize = 13.sp, color = Muted)
                Spacer(Modifier.weight(1f))
                if (selected) {
                    Icon(Icons.Default.Check, contentDescription = "已选中", tint = MaterialTheme.colorScheme.primary)
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                StatChip("改动 ${scheme.changedCount} 处")
                StatChip("保留 ${(scheme.keepRate * 100).toInt()}%")
            }
            if (scheme.sacrifice.isNotBlank()) {
                Spacer(Modifier.height(8.dp))
                Text("牺牲：${scheme.sacrifice}", fontSize = 12.sp, color = ConflictOrange)
            }
            Spacer(Modifier.height(8.dp))
            scheme.actions.forEach { action ->
                Text(
                    text = "· ${actionSummary(action, plan)}",
                    fontSize = 13.sp,
                    color = Ink,
                    modifier = Modifier.padding(vertical = 1.dp),
                )
            }
        }
    }
}

@Composable
fun StatChip(text: String) {
    Surface(color = Color(0xFFF3F4F6), shape = RoundedCornerShape(50)) {
        Text(text, modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp), fontSize = 11.sp, color = Ink)
    }
}

@Composable
fun ImpactRow(node: PlanNode, state: String, reason: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            modifier = Modifier
                .padding(top = 5.dp)
                .size(9.dp)
                .background(stateColor(state), CircleShape),
        )
        Spacer(Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(node.title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                Spacer(Modifier.width(8.dp))
                StateBadge(state)
            }
            Spacer(Modifier.height(2.dp))
            Text(reason, fontSize = 12.sp, color = Muted)
        }
    }
}

@Composable
fun NotifyRow(row: NotificationRow, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth().clickable { onCheckedChange(!checked) },
        color = Color.White,
        shape = RoundedCornerShape(14.dp),
        tonalElevation = 1.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(checked = checked, onCheckedChange = onCheckedChange)
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(row.title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink)
                    Spacer(Modifier.width(8.dp))
                    LevelBadge(row.level)
                }
                Text(row.text, fontSize = 12.sp, color = Muted, modifier = Modifier.padding(top = 2.dp))
                Text("通知：${row.person}", fontSize = 11.sp, color = Muted, modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}

@Composable
fun LevelBadge(level: String) {
    val color = if (level == "打断") InvalidRed else OkGreen
    Surface(color = color.copy(alpha = 0.12f), shape = RoundedCornerShape(50)) {
        Text(
            text = level,
            modifier = Modifier.padding(horizontal = 7.dp, vertical = 2.dp),
            fontSize = 10.sp,
            color = color,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
fun ActionRow(
    item: TodoRow,
    done: Boolean,
    onToggle: () -> Unit,
    onCall: () -> Unit,
    onCopy: () -> Unit,
) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = Color.White,
        shape = RoundedCornerShape(14.dp),
        tonalElevation = 1.dp,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(checked = done, onCheckedChange = { onToggle() })
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = item.text,
                    fontSize = 14.sp,
                    color = if (done) Muted else Ink,
                    textDecoration = if (done) TextDecoration.LineThrough else TextDecoration.None,
                )
                Row {
                    if (item.phone.isNotBlank()) {
                        TextButton(onClick = onCall) { Text("拨号", fontSize = 12.sp) }
                    }
                    TextButton(onClick = onCopy) { Text("话术", fontSize = 12.sp) }
                }
            }
        }
    }
}

@Composable
fun ImpactSummary(impact: Impact, title: String, onOpen: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        color = RiskAmber.copy(alpha = 0.12f),
        shape = RoundedCornerShape(12.dp),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "$title · 影响 ${impact.affectedCount}/${impact.totalCount} 个节点",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Color(0xFF7A4F01),
                )
                Text(
                    "${Math.round(impact.ratio * 100)}% · ${pathLabel(impact.path)}",
                    fontSize = 11.sp,
                    color = Color(0xFF8A5A00),
                )
            }
            TextButton(onClick = onOpen) { Text("查看影响", fontSize = 12.sp) }
        }
    }
}

/**
 * 交通方式的中文说法。
 *
 * 数据来自高德路径规划（route.py 选择）：步行/骑行更快时用更快的，
 * 用户说过"不想多走路"就一律公交；estimate 表示接口失败退回直线估算。
 */
fun transportLabel(mode: String): String = when (mode) {
    "walking" -> "步行"
    "bicycling" -> "骑行"
    "transit" -> "公交"
    "estimate" -> "约"
    else -> "通行"
}

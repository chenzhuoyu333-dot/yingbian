package com.example.yingbian.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

/** 日历里最重的那种黑，和截图一致。 */
private val SelectedBlack = Color(0xFF111111)

/** 区间中间的深灰条。 */
private val RangeGrey = Color(0xFF4A4A4A)

private const val MAX_TRIP_DAYS = 7

/**
 * 截图里的「你想去多久?」区间日历。
 *
 * 交互：
 * - 第一次点：选出发日；
 * - 再点更晚的一天：结束日，中间连成深灰条；
 * - 再点更早的一天：自动调换起止；
 * - 再点一次已选中的范围：重新开始选。
 *
 * 「灵活天数」打开时只固定出发日，天数交给文字里的描述（后端解析）。
 */
@Composable
fun DateRangeCalendar(
    startIso: String,
    endIso: String?,
    flexible: Boolean,
    todayIso: String,
    onFlexibleChange: (Boolean) -> Unit,
    onSelect: (start: String, end: String?) -> Unit,
    onBack: () -> Unit,
    onConfirm: () -> Unit,
) {
    var anchorYear by remember { mutableStateOf(parseIso(startIso)?.get(Calendar.YEAR) ?: currentYear()) }
    var anchorMonth by remember { mutableStateOf(parseIso(startIso)?.get(Calendar.MONTH) ?: currentMonth()) }
    var notice by remember { mutableStateOf("") }

    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .clickable(onClick = onBack),
                contentAlignment = Alignment.Center,
            ) {
                Text("‹", fontSize = 22.sp, color = Ink)
            }
            Spacer(Modifier.weight(1f))
            FlexibleToggle(checked = flexible) { onFlexibleChange(it) }
        }

        Text(
            text = "你想去多久?",
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold,
            color = Ink,
            modifier = Modifier.padding(top = 4.dp),
        )
        Text(
            text = "时区：Asia/Shanghai",
            fontSize = 10.sp,
            color = Muted,
            modifier = Modifier.padding(top = 6.dp),
        )

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = "${anchorYear} 年 ${anchorMonth + 1} 月",
                fontSize = 18.sp,
                fontWeight = FontWeight.Medium,
                color = Ink,
            )
            Spacer(Modifier.weight(1f))
            MonthArrow("‹", enabled = canGoPrev(anchorYear, anchorMonth)) {
                val prev = shiftMonth(anchorYear, anchorMonth, -1)
                anchorYear = prev.first
                anchorMonth = prev.second
            }
            MonthArrow("›", enabled = canGoNext(anchorYear, anchorMonth)) {
                val next = shiftMonth(anchorYear, anchorMonth, 1)
                anchorYear = next.first
                anchorMonth = next.second
            }
        }

        Row(modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            listOf("日", "一", "二", "三", "四", "五", "六").forEach { label ->
                Text(
                    text = label,
                    fontSize = 10.sp,
                    color = Muted,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.weight(1f),
                )
            }
        }

        MonthGrid(
            anchorYear = anchorYear,
            anchorMonth = anchorMonth,
            startIso = startIso,
            endIso = endIso,
            todayIso = todayIso,
            onPick = { iso ->
                val message = pickDate(iso, startIso, endIso, onSelect)
                if (message.isNotBlank()) notice = message
            },
        )

        Text(
            text = when {
                notice.isNotBlank() -> notice
                endIso != null -> "共 ${daysBetween(startIso, endIso)} 天 · 最晚可选 ${addDaysIso(startIso, MAX_TRIP_DAYS - 1)}"
                flexible -> "只固定出发日，天数按你文字里说的算"
                else -> "再点一天选返程日；只选一天就是当天往返"
            },
            fontSize = 10.sp,
            color = if (notice.isNotBlank()) ConflictOrange else Muted,
            modifier = Modifier.padding(top = 10.dp),
        )

        Button(
            onClick = onConfirm,
            modifier = Modifier.fillMaxWidth().padding(top = 14.dp).height(48.dp),
            shape = RoundedCornerShape(24.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = SelectedBlack,
                contentColor = Color.White,
            ),
        ) {
            Text("确定", fontSize = 15.sp, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(28.dp))
    }
}

@Composable
private fun FlexibleToggle(checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier
            .clip(CircleShape)
            .background(if (checked) SelectedBlack else Color(0xFFEDEDED))
            .clickable { onChange(!checked) }
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(18.dp)
                .clip(CircleShape)
                .background(if (checked) Color.White else Color(0xFFBDBDBD)),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = "灵活天数",
            fontSize = 10.sp,
            color = if (checked) Color.White else Muted,
        )
    }
}

@Composable
private fun MonthArrow(label: String, enabled: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(30.dp)
            .clip(CircleShape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, fontSize = 18.sp, color = if (enabled) Ink else LineGrey)
    }
}

@Composable
private fun MonthGrid(
    anchorYear: Int,
    anchorMonth: Int,
    startIso: String,
    endIso: String?,
    todayIso: String,
    onPick: (String) -> Unit,
) {
    val monthStart = remember(anchorYear, anchorMonth) {
        Calendar.getInstance().apply {
            clear()
            set(anchorYear, anchorMonth, 1)
        }
    }
    val offset = monthStart.get(Calendar.DAY_OF_WEEK) - Calendar.SUNDAY
    val dayCount = monthStart.getActualMaximum(Calendar.DAY_OF_MONTH)
    val rows = (offset + dayCount + 6) / 7
    val formatter = remember { SimpleDateFormat("yyyy-MM-dd", Locale.CHINA) }

    Column(modifier = Modifier.fillMaxWidth().padding(top = 6.dp)) {
        for (row in 0 until rows) {
            Row(modifier = Modifier.fillMaxWidth()) {
                for (col in 0 until 7) {
                    val dayNumber = row * 7 + col - offset + 1
                    if (dayNumber in 1..dayCount) {
                        val iso = remember(anchorYear, anchorMonth, dayNumber) {
                            val cal = Calendar.getInstance().apply {
                                clear()
                                set(anchorYear, anchorMonth, dayNumber)
                            }
                            formatter.format(cal.time)
                        }
                        DayCell(
                            dayNumber = dayNumber,
                            iso = iso,
                            isStart = iso == startIso,
                            isEnd = endIso != null && iso == endIso,
                            inRange = endIso != null && iso > startIso && iso < endIso,
                            enabled = iso >= todayIso,
                            leftRounded = iso == startIso || col == 0,
                            rightRounded = iso == endIso || col == 6,
                            onClick = { onPick(iso) },
                            modifier = Modifier.weight(1f),
                        )
                    } else {
                        Spacer(modifier = Modifier.weight(1f).height(44.dp))
                    }
                }
            }
        }
    }
}

@Composable
private fun DayCell(
    dayNumber: Int,
    iso: String,
    isStart: Boolean,
    isEnd: Boolean,
    inRange: Boolean,
    enabled: Boolean,
    leftRounded: Boolean,
    rightRounded: Boolean,
    onClick: () -> Unit,
    modifier: Modifier,
) {
    val bandVisible = inRange || isStart || isEnd
    Box(
        modifier = modifier.height(44.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (bandVisible) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(36.dp)
                    .clip(
                        RoundedCornerShape(
                            topStart = if (leftRounded) 18.dp else 0.dp,
                            bottomStart = if (leftRounded) 18.dp else 0.dp,
                            topEnd = if (rightRounded) 18.dp else 0.dp,
                            bottomEnd = if (rightRounded) 18.dp else 0.dp,
                        ),
                    )
                    .background(RangeGrey),
            )
        }
        if (isStart || isEnd) {
            Box(modifier = Modifier.size(36.dp).clip(CircleShape).background(SelectedBlack))
        }
        Box(
            modifier = Modifier
                .size(width = 44.dp, height = 44.dp)
                .clip(CircleShape)
                .clickable(enabled = enabled, onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = dayNumber.toString(),
                fontSize = 14.sp,
                fontWeight = if (isStart || isEnd) FontWeight.Bold else FontWeight.Normal,
                color = when {
                    isStart || isEnd || inRange -> Color.White
                    !enabled -> LineGrey
                    else -> Ink
                },
            )
        }
    }
}

/**
 * 点选逻辑，返回需要提示的文字（空字符串表示不提示）。
 */
private fun pickDate(
    iso: String,
    startIso: String,
    endIso: String?,
    onSelect: (String, String?) -> Unit,
): String {
    return when {
        endIso == null -> {
            when {
                iso == startIso -> {
                    onSelect(startIso, null)
                    ""
                }
                iso < startIso -> {
                    onSelect(iso, startIso)
                    ""
                }
                else -> {
                    val latest = addDaysIso(startIso, MAX_TRIP_DAYS - 1)
                    if (iso > latest) {
                        onSelect(startIso, latest)
                        "最多选 $MAX_TRIP_DAYS 天，已自动选到 ${displayMonthDay(latest)}"
                    } else {
                        onSelect(startIso, iso)
                        ""
                    }
                }
            }
        }
        else -> {
            onSelect(iso, null)
            ""
        }
    }
}

private fun parseIso(value: String): Calendar? = runCatching {
    val date = SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).apply { isLenient = false }
        .parse(value.trim())
    date?.let {
        Calendar.getInstance().apply {
            time = it
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
    }
}.getOrNull()

private fun currentYear(): Int = Calendar.getInstance().get(Calendar.YEAR)

private fun currentMonth(): Int = Calendar.getInstance().get(Calendar.MONTH)

private fun monthIndex(year: Int, month: Int): Int = year * 12 + month

private fun canGoPrev(year: Int, month: Int): Boolean {
    val now = Calendar.getInstance()
    return monthIndex(year, month) > monthIndex(now.get(Calendar.YEAR), now.get(Calendar.MONTH))
}

private fun canGoNext(year: Int, month: Int): Boolean {
    val now = Calendar.getInstance()
    return monthIndex(year, month) < monthIndex(now.get(Calendar.YEAR), now.get(Calendar.MONTH)) + 11
}

private fun shiftMonth(year: Int, month: Int, delta: Int): Pair<Int, Int> {
    val total = monthIndex(year, month) + delta
    return total / 12 to total % 12
}

fun addDaysIso(start: String, days: Int): String {
    val cal = parseIso(start) ?: Calendar.getInstance()
    cal.add(Calendar.DAY_OF_MONTH, days)
    return SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).format(cal.time)
}

fun daysBetween(startIso: String, endIso: String): Int {
    val start = parseIso(startIso) ?: return 1
    val end = parseIso(endIso) ?: return 1
    val diff = (end.timeInMillis - start.timeInMillis) / (24L * 60L * 60L * 1000L)
    return diff.toInt() + 1
}

fun displayMonthDay(iso: String): String {
    val cal = parseIso(iso) ?: return iso
    return "${cal.get(Calendar.MONTH) + 1} 月 ${cal.get(Calendar.DAY_OF_MONTH)} 日"
}

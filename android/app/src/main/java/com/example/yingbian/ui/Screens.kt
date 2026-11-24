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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.rememberDateRangePickerState
import com.example.yingbian.data.PatrolAlert
import com.example.yingbian.data.PatrolResult
import com.example.yingbian.data.Province
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.example.yingbian.data.ActivityRow
import com.example.yingbian.data.CheckinResult
import com.example.yingbian.data.Impact
import com.example.yingbian.data.LocateResult
import com.example.yingbian.data.MemberInfo
import com.example.yingbian.data.Plan
import com.example.yingbian.data.parseMinutes
import com.example.yingbian.data.PlanEdge
import com.example.yingbian.data.PlanNode
import com.example.yingbian.data.PlanSummary
import com.example.yingbian.data.RepairScheme
import com.example.yingbian.data.UndoPreview
import com.example.yingbian.data.VoteState
import com.example.yingbian.data.Weather
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

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
    onLocate: () -> Unit = {},
    locateLoading: Boolean = false,
    patrol: PatrolResult? = null,
    patrolDismissed: Boolean = false,
    onOpenPatrol: () -> Unit = {},
    onDismissPatrol: () -> Unit = {},
    memberCount: Int = 0,
    voteOpen: Boolean = false,
    weatherLocation: String = "行程所在地",
    weatherError: String? = null,
    weatherLoading: Boolean = false,
    onUseLocation: () -> Unit = {},
    onRefreshWeather: () -> Unit = {},
    onEditLodging: () -> Unit = {},
    onAdjustStay: (PlanNode) -> Unit = {},
) {

    // 现在是几点（每 30 秒刷新一次，用来画"现在"游标）
    var nowMinutes by remember { mutableStateOf(currentMinuteOfDay()) }
    LaunchedEffect(Unit) {
        while (true) {
            kotlinx.coroutines.delay(30_000)
            nowMinutes = currentMinuteOfDay()
        }
    }
    var weatherOpen by remember { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize()) {
        // 没有天气（还没生成行程 / 这份行程没有坐标）就整块不显示，不占面积
        weather?.let { w ->
            WeatherChip(w, onClick = { weatherOpen = true })
            if (weatherOpen) {
                WeatherDialog(
                    weather = w,
                    location = weatherLocation,
                    loading = weatherLoading,
                    error = weatherError,
                    onUseLocation = onUseLocation,
                    onRefresh = onRefreshWeather,
                    onDismiss = { weatherOpen = false },
                )
            }
        }
        if (offline) OfflineBanner()
        CollabBar(
            memberCount = memberCount,
            voteOpen = voteOpen,
            onVote = onVote,
            onActivity = onActivity,
            onLocate = onLocate,
            locateLoading = locateLoading,
        )
        // 管家提醒：只有真有事才出现，用户可以点"知道了"收起
        patrol?.let { result ->
            if (result.needsAttention && !patrolDismissed) {
                ButlerNotice(
                    result = result,
                    onOpen = onOpenPatrol,
                    onDismiss = onDismissPatrol,
                )
            }
        }

        if (plan.understanding.isNotBlank()) {
            // 让用户一眼看到"AI 把你的话理解成了什么"，
            // 而不是对着一份看不懂的行程发愣
            Text(
                text = "理解：" + plan.understanding,
                fontSize = 10.sp,
                color = Muted,
                modifier = Modifier.padding(horizontal = 18.dp, vertical = 2.dp),
            )
        }
        if (plan.days > 1) {
            val hotel = plan.nodes.firstOrNull { it.overnight }
            Surface(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 3.dp),
                color = SoftBlue,
                shape = RoundedCornerShape(10.dp),
                onClick = onEditLodging,
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = if (hotel?.place.isNullOrBlank()) "住宿：待定" else "住宿：${hotel?.place}",
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = Ink,
                    )
                    Spacer(Modifier.weight(1f))
                    Text("修改 ›", fontSize = 11.sp, color = Muted)
                }
            }
        }
        if (plan.unresolvedMustVisit.isNotEmpty() || plan.generationWarnings.isNotEmpty()) {
            GenerateNotice(plan)
        }
        impact?.let { ImpactSummary(it, eventTitle, onImpact) }
        val dayGroups = plan.nodes.groupBy { it.date.ifBlank { plan.date } }.toList()
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        ) {
            item {
                SectionHeader(
                    title = if (dayGroups.size > 1) "多日行程" else "行程安排",
                    subtitle = "${dayGroups.size} 天 · ${plan.nodes.size} 个节点 · 版本 ${plan.version}",
                )
            }
            dayGroups.forEachIndexed { dayIndex, (date, dayNodes) ->
                item(key = "day-header-$date") {
                    DayHeader(date, dayIndex + 1, dayNodes.size)
                }
                // 只在"今天"那天画游标，插在第一个还没开始的节点之前
                val cursorBeforeId = if (date == todayIso()) {
                    dayNodes.firstOrNull { parseMinutes(it.start) > nowMinutes }?.id
                } else {
                    null
                }
                itemsIndexed(dayNodes, key = { _, node -> node.id }) { index, node ->
                    if (node.id == cursorBeforeId) {
                        NowCursor(nowMinutes)
                    }
                    NodeCard(
                        node = node,
                        state = impact?.stateOf(node.id) ?: "ok",
                        shift = impact?.shiftOf(node.id) ?: 0,
                        phase = when {
                            parseMinutes(node.end) <= nowMinutes -> "past"
                            parseMinutes(node.start) <= nowMinutes -> "now"
                            else -> "future"
                        },
                        onClick = { onAdjustStay(node) },
                    )
                    if (index < dayNodes.lastIndex) {
                        EdgeLine(edgeBetween(plan, node, dayNodes[index + 1]))
                    }
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

private fun edgeBetween(plan: Plan, from: PlanNode, to: PlanNode): PlanEdge? =
    plan.edges.firstOrNull { it.from == from.id && it.to == to.id }

@Composable
private fun DayHeader(date: String, dayIndex: Int, stopCount: Int) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 14.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = formatIsoDate(date),
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
            color = Ink,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text = "第 $dayIndex 天 · $stopCount 站",
            fontSize = 11.sp,
            color = Muted,
        )
    }
}

private fun formatIsoDate(value: String): String {
    if (value.isBlank()) return "日期未定"
    return runCatching {
        val parser = SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).apply { isLenient = false }
        val raw = parser.parse(value) ?: return@runCatching value
        SimpleDateFormat("M 月 d 日 EEEE", Locale.CHINA).format(raw)
    }.getOrDefault(value)
}

@Composable
private fun WeatherChip(weather: Weather, onClick: () -> Unit) {
    // 只占一行：天气 + 降雨概率 + 来源提示。详细信息点进对话框看。
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        color = if (weather.isDemo) Color(0xFFFFF8E1) else SoftBlue,
        shape = RoundedCornerShape(10.dp),
        onClick = onClick,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = weather.text.ifBlank { "天气" },
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = "${(weather.rainProb * 100).toInt()}%",
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                color = if (weather.rainProb >= 0.6) ConflictOrange else OkGreen,
            )
            if (weather.isDemo) {
                Text(
                    text = "  演示数据",
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Color(0xFF8A5A00),
                )
            } else {
                val source = when {
                    weather.source.contains("和风") -> "和风"
                    weather.source.contains("高德") -> "高德"
                    weather.source.isBlank() -> ""
                    else -> "实况"
                }
                if (source.isNotBlank()) {
                    Text(
                        text = "  $source",
                        fontSize = 10.sp,
                        color = Muted,
                    )
                }
            }
            Spacer(Modifier.weight(1f))
            Text(text = "详情 ›", fontSize = 10.sp, color = Muted)
        }
    }
}

/** 天气详情：来源、更新时间、概率依据都放这里，不再占主界面面积 */
@Composable
private fun WeatherDialog(
    weather: Weather,
    location: String,
    loading: Boolean,
    error: String?,
    onUseLocation: () -> Unit,
    onRefresh: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("天气详情") },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = weather.text.ifBlank { "未知" },
                        fontSize = 22.sp,
                        fontWeight = FontWeight.Bold,
                        color = Ink,
                    )
                    Spacer(Modifier.width(12.dp))
                    Text(
                        text = "降雨 ${(weather.rainProb * 100).toInt()}%",
                        fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = if (weather.rainProb >= 0.6) ConflictOrange else OkGreen,
                    )
                }
                if (weather.isDemo) {
                    Text(
                        text = "演示数据 —— 不是真实预报",
                        fontSize = 11.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = Color(0xFF8A5A00),
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))
                DetailLine("来源", weather.source)
                DetailLine("位置", location)
                DetailLine("更新", weather.fetchedAt.replace("T", " "))
                if (weather.basis.isNotBlank()) DetailLine("概率依据", weather.basis)
                if (weather.note.isNotBlank()) DetailLine("说明", weather.note)
                if (!error.isNullOrBlank()) DetailLine("定位错误", error)

                Spacer(Modifier.height(8.dp))
                Row {
                    TextButton(onClick = onRefresh, contentPadding = PaddingValues(0.dp)) {
                        Text(if (loading) "刷新中…" else "刷新行程天气", fontSize = 11.sp)
                    }
                    Spacer(Modifier.width(14.dp))
                    TextButton(onClick = onUseLocation, contentPadding = PaddingValues(0.dp)) {
                        Text(if (loading) "定位中…" else "用我的位置查询", fontSize = 11.sp)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
}

@Composable
private fun DetailLine(label: String, value: String) {
    Row(modifier = Modifier.padding(vertical = 2.dp)) {
        Text("$label：", fontSize = 11.sp, color = Muted)
        Text(value, fontSize = 11.sp, color = Ink)
    }
}

/**
 * 新建行程（整屏）：目的地 → 起止日期 → 一句话偏好。
 *
 * 刻意不给"几天"这个输入：用户脑子里是"11.20 到 11.24"，
 * 不是"4 晚 5 天"。天数由后端从起止日期算，少一个要用户换算的字段。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewPlanScreen(
    regions: List<Province>,
    busy: Boolean,
    error: String?,
    onCreate: (
        city: String,
        startDate: String,
        endDate: String,
        text: String,
        startPlace: String,
        startLat: Double?,
        startLng: Double?,
        lodging: String,
        pace: String,
        maxTransitMin: Int,
    ) -> Unit,
    onLocate: suspend () -> Pair<Double, Double>? = { null },
) {
    var city by remember { mutableStateOf("") }
    var startDate by remember { mutableStateOf("") }
    var endDate by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var startPlace by remember { mutableStateOf("") }
    var lodging by remember { mutableStateOf("") }
    var pace by remember { mutableStateOf("normal") }
    var maxTransitMin by remember { mutableStateOf(60) }
    var startLat by remember { mutableStateOf<Double?>(null) }
    var startLng by remember { mutableStateOf<Double?>(null) }
    var locating by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    var regionOpen by remember { mutableStateOf(false) }
    var dateOpen by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 8.dp),
    ) {
        Text("你想去哪里？", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(10.dp))

        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = Color.White,
            shape = RoundedCornerShape(16.dp),
            shadowElevation = 2.dp,
            onClick = { regionOpen = true },
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                if (city.isBlank()) {
                    Text("选择省份和城市", fontSize = 13.sp, color = Muted)
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(
                            color = Color(0xFFF0EDFF),
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            Text(
                                text = city,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = Ink,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            )
                        }
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text("点这里展开省份 → 城市", fontSize = 10.sp, color = Muted)
            }
        }

        Spacer(Modifier.height(22.dp))
        Text("你想去多久？", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(10.dp))

        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = Color.White,
            shape = RoundedCornerShape(16.dp),
            shadowElevation = 2.dp,
            onClick = { dateOpen = true },
        ) {
            Row(
                modifier = Modifier.padding(16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🗓", fontSize = 16.sp)
                Spacer(Modifier.width(10.dp))
                Text(
                    text = if (startDate.isBlank()) {
                        "选择起止日期"
                    } else if (endDate.isBlank() || endDate == startDate) {
                        // 只选一天：明确标成单日，避免用户以为能生成多日
                        "$startDate · 单日"
                    } else {
                        "$startDate → $endDate · 共 " +
                            (daysBetween(startDate, endDate) + 1) + " 天"
                    },
                    fontSize = 14.sp,
                    color = if (startDate.isBlank()) Muted else Ink,
                    modifier = Modifier.weight(1f),
                )
                Text("›", fontSize = 16.sp, color = Muted)
            }
        }

        Spacer(Modifier.height(22.dp))
        Text("从哪儿出发？", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = startPlace,
            onValueChange = {
                startPlace = it
                startLat = null
                startLng = null
            },
            placeholder = { Text("填一个起点，比如「西湖文化广场」", fontSize = 12.sp) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(
                onClick = {
                    scope.launch {
                        locating = true
                        // onLocate 是 suspend：必须在协程里调
                        val point = try {
                            onLocate()
                        } finally {
                            locating = false
                        }
                        if (point != null) {
                            startLat = point.first
                            startLng = point.second
                            startPlace = "我的位置"
                        }
                    }
                },
                enabled = !locating,
            ) {
                Text(if (locating) "定位中…" else "用当前定位", fontSize = 12.sp)
            }
            Spacer(Modifier.width(10.dp))
            if (startLat != null) {
                Text("已用当前定位", fontSize = 11.sp, color = OkGreen)
            } else if (startPlace.isNotBlank()) {
                Text("从「" + startPlace + "」出发", fontSize = 11.sp, color = Muted)
            } else {
                Text("不填就从市区默认位置开始", fontSize = 11.sp, color = Muted)
            }
        }

        Spacer(Modifier.height(22.dp))
        Text("住在哪里？", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = lodging,
            onValueChange = { lodging = it },
            placeholder = { Text("酒店名或附近地标；不填就按待定排", fontSize = 12.sp) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(4.dp))
        Text("填了住宿，第二天会从酒店出发，晚上回酒店的路也会按地图算。", fontSize = 10.sp, color = Muted)

        Spacer(Modifier.height(22.dp))
        Text("节奏", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                "relaxed" to "轻松",
                "normal" to "正常",
                "packed" to "紧凑",
            ).forEach { (value, label) ->
                val selected = pace == value
                if (selected) {
                    Button(onClick = { pace = value }) { Text(label, fontSize = 12.sp) }
                } else {
                    OutlinedButton(onClick = { pace = value }) { Text(label, fontSize = 12.sp) }
                }
            }
        }
        Text("轻松会缩短每天的点数、建议 18:30 结束；紧凑会多排并建议 21:00 结束。", fontSize = 10.sp, color = Muted)

        Spacer(Modifier.height(22.dp))
        Text("单段路最多坐多久？", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                45 to "45 分钟",
                60 to "60 分钟",
                90 to "90 分钟",
            ).forEach { (value, label) ->
                val selected = maxTransitMin == value
                if (selected) {
                    Button(onClick = { maxTransitMin = value }) { Text(label, fontSize = 12.sp) }
                } else {
                    OutlinedButton(onClick = { maxTransitMin = value }) { Text(label, fontSize = 12.sp) }
                }
            }
        }
        Text("默认 60 分钟；90 只建议当天只去一个远点、或必去点在郊区时用。", fontSize = 10.sp, color = Muted)

        Spacer(Modifier.height(22.dp))
        Text("说说你想怎么玩", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            placeholder = { Text("想拍照、不想多走路，人均 100 以内", fontSize = 12.sp) },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3,
        )
        Text(
            "兴趣最多识别 6 个、避开项最多 8 个；你点名的“必去”不会悄悄丢掉。",
            fontSize = 10.sp,
            color = Muted,
            modifier = Modifier.padding(top = 4.dp),
        )

        if (!error.isNullOrBlank()) {
            Spacer(Modifier.height(10.dp))
            Text("生成失败：$error", fontSize = 12.sp, color = ConflictOrange)
        }

        Spacer(Modifier.height(24.dp))
        Button(
            onClick = { onCreate(city, startDate, endDate.ifBlank { startDate }, text, startPlace, startLat, startLng, lodging, pace, maxTransitMin) },
            enabled = !busy && city.isNotBlank() && startDate.isNotBlank(),
            modifier = Modifier.fillMaxWidth().height(48.dp),
        ) {
            Text(if (busy) "生成中…" else "生成行程", fontSize = 15.sp)
        }
        Spacer(Modifier.height(20.dp))
    }

    if (regionOpen) {
        RegionPickerDialog(
            regions = regions,
            selected = city,
            onPick = { picked ->
                city = picked
                regionOpen = false
            },
            onDismiss = { regionOpen = false },
        )
    }

    if (dateOpen) {
        // 用区间日历（点出发日、点结束日，中间连起来），比系统选择器直观
        Dialog(onDismissRequest = { dateOpen = false }) {
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = Color.White,
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp),
            ) {
                DateRangeCalendar(
                    startIso = startDate,
                    endIso = endDate.ifBlank { null },
                    flexible = false,
                    todayIso = todayIso(),
                    onFlexibleChange = { },
                    onSelect = { start, end ->
                        startDate = start
                        // 第一次点击只记录出发日；第二次点击才写返程日。
                        // 如果这里把 null 直接写成 start，下一次点击会被当成重新选择，
                        // 结果区间永远只有一天。
                        endDate = end.orEmpty()
                    },
                    onBack = { dateOpen = false },
                    onConfirm = { dateOpen = false },
                )
            }
        }
    }
}

/** 省市两级选择：先省，再市；都带搜索框 */
@Composable
fun RegionPickerDialog(
    regions: List<Province>,
    selected: String,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var province by remember { mutableStateOf<String?>(null) }
    var query by remember { mutableStateOf("") }

    val cities = remember(province, regions) {
        regions.firstOrNull { it.name == province }?.cities.orEmpty()
    }
    val shownProvinces = remember(query, regions) {
        if (query.isBlank()) regions else regions.filter { it.name.contains(query) }
    }
    val shownCities = remember(query, cities) {
        if (query.isBlank()) cities else cities.filter { it.contains(query) }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (province == null) "选择省份" else province!!) },
        text = {
            Column {
                if (regions.isEmpty()) {
                    Text("省市清单没取到，请检查网络或后端", fontSize = 12.sp, color = ConflictOrange)
                } else {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        placeholder = { Text(if (province == null) "搜索省份" else "搜索城市", fontSize = 12.sp) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(8.dp))
                    LazyColumn(modifier = Modifier.height(320.dp)) {
                        if (province == null) {
                            items(shownProvinces, key = { it.name }) { item ->
                                TextButton(
                                    onClick = {
                                        province = item.name
                                        query = ""
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text(
                                        text = item.name + "  (" + item.cities.size + ")",
                                        fontSize = 13.sp,
                                        color = Ink,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        } else {
                            items(shownCities, key = { it }) { name ->
                                TextButton(
                                    onClick = { onPick(name) },
                                    modifier = Modifier.fillMaxWidth(),
                                ) {
                                    Text(
                                        text = if (name == selected) "✓ " + name else name,
                                        fontSize = 13.sp,
                                        color = if (name == selected) OkGreen else Ink,
                                        modifier = Modifier.fillMaxWidth(),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            if (province != null) {
                TextButton(onClick = { province = null; query = "" }) { Text("返回省份") }
            } else {
                TextButton(onClick = onDismiss) { Text("关闭") }
            }
        },
    )
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
    onLocate: () -> Unit = {},
    locateLoading: Boolean = false,
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
            TextButton(onClick = onLocate, enabled = !locateLoading) {
                Text(if (locateLoading) "定位中…" else "定位", fontSize = 11.sp)
            }
            TextButton(onClick = onActivity) { Text("记录", fontSize = 11.sp) }
            // 一个人出行时没有“投票”对象，按钮直接不出现，避免点了没反应。
            if (memberCount > 1) {
                TextButton(onClick = onVote) {
                    Text(if (voteOpen) "投票中…" else "投票", fontSize = 11.sp)
                }
            }
        }
    }
}

/**
 * 定位检查结果：先回答"你在哪、该在哪、落后多少"，再给改法。
 */
@Composable
fun LocateDialog(
    result: LocateResult,
    onUseScheme: (RepairScheme) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (result.isBehind) "你落后了" else "定位检查") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                Text(result.message, fontSize = 12.sp, color = Ink)
                if (result.driftMinutes > 0) {
                    Text(
                        text = "落后 " + result.driftMinutes + " 分钟",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = ConflictOrange,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
                if (result.schemes.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    Text("可以这样改：", fontSize = 11.sp, color = Muted)
                    result.schemes.forEach { scheme ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = scheme.label,
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = Ink,
                                )
                                Text(
                                    text = "改 " + scheme.changedCount + " 处",
                                    fontSize = 10.sp,
                                    color = Muted,
                                )
                            }
                            TextButton(onClick = { onUseScheme(scheme) }) {
                                Text("采用", fontSize = 11.sp)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("关闭") } },
    )
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
                    enabled = !loading,
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
            }
            if (loading) {
                Text(
                    text = "正在重算…",
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    fontSize = 11.sp,
                    color = Muted,
                    textAlign = TextAlign.Center,
                )
            } else if (impact == null) {
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = onRain,
                    enabled = !offline,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (offline) "离线，无法重算" else "报告变化：15:00 起下雨")
                }
            } else {
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
                if (offline) {
                    Text(
                        text = "离线：只能查看缓存，不能重算或打卡",
                        modifier = Modifier.padding(top = 6.dp),
                        fontSize = 11.sp,
                        color = Muted,
                    )
                }
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
    initialNodeId: String?,
    onCheckin: (nodeId: String, minutes: Int, personId: String?) -> Unit,
    onSelectScheme: (String) -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var nodeId by remember(plan.planId, initialNodeId) {
        val target = plan.nodes.firstOrNull { it.id == initialNodeId }?.id
        mutableStateOf(
            target
                ?: plan.nodes.firstOrNull { !it.confirmed }?.id
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
            text = "按“保时间 / 保体验”生成两套，选一套采用",
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

/** 方案弹窗：只在“需要改行程”时从底部弹出，不再占一个底部 tab */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SchemeSheet(
    plan: Plan,
    schemes: List<RepairScheme>,
    selectedId: String?,
    loading: Boolean,
    onSelect: (String) -> Unit,
    onApply: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            Text("怎么改？", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = Ink)
            Text(
                text = "按“保时间 / 保体验”给出两套，选一套就应用；不改可以关掉。",
                fontSize = 11.sp,
                color = Muted,
                modifier = Modifier.padding(top = 3.dp, bottom = 10.dp),
            )
            if (schemes.isEmpty()) {
                Text("暂时没有可用方案。", fontSize = 12.sp, color = Muted)
            } else {
                LazyColumn(
                    modifier = Modifier.height(360.dp),
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
                }
            }
            Button(
                onClick = onApply,
                enabled = selectedId != null && !loading,
                modifier = Modifier.fillMaxWidth().padding(vertical = 14.dp),
            ) {
                Text(if (loading) "应用中…" else "采用选中的方案")
            }
        }
    }
}

@Composable
fun NotifyScreen(
    notifications: List<NotificationRow>,
    onCall: (NotificationRow) -> Unit,
    onCopy: (NotificationRow) -> Unit,
    onBack: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "一个变化只产生一条行动项；App 内成员自动收到，只有需要打电话确认的才需要你点一下。",
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            fontSize = 12.sp,
            color = Muted,
        )
        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(notifications, key = { it.id }) { row ->
                ReminderRow(row = row, onCall = { onCall(row) }, onCopy = { onCopy(row) })
            }
            if (notifications.isEmpty()) {
                item { EmptyHint("还没有需要提醒的变化。行程改动后，这里会自动出现一条。") }
            }
            item { Spacer(Modifier.height(6.dp)) }
        }
        Surface(color = Color.White, shadowElevation = 10.dp) {
            OutlinedButton(onClick = onBack, modifier = Modifier.fillMaxWidth().padding(16.dp)) {
                Text("回到行程")
            }
        }
    }
}

@Composable
private fun ReminderRow(
    row: NotificationRow,
    onCall: () -> Unit,
    onCopy: () -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp)) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                LevelBadge(row.level)
                Spacer(Modifier.width(8.dp))
                Text(row.title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Ink)
            }
            Spacer(Modifier.height(6.dp))
            Text(row.text, fontSize = 12.sp, color = Ink)
            Spacer(Modifier.height(4.dp))
            Text(
                text = when (row.kind) {
                    "auto" -> "已自动通知 App 内成员，不需要你再操作"
                    "assist" -> "需要你联系：${row.person}"
                    else -> "只读知会，无需操作"
                },
                fontSize = 10.sp,
                color = Muted,
            )
            if (row.kind == "assist") {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (row.phone.isNotBlank()) {
                        Button(onClick = onCall) { Text("打电话", fontSize = 12.sp) }
                    }
                    OutlinedButton(onClick = onCopy) { Text("复制话术", fontSize = 12.sp) }
                }
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

/** 行程页没有“当前行程”时的空态：不再默认塞一份内置演示 */
@Composable
fun NoActivePlanScreen(onCreate: () -> Unit, onOpenHome: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("还没有正在执行的行程", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Text(
            "先新建一份，生成后会直接出现在这里；天气和定位也只会对真实行程生效。",
            fontSize = 13.sp,
            color = Muted,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp, bottom = 18.dp),
        )
        Button(onClick = onCreate, modifier = Modifier.fillMaxWidth()) {
            Text("新建行程", fontSize = 14.sp)
        }
        TextButton(onClick = onOpenHome) { Text("去计划页看看", fontSize = 12.sp, color = Muted) }
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
fun ErrorScreen(
    message: String,
    onRetry: () -> Unit,
    onCache: () -> Unit,
    onFind: () -> Unit = {},
    finding: Boolean = false,
    findHint: String = "",
) {
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
            modifier = Modifier.padding(top = 8.dp, bottom = 6.dp),
        )
        if (findHint.isNotBlank()) {
            Text(
                text = findHint,
                fontSize = 11.sp,
                color = Muted,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(bottom = 10.dp),
            )
        } else {
            Spacer(Modifier.height(12.dp))
        }
        // 连不上时最常见两种原因：地址变了、或不在同一网络。
        // 直接给一个"自己找"，比让用户去设置里摸索有用得多。
        Button(
            onClick = onFind,
            enabled = !finding,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (finding) "正在寻找服务器…" else "自动寻找服务器")
        }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("重试") }
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
    "at_risk" -> if (!node.indoor) "受降雨影响（降雨概率 70%）" else "受上游变化影响"
    "invalid" -> node.windowLatest?.let { "最晚 $it 开始，当前时间装不下" } ?: "已取消或临时关闭"
    "conflict" -> "你锁定了这个节点，需要你确认"
    else -> "正常"
}

@Composable
fun UndoDialog(
    preview: UndoPreview?,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (preview?.canUndo == true) "撤销到上一版？" else "没有可撤销的改动") },
        text = {
            Column {
                Text(preview?.summary ?: "正在读取…", fontSize = 13.sp, color = Ink)
                if (!preview?.changes.isNullOrEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    preview?.changes?.forEach { change ->
                        Text(
                            text = "· ${change.title}：${change.text}",
                            fontSize = 11.sp,
                            color = Muted,
                            modifier = Modifier.padding(vertical = 2.dp),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                enabled = preview?.canUndo == true,
            ) { Text("确认撤销") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("先不撤") } },
    )
}

@Composable
fun AutoLocateDialog(
    result: LocateResult,
    onCheckin: () -> Unit,
    onFix: () -> Unit,
    onDismiss: () -> Unit,
) {
    val arrived = result.arrived
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(if (arrived) "到了「${result.atNodeTitle}」" else "你可能落后了")
        },
        text = {
            Column {
                Text(
                    if (arrived) {
                        "定位显示你在目标点 ${result.atDistanceM} 米内。要现在打卡吗？"
                    } else {
                        "计划已经在推进，但定位还停在「${result.atNodeTitle}」，落后约 ${result.driftMinutes} 分钟。"
                    },
                    fontSize = 13.sp,
                    color = Ink,
                )
                if (result.message.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text(result.message, fontSize = 11.sp, color = Muted)
                }
            }
        },
        confirmButton = {
            if (arrived) {
                Button(onClick = onCheckin) { Text("打卡") }
            } else {
                Button(onClick = onFix) { Text("看看怎么改") }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("先不管") } },
    )
}

@Composable
fun LodgingDialog(
    initial: String,
    busy: Boolean,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(if (initial.isBlank()) "住在哪里？" else "修改住宿") },
        text = {
            Column {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    placeholder = { Text("酒店名或附近地标", fontSize = 12.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))
                Text("只会改酒店节点和晚上那段通勤，白天行程不动。", fontSize = 11.sp, color = Muted)
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(name.trim()) }, enabled = !busy && name.isNotBlank()) {
                Text(if (busy) "保存中…" else "保存")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
fun StayDialog(
    node: PlanNode,
    busy: Boolean,
    onSave: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    var minutes by remember { mutableStateOf(node.durationMin.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("调整「${node.title}」停留") },
        text = {
            Column {
                Text("当前 ${node.durationMin} 分钟。改完同一天后面的站点会一起顺延。", fontSize = 12.sp, color = Muted)
                Spacer(Modifier.height(8.dp))
                Row {
                    listOf(30, 45, 60, 90, 120).forEach { preset ->
                        TextButton(onClick = { minutes = preset.toString() }) {
                            Text("$preset", fontSize = 12.sp)
                        }
                    }
                }
                OutlinedTextField(
                    value = minutes,
                    onValueChange = { minutes = it.filter(Char::isDigit).take(3) },
                    label = { Text("分钟", fontSize = 11.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { minutes.toIntOrNull()?.let(onSave) },
                enabled = !busy && (minutes.toIntOrNull() ?: 0) >= 15,
            ) { Text(if (busy) "保存中…" else "保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
fun WeatherChangeDialog(
    alert: PatrolAlert,
    onFix: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(alert.title.ifBlank { "天气会影响行程" }) },
        text = {
            Column {
                Text(alert.detail.ifBlank { "检测到降雨会覆盖一个户外地点。" }, fontSize = 13.sp, color = Ink)
                if (alert.action.isNotBlank()) {
                    Spacer(Modifier.height(6.dp))
                    Text("建议：${alert.action}", fontSize = 11.sp, color = Muted)
                }
            }
        },
        confirmButton = { Button(onClick = onFix) { Text("现在改行程") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("先按原计划") } },
    )
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
    val label = mapOf("A" to "保时间", "B" to "保体验")
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

/** 行程记录：本地操作 + 协作事件合并成一条时间线，单人也能看懂发生过什么 */
@Composable
fun ActivityDialog(
    rows: List<ActivityRow>,
    members: List<MemberInfo>,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("行程记录") },
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
                    Text("还没有记录；生成或改一次行程就会出现在这里", fontSize = 12.sp, color = Muted)
                }
                rows.takeLast(20).forEach { row ->
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

/**
 * 我的：只放“关于我”的东西——昵称、身份、服务器、调试入口。
 * 历史行程不在这里重复，统一放首页的“计划”。
 */
@Composable
fun ProfileScreen(
    memberName: String,
    memberId: String,
    baseUrl: String,
    useMock: Boolean,
    memberCount: Int,
    planTitle: String,
    onRename: (String) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenDebug: () -> Unit,
) {
    var name by remember { mutableStateOf(memberName) }
    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Surface(color = Color(0xFFF0EDFF), shape = RoundedCornerShape(28.dp)) {
                Box(modifier = Modifier.size(56.dp), contentAlignment = Alignment.Center) {
                    Text(
                        text = memberName.take(1).ifBlank { "我" },
                        fontSize = 22.sp,
                        fontWeight = FontWeight.Bold,
                        color = Ink,
                    )
                }
            }
            Spacer(Modifier.width(14.dp))
            Column {
                Text(memberName, fontSize = 19.sp, fontWeight = FontWeight.Bold, color = Ink)
                Text("身份 $memberId · 同行 $memberCount 人", fontSize = 11.sp, color = Muted)
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("我的昵称", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(6.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = { if (name.isNotBlank()) onRename(name.trim()) },
                enabled = name.isNotBlank() && name != memberName,
            ) { Text("保存") }
        }
        Text("昵称会出现在同行成员的投票和操作记录里。", fontSize = 10.sp, color = Muted)

        Spacer(Modifier.height(24.dp))
        Text("连接", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(6.dp))
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = Color.White,
            shape = RoundedCornerShape(14.dp),
            shadowElevation = 1.dp,
            onClick = onOpenSettings,
        ) {
            Column(modifier = Modifier.padding(14.dp)) {
                Text(
                    text = if (useMock) "离线演示（不连服务器）" else baseUrl,
                    fontSize = 12.sp,
                    color = Ink,
                )
                Spacer(Modifier.height(3.dp))
                Text("点这里改服务器地址或重新自动寻找", fontSize = 10.sp, color = Muted)
            }
        }

        Spacer(Modifier.height(24.dp))
        Text("当前行程", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Ink)
        Spacer(Modifier.height(6.dp))
        Text(planTitle.ifBlank { "还没有打开的行程" }, fontSize = 12.sp, color = Muted)

        Spacer(Modifier.height(24.dp))
        OutlinedButton(onClick = onOpenDebug, modifier = Modifier.fillMaxWidth()) {
            Text("调试 / 演示状态", fontSize = 12.sp)
        }
        Spacer(Modifier.height(20.dp))
        Text("应变 · 行程变化助手", fontSize = 10.sp, color = Muted)
    }
}

/**
 * 首页：我的计划。
 *
 * 这一屏把"一次性行程"变成"行程库"：
 *   · 中间是历史行程，最近改过的排最前
 *   · 右上角新建 → 一句话交给 AI，生成完直接进这份行程
 */
@Composable
fun HomeScreen(
    plans: List<PlanSummary>,
    loading: Boolean,
    onOpen: (String) -> Unit,
    onCreate: () -> Unit,
    onDelete: (String) -> Unit,
) {
    val mine = plans.filterNot { it.builtin }
    val examples = plans.filter { it.builtin }
    Column(modifier = Modifier.fillMaxSize()) {
        // 顶部已经有标题和加号了，这里不再重复一行"我的计划 + 新建"

        LazyColumn(
            modifier = Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (mine.isEmpty() && !loading) {
                item {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 40.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text("还没有你自己的行程", fontSize = 14.sp, color = Muted)
                        Spacer(Modifier.height(6.dp))
                        Text("点右上角＋，说一句你想怎么玩", fontSize = 12.sp, color = Muted)
                    }
                }
            }
            if (mine.isNotEmpty()) {
                item { SectionHeader("我的行程", "只放你生成/打开过的，不和示范混在一起") }
            }
            items(mine, key = { it.planId }) { item ->
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = Color.White,
                    shape = RoundedCornerShape(16.dp),
                    shadowElevation = 2.dp,
                    onClick = { onOpen(item.planId) },
                ) {
                    Row(modifier = Modifier.padding(14.dp)) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = item.title,
                                fontSize = 16.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = Ink,
                            )
                            Text(
                                text = buildString {
                                    append(item.date)
                                    append(" · ")
                                    append("${item.nodeCount} 个地点")
                                    if (item.confirmedCount > 0) append(" · ${item.confirmedCount} 个锁定")
                                },
                                fontSize = 11.sp,
                                color = Muted,
                                modifier = Modifier.padding(top = 3.dp),
                            )
                            Text(
                                text = if (item.builtin) {
                                    "内置示范"
                                } else {
                                    "更新于 ${item.updatedAt.ifBlank { "刚刚" }} · v${item.version}"
                                },
                                fontSize = 10.sp,
                                color = Muted,
                                modifier = Modifier.padding(top = 6.dp),
                            )
                        }
                        if (!item.builtin) {
                            TextButton(onClick = { onDelete(item.planId) }) {
                                Text("删除", fontSize = 11.sp, color = ConflictOrange)
                            }
                        }
                    }
                }
            }
            if (examples.isNotEmpty()) {
                item {
                    SectionHeader("示例行程（演示用）", "内置数据，用来讲“零缓冲会全崩”；不参与你的历史")
                }
                items(examples, key = { it.planId }) { item ->
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        color = Color(0xFFF7F7F8),
                        shape = RoundedCornerShape(14.dp),
                        onClick = { onOpen(item.planId) },
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Text(item.title, fontSize = 13.sp, color = Ink, fontWeight = FontWeight.SemiBold)
                            Text("内置示范 · ${item.date}", fontSize = 10.sp, color = Muted)
                        }
                    }
                }
            }
        }
    }
}

/**
 * 新建行程：一句话交给 AI。
 *
 * 这里刻意不做表单 —— 表单是"问用户要参数"，对话框是"听用户说需求"。
 * 解析成什么条件由后端 ai.py 决定，界面只负责把话送出去。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewPlanDialog(
    busy: Boolean,
    error: String?,
    onGenerate: (String, String, Int?, String, Boolean) -> Unit,
    onDismiss: () -> Unit,
) {
    // 0 = 说需求，1 = 选日期。两页共用一个底部弹层，避免弹窗叠弹窗。
    var page by remember { mutableStateOf(0) }
    var text by remember { mutableStateOf("") }
    var startDate by remember { mutableStateOf(todayIso()) }
    var endDate by remember { mutableStateOf<String?>(null) }
    var lodging by remember { mutableStateOf("") }
    var avoidWalking by remember { mutableStateOf(false) }
    // 灵活天数 = 只固定出发日，天数交给文字里的描述
    var flexible by remember { mutableStateOf(true) }
    val today = remember { todayIso() }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val samples = listOf(
        "想拍照、不想早起，别爬山，轻松一点",
        "下午两点半出发，想看博物馆和咖啡店，人均 40 以内",
        "一整天都在外面，尽量多去几个地方",
    )

    val tripEnd = endDate
    val tripDays = tripEnd?.let { daysBetween(startDate, it) }
    val dateLabel = when {
        tripEnd != null -> "${displayMonthDay(startDate)} → ${displayMonthDay(tripEnd)}"
        flexible -> "${displayMonthDay(startDate)} 出发"
        else -> "${displayMonthDay(startDate)} 当天往返"
    }
    val dateHint = when {
        tripEnd != null -> "共 $tripDays 天"
        flexible -> "天数按文字里说的算"
        else -> "共 1 天"
    }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        if (page == 1) {
            DateRangeCalendar(
                startIso = startDate,
                endIso = endDate,
                flexible = flexible,
                todayIso = today,
                onFlexibleChange = { on ->
                    flexible = on
                    if (on) endDate = null
                },
                onSelect = { newStart, newEnd ->
                    startDate = newStart
                    endDate = newEnd
                    if (newEnd != null) flexible = false
                },
                onBack = { page = 0 },
                onConfirm = { page = 0 },
            )
        } else {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .imePadding()
                    .padding(horizontal = 20.dp)
                    .padding(bottom = 28.dp),
            ) {
                Text("说说你想怎么玩", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Ink)
                Text(
                    text = "AI 会把这句话解析成条件，再从高德检索真实地点排成行程。地点不是模型编的。",
                    fontSize = 11.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 4.dp),
                )
                Spacer(Modifier.height(14.dp))

                Surface(
                    onClick = { page = 1 },
                    color = SoftBlue,
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("日期", fontSize = 10.sp, color = Muted)
                            Text(
                                text = dateLabel,
                                fontSize = 15.sp,
                                fontWeight = FontWeight.Bold,
                                color = Ink,
                                modifier = Modifier.padding(top = 3.dp),
                            )
                            Text(
                                text = dateHint,
                                fontSize = 10.sp,
                                color = Muted,
                                modifier = Modifier.padding(top = 3.dp),
                            )
                        }
                        Text("选择 ›", fontSize = 11.sp, color = Muted)
                    }
                }

                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = lodging,
                    onValueChange = { lodging = it },
                    label = { Text("住哪儿（可选）", fontSize = 12.sp) },
                    placeholder = { Text("酒店名或区域，如 龙翔桥 / 西湖边", fontSize = 11.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    text = "填了住宿：每天从酒店出发、晚上回酒店，酒店通勤计入行程。",
                    fontSize = 10.sp,
                    color = Muted,
                    modifier = Modifier.padding(top = 4.dp, start = 2.dp),
                )

                Spacer(Modifier.height(10.dp))
                Surface(
                    onClick = { avoidWalking = !avoidWalking },
                    color = if (avoidWalking) Ink else SoftBlue,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = if (avoidWalking) "少走路：已开启" else "少走路",
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = if (avoidWalking) Color.White else Ink,
                            )
                            Text(
                                text = "不安排长距离步行，公交优先选步行最少的方案",
                                fontSize = 9.sp,
                                color = if (avoidWalking) Color.White.copy(alpha = 0.8f) else Muted,
                                modifier = Modifier.padding(top = 2.dp),
                            )
                        }
                        Text(
                            text = if (avoidWalking) "✓" else "开启",
                            fontSize = 11.sp,
                            color = if (avoidWalking) Color.White else Muted,
                        )
                    }
                }

                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    placeholder = { Text("例如：想拍照、不想早起，别爬山", fontSize = 12.sp) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                )
                Spacer(Modifier.height(8.dp))
                Text("试试这些：", fontSize = 11.sp, color = Muted)
                samples.forEach { sample ->
                    TextButton(
                        onClick = { text = sample },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(sample, fontSize = 11.sp, color = Ink, textAlign = TextAlign.Start)
                    }
                }
                if (!error.isNullOrBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text("生成失败：$error", fontSize = 12.sp, color = ConflictOrange)
                }
                Spacer(Modifier.height(6.dp))
                Button(
                    onClick = {
                        val pickedEnd = endDate
                        val days = when {
                            pickedEnd != null -> daysBetween(startDate, pickedEnd)
                            flexible -> null
                            else -> 1
                        }
                        onGenerate(text.trim(), startDate, days, lodging.trim(), avoidWalking)
                    },
                    enabled = !busy && text.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().height(46.dp),
                    shape = RoundedCornerShape(23.dp),
                ) {
                    Text(if (busy) "生成中…" else "生成行程")
                }
                TextButton(
                    onClick = onDismiss,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("取消", fontSize = 12.sp, color = Muted)
                }
            }
        }
    }
}

fun currentMinuteOfDay(): Int {
    val c = java.util.Calendar.getInstance()
    return c.get(java.util.Calendar.HOUR_OF_DAY) * 60 + c.get(java.util.Calendar.MINUTE)
}

fun todayIso(): String =
    SimpleDateFormat("yyyy-MM-dd", Locale.CHINA).format(Date())

@Composable
private fun DebugAction(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Text(label, fontSize = 13.sp, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Start)
    }
}

/**
 * 管家提醒：产品最核心的一屏。
 *
 * 别人做的是"你发现不对 → 你去改"，
 * 这里做的是"它先发现 → 它告诉你 → 一键改"。
 * 只有真有事才出现，可以"知道了"收起。
 */
@Composable
fun ButlerNotice(
    result: PatrolResult,
    onOpen: () -> Unit,
    onDismiss: () -> Unit,
) {
    val urgent = result.severity == "urgent"
    Surface(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
        color = if (urgent) Color(0xFFFFF1E6) else Color(0xFFEFF6FF),
        shape = RoundedCornerShape(14.dp),
        onClick = onOpen,
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (urgent) "管家提醒" else "提醒",
                    fontSize = 10.sp,
                    color = if (urgent) ConflictOrange else Muted,
                )
                Text(
                    text = result.summary,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    color = Ink,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            TextButton(onClick = onDismiss) { Text("知道了", fontSize = 11.sp) }
        }
    }
}

/** 提醒详情：每条都能直接去处理 */
@Composable
fun PatrolDialog(
    result: PatrolResult,
    onHandle: (PatrolAlert) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("管家发现") },
        text = {
            Column(modifier = Modifier.verticalScroll(rememberScrollState())) {
                result.alerts.forEach { alert ->
                    Column(modifier = Modifier.padding(vertical = 6.dp)) {
                        Text(
                            text = alert.title,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = if (alert.severity == "urgent") ConflictOrange else Ink,
                        )
                        Text(alert.detail, fontSize = 11.sp, color = Muted)
                        if (alert.action.isNotBlank()) {
                            TextButton(
                                onClick = { onHandle(alert) },
                                contentPadding = PaddingValues(0.dp),
                            ) {
                                Text(alert.action + " >", fontSize = 11.sp)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("先不管") } },
    )
}

/**
 * 今天没有行程时的首页。
 *
 * 不做成空白页：上面是所在地天气（按定位查），下面一句话告诉用户
 * "今天空着"以及"可以现在安排"。
 */
@Composable
fun NoPlanTodayScreen(
    weather: Weather?,
    weatherLoading: Boolean,
    weatherError: String?,
    today: String,
    onNewPlan: () -> Unit,
    onRefreshWeather: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(40.dp))

        // 所在地天气（只有定位成功才有）
        when {
            weather != null -> {
                Text(
                    text = weather.place.ifBlank { "你所在的地方" },
                    fontSize = 13.sp,
                    color = Muted,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    text = weather.text.ifBlank { "天气" },
                    fontSize = 34.sp,
                    fontWeight = FontWeight.Bold,
                    color = Ink,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = buildString {
                        if (weather.rainProb > 0) {
                            append("降雨 ")
                            append((weather.rainProb * 100).toInt())
                            append("%")
                        } else {
                            append("今天不太会下雨")
                        }
                    },
                    fontSize = 14.sp,
                    color = Muted,
                )
                if (weather.isDemo) {
                    Spacer(Modifier.height(4.dp))
                    Text("演示数据", fontSize = 10.sp, color = Muted)
                }
            }
            weatherLoading -> {
                CircularProgressIndicator(modifier = Modifier.size(28.dp))
                Spacer(Modifier.height(10.dp))
                Text("正在取你所在地的天气…", fontSize = 12.sp, color = Muted)
            }
            else -> {
                Text("取不到天气", fontSize = 13.sp, color = Muted)
                if (!weatherError.isNullOrBlank()) {
                    Text(weatherError, fontSize = 11.sp, color = Muted)
                }
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = onRefreshWeather) { Text("用我的位置再试", fontSize = 12.sp) }
            }
        }

        Spacer(Modifier.height(34.dp))

        Text("今天没有安排", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Ink)
        Spacer(Modifier.height(8.dp))
        Text(
            text = "想出去的话，说一句你想怎么玩，我来排。",
            fontSize = 13.sp,
            color = Muted,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(4.dp))
        Text(today, fontSize = 11.sp, color = Muted)

        Spacer(Modifier.height(26.dp))
        Button(onClick = onNewPlan, modifier = Modifier.fillMaxWidth().height(48.dp)) {
            Text("安排一件事", fontSize = 15.sp)
        }
        Spacer(Modifier.height(10.dp))
        Text(
            text = "也可以点右上角设置，看看历史行程",
            fontSize = 11.sp,
            color = Muted,
        )
        Spacer(Modifier.height(40.dp))
    }
}

package com.example.yingbian.data

import org.json.JSONArray
import org.json.JSONObject

data class Alternative(
    val id: String,
    val title: String,
    val indoor: Boolean,
    val start: String,
    val end: String,
    val travelMin: Int,
    val place: String,
    val sacrifice: String,
    val contact: String,
)

data class PlanNode(
    val id: String,
    val type: String,
    val title: String,
    val start: String,
    val end: String,
    val indoor: Boolean,
    val confirmed: Boolean,
    val windowLatest: String?,
    val alternatives: List<Alternative>,
    val place: String,
    val contact: String,
    val persons: List<String>,
    val sacrifice: String,
) {
    val durationMin: Int
        get() = (parseMinutes(end) - parseMinutes(start)).coerceAtLeast(0)

    fun startWithShift(shift: Int): String = formatMinutes(parseMinutes(start) + shift)

    fun endWithShift(shift: Int): String = formatMinutes(parseMinutes(end) + shift)
}

data class PlanEdge(
    val from: String,
    val to: String,
    val minGapMin: Int,
)

data class Plan(
    val planId: String,
    val title: String,
    val date: String,
    val version: Int,
    val nodes: List<PlanNode>,
    val edges: List<PlanEdge>,
    /** 生成器给出的提示（必去点没排进去、自检发现问题等）；内置计划为空 */
    val generationWarnings: List<String> = emptyList(),
    /** 用户点名但没排进去的必去点，界面上要标「待确认」 */
    val unresolvedMustVisit: List<String> = emptyList(),
) {
    fun node(id: String): PlanNode? = nodes.firstOrNull { it.id == id }
}

data class Impact(
    val states: Map<String, String>,
    val shifts: Map<String, Int>,
    val ratio: Double,
    val path: String,
    val affectedCount: Int,
    val totalCount: Int,
) {
    fun stateOf(nodeId: String): String = states[nodeId] ?: "ok"

    fun shiftOf(nodeId: String): Int = shifts[nodeId] ?: 0
}

data class RepairAction(
    val nodeId: String,
    val action: String,
    val payload: Map<String, String>,
    val reason: String,
    val sacrifice: String,
)

data class RepairScheme(
    val id: String,
    val label: String,
    val keepRate: Double,
    val changedCount: Int,
    val actions: List<RepairAction>,
    val sacrifice: String,
)

data class RepairResult(
    val status: String,
    val schemes: List<RepairScheme>,
    val blockedNode: String?,
    val message: String,
)

/**
 * 生成行程的偏好。字段名与后端 /api/generate 的请求体一一对应。
 * 全部有默认值，界面上只需要改用户关心的几项。
 */
data class GeneratePrefs(
    val city: String = "杭州",
    val date: String = "2026-11-14",
    val startTime: String = "09:30",
    val endTime: String = "20:00",
    val interests: List<String> = listOf("景点", "公园", "咖啡"),
    val mustVisit: List<String> = emptyList(),
    val avoid: List<String> = emptyList(),
    val pace: String = "normal",
    val maxTransitMin: Int = 45,
)

data class Weather(
    val source: String,
    val fetchedAt: String,
    val rainProb: Double,
    val text: String,
    /** 后端明确标注的"这是演示数据"，界面必须显示出来 */
    val isDemo: Boolean = false,
    /** 降雨概率是怎么来的（和风 pop / 高德文字估计），用于解释而非装饰 */
    val basis: String = "",
    /** isDemo 为真时，后端给的原因说明 */
    val note: String = "",
)

fun parseMinutes(value: String): Int {
    val parts = value.trim().split(":")
    if (parts.size != 2) return 0
    return (parts[0].toIntOrNull() ?: 0) * 60 + (parts[1].toIntOrNull() ?: 0)
}

fun formatMinutes(total: Int): String {
    val minutes = ((total % 1440) + 1440) % 1440
    return "%02d:%02d".format(minutes / 60, minutes % 60)
}

fun applyActions(plan: Plan, actions: List<RepairAction>): Plan {
    var nodes = plan.nodes
    for (action in actions) {
        nodes = when (action.action) {
            "shift" -> {
                val minutes = action.payload["minutes"]?.toIntOrNull() ?: 0
                nodes.map { node ->
                    if (node.id != action.nodeId) node
                    else node.copy(
                        start = node.startWithShift(minutes),
                        end = node.endWithShift(minutes),
                    )
                }
            }

            "replace" -> {
                val alternativeId = action.payload["alternativeId"]
                nodes.map { node ->
                    if (node.id != action.nodeId) node
                    else {
                        val alternative = node.alternatives.firstOrNull { it.id == alternativeId }
                        if (alternative == null) node
                        else node.copy(
                            title = alternative.title,
                            indoor = alternative.indoor,
                            start = alternative.start,
                            end = alternative.end,
                            place = alternative.place,
                            contact = alternative.contact.ifBlank { node.contact },
                            sacrifice = alternative.sacrifice,
                        )
                    }
                }
            }

            "drop" -> nodes.filterNot { it.id == action.nodeId }
            else -> nodes
        }
    }
    val ids = nodes.map { it.id }.toSet()
    return plan.copy(
        version = plan.version + 1,
        nodes = nodes,
        edges = plan.edges.filter { it.from in ids && it.to in ids },
    )
}

object PlanJson {
    private fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key, "")

    private fun JSONObject.stringMap(): Map<String, String> {
        val result = linkedMapOf<String, String>()
        val iterator = keys()
        while (iterator.hasNext()) {
            val key = iterator.next()
            result[key] = opt(key).toString()
        }
        return result
    }

    private fun JSONObject.intMap(): Map<String, Int> {
        val result = linkedMapOf<String, Int>()
        val iterator = keys()
        while (iterator.hasNext()) {
            val key = iterator.next()
            result[key] = optInt(key, 0)
        }
        return result
    }

    private fun JSONArray.objects(): List<JSONObject> =
        (0 until length()).mapNotNull { index -> optJSONObject(index) }

    // 字符串数组要单独取：objects() 只拿 JSONObject，警告列表会被整段丢掉
    private fun JSONArray.strings(): List<String> =
        (0 until length()).mapNotNull { index ->
            optString(index, "").takeIf { it.isNotBlank() }
        }

    fun parsePlan(raw: JSONObject): Plan {
        val nodes = raw.optJSONArray("nodes")?.objects().orEmpty().map { item ->
            PlanNode(
                id = item.text("id"),
                type = item.text("type"),
                title = item.text("title"),
                start = item.text("start"),
                end = item.text("end"),
                indoor = item.optBoolean("indoor", true),
                confirmed = item.optBoolean("confirmed", false),
                windowLatest = item.text("windowLatest").ifBlank { null },
                alternatives = item.optJSONArray("alternatives")?.objects().orEmpty().map { alt ->
                    Alternative(
                        id = alt.text("id"),
                        title = alt.text("title"),
                        indoor = alt.optBoolean("indoor", true),
                        start = alt.text("start"),
                        end = alt.text("end"),
                        travelMin = alt.optInt("travelMin", 0),
                        place = alt.text("place"),
                        sacrifice = alt.text("sacrifice"),
                        contact = alt.text("contact"),
                    )
                },
                place = item.text("place"),
                contact = item.text("contact"),
                persons = item.optJSONArray("persons")?.let { array ->
                    (0 until array.length()).map { index -> array.optString(index) }
                }.orEmpty(),
                sacrifice = item.text("sacrifice"),
            )
        }
        val edges = raw.optJSONArray("edges")?.objects().orEmpty().map { item ->
            PlanEdge(
                from = item.text("from"),
                to = item.text("to"),
                minGapMin = item.optInt("minGapMin", 0),
            )
        }
        // 生成器把这些放在 generation 字段里；内置计划没有这一段，读成空即可
        val generation = raw.optJSONObject("generation")
        val warnings = generation?.optJSONArray("warnings")?.strings().orEmpty()
        val unresolved = generation?.optJSONArray("unresolvedMustVisit")?.strings().orEmpty()

        return Plan(
            planId = raw.text("planId"),
            title = raw.text("title"),
            date = raw.text("date"),
            version = raw.optInt("version", 1),
            nodes = nodes,
            edges = edges,
            generationWarnings = warnings,
            unresolvedMustVisit = unresolved,
        )
    }

    fun parseImpact(data: JSONObject): Impact = Impact(
        states = data.optJSONObject("states")?.stringMap().orEmpty(),
        shifts = data.optJSONObject("shifts")?.intMap().orEmpty(),
        ratio = data.optDouble("ratio", 0.0),
        path = data.text("path").ifBlank { "local" },
        affectedCount = data.optInt("affectedCount", 0),
        totalCount = data.optInt("totalCount", 0),
    )

    fun parseRepair(data: JSONObject): RepairResult {
        val schemes = data.optJSONArray("schemes")?.objects().orEmpty().map { item ->
            RepairScheme(
                id = item.text("id"),
                label = item.text("label"),
                keepRate = item.optDouble("keepRate", 1.0),
                changedCount = item.optInt("changedCount", 0),
                actions = item.optJSONArray("actions")?.objects().orEmpty().map { action ->
                    RepairAction(
                        nodeId = action.text("nodeId"),
                        action = action.text("action"),
                        payload = action.optJSONObject("payload")?.stringMap().orEmpty(),
                        reason = action.text("reason"),
                        sacrifice = action.text("sacrifice"),
                    )
                },
                sacrifice = item.text("sacrifice"),
            )
        }
        return RepairResult(
            status = data.text("status").ifBlank { "ok" },
            schemes = schemes,
            blockedNode = data.text("blockedNode").ifBlank { null },
            message = data.text("message"),
        )
    }

    fun parseWeather(data: JSONObject): Weather = Weather(
        source = data.text("source"),
        fetchedAt = data.text("fetchedAt"),
        rainProb = data.optDouble("next2hRainProb", 0.0),
        text = data.text("text"),
        isDemo = data.optBoolean("isDemo", false),
        basis = data.optString("basis", ""),
        note = data.optString("note", ""),
    )
}

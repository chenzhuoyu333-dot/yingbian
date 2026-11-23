package com.example.yingbian.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InterfaceAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import java.net.URL
import java.util.concurrent.atomic.AtomicReference

/**
 * 自动寻找后端：四段式，尽量在任何网络条件下都能找到。
 *
 * 顺序（先快后慢，找到就停）：
 *   0. 已知地址   —— 上一次连成功的那个，先试 300ms
 *   1. UDP 广播   —— 向后端 8001 喊暗号，1.5 秒；跨 /24 也能收到
 *   2. 同网段扫   —— 每块网卡的 /24，约 254 个地址
 *   3. 大网段扫   —— 校园网常见 /20（4094 个），有预算上限 + 并发 64
 *
 * 为什么必须做第 3 段：
 *   校园网 `scut-student` 是 10.195.144.0/20。手机在 10.195.159.x、
 *   电脑可能在 10.195.146.x —— 同一个子网，但不在同一个 /24。
 *   只扫 /24 会永远找不到。这是"平板能找、手机找不到"的第二层原因。
 *
 * 不做：不扫外网、不后台常驻、不在用户没触发时耗电。
 */
object ServerDiscovery {

    const val DEFAULT_PORT = 8000
    const val DISCOVERY_PORT = 8001
    private const val MAGIC = "YINGBIAN_DISCOVER"

    /** 大网段扫描的地址预算与并发（越界就只扫前 N 个，避免扫爆） */
    private const val WIDE_MAX_HOSTS = 2048
    private const val WIDE_CONCURRENCY = 64

    /**
     * 找后端。
     * @param known 已知地址（上次连成功过的），会最先试
     * @param onPhase 进度回调：告诉用户现在在做什么（界面上显示）
     */
    suspend fun find(
        port: Int = DEFAULT_PORT,
        known: List<String> = emptyList(),
        onPhase: (String) -> Unit = {},
    ): String? = withContext(Dispatchers.IO) {
        // 0) 已知地址
        if (known.isNotEmpty()) {
            onPhase("试上次连过的地址…")
            known.forEach { base ->
                val host = hostOf(base)
                if (host != null && probe(host, port)) return@withContext "http://$host:$port"
            }
        }

        // 1) UDP 广播
        onPhase("广播寻找…")
        broadcastFind()?.let { return@withContext it }

        // 2) 同网段（每块网卡的 /24）
        val nets = localNetworks()
        if (nets.isEmpty()) return@withContext null

        onPhase("扫描同网段…")
        scanHosts(nets.flatMap { hostsOf(it, sameSlash24Only = true) }, port, 16)
            ?.let { return@withContext it }

        // 3) 大网段（/20 这类），预算内扫
        val wide = nets.flatMap { hostsOf(it, sameSlash24Only = false) }
            .distinct()
            .take(WIDE_MAX_HOSTS)
        if (wide.isNotEmpty()) {
            onPhase("扫描更大的网段（" + wide.size + " 个地址）…")
            scanHosts(wide, port, WIDE_CONCURRENCY)?.let { return@withContext it }
        }
        null
    }

    /** 诊断：这次到底看了哪些网段 */
    fun describeNetworks(): String {
        val nets = localNetworks()
        if (nets.isEmpty()) return "没有可用的 IPv4 网卡（Wi-Fi 是否已连接？）"
        return nets.joinToString("；") { net ->
            val wide = hostsOf(net, sameSlash24Only = false).size
            "${net.ip}/${net.prefixLength}（可扫 $wide 个，广播 ${net.broadcast ?: "无"}）"
        }
    }

    // ── UDP 广播 ────────────────────────────────────────

    private fun broadcastFind(timeoutMs: Int = 1500): String? {
        val magic = MAGIC.toByteArray()
        val targets = buildList {
            add("255.255.255.255")
            localNetworks().mapNotNull { it.broadcast }.forEach { add(it) }
        }.distinct()

        val socket = runCatching {
            DatagramSocket().apply {
                broadcast = true
                soTimeout = 400
            }
        }.getOrNull() ?: return null

        return try {
            targets.forEach { target ->
                runCatching {
                    socket.send(
                        DatagramPacket(magic, magic.size, InetAddress.getByName(target), DISCOVERY_PORT)
                    )
                }
            }
            val buffer = ByteArray(512)
            val deadline = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < deadline) {
                val packet = DatagramPacket(buffer, buffer.size)
                try {
                    socket.receive(packet)
                } catch (_: SocketTimeoutException) {
                    continue
                }
                val json = runCatching {
                    JSONObject(String(packet.data, 0, packet.length))
                }.getOrNull() ?: continue
                if (json.optString("app") != "yingbian") continue
                val httpPort = json.optInt("http", DEFAULT_PORT)
                return "http://${packet.address.hostAddress}:$httpPort"
            }
            null
        } catch (_: Exception) {
            null
        } finally {
            socket.close()
        }
    }

    // ── 扫地址 ──────────────────────────────────────────

    private suspend fun scanHosts(hosts: List<String>, port: Int, concurrency: Int): String? {
        if (hosts.isEmpty()) return null
        val found = AtomicReference<String?>(null)
        coroutineScope {
            hosts.chunked(concurrency).forEach { chunk ->
                if (found.get() != null) return@forEach
                chunk.map { ip ->
                    async(Dispatchers.IO) {
                        if (found.get() == null && probe(ip, port, timeoutMs = 500)) {
                            found.compareAndSet(null, "http://$ip:$port")
                        }
                    }
                }.awaitAll()
            }
        }
        return found.get()
    }

    private data class LocalNet(
        val ip: String,
        val prefixLength: Int,
        val broadcast: String?,
    )

    /** 所有非回环 IPv4；Wi-Fi 排最前，移动数据排最后 */
    private fun localNetworks(): List<LocalNet> = try {
        NetworkInterface.getNetworkInterfaces()
            .toList()
            .filter { iface -> runCatching { iface.isUp && !iface.isLoopback }.getOrDefault(false) }
            .sortedBy { iface ->
                val name = iface.name.lowercase()
                when {
                    name.startsWith("wlan") || name.startsWith("ap") -> 0
                    name.startsWith("eth") -> 1
                    name.startsWith("rmnet") || name.startsWith("ccmni") -> 3
                    else -> 2
                }
            }
            .flatMap { iface ->
                iface.interfaceAddresses.mapNotNull { address: InterfaceAddress ->
                    val inet = address.address ?: return@mapNotNull null
                    val host = inet.hostAddress ?: return@mapNotNull null
                    if (host.contains(':')) return@mapNotNull null
                    if (inet.isLoopbackAddress || host.startsWith("169.254.")) return@mapNotNull null
                    LocalNet(
                        ip = host,
                        prefixLength = address.networkPrefixLength.toInt(),
                        broadcast = address.broadcast?.hostAddress,
                    )
                }
            }
            .distinctBy { it.ip }
    } catch (_: Exception) {
        emptyList()
    }

    /**
     * 按网卡自己的掩码算候选地址。
     * @param sameSlash24Only true 只扫本 /24；false 按真实掩码（/20 会算出上千个）
     */
    private fun hostsOf(net: LocalNet, sameSlash24Only: Boolean): List<String> {
        val octets = net.ip.split('.').mapNotNull { it.toIntOrNull() }
        if (octets.size != 4) return emptyList()

        if (sameSlash24Only) {
            // 从自己附近往外扫：电脑和手机通常在相近的地址上，
            // 比从 .1 顺序扫更快命中，弱网也不会先耗完时间。
            val own = octets[3]
            return (1..254)
                .sortedBy { kotlin.math.abs(it - own) }
                .map { "${octets[0]}.${octets[1]}.${octets[2]}.$it" }
                .filter { it != net.ip }
        }

        val prefix = if (net.prefixLength == 0) 24 else net.prefixLength
        if (prefix >= 24) {
            return (1..254).map { "${octets[0]}.${octets[1]}.${octets[2]}.$it" }
                .filter { it != net.ip }
        }
        // /20 之类：保留前 (prefix) 位，后面全遍历，但有预算上限
        val base = octets[0] shl 24 or (octets[1] shl 16) or (octets[2] shl 8) or octets[3]
        val mask = if (prefix == 0) 0 else (-1 shl (32 - prefix))
        val network = base and mask
        val hostBits = 32 - prefix
        val total = 1 shl hostBits
        val hosts = mutableListOf<String>()
        var index = 1
        while (index < total - 1 && hosts.size < WIDE_MAX_HOSTS) {
            val value = network + index
            val ip = "${(value ushr 24) and 0xFF}.${(value ushr 16) and 0xFF}." +
                "${(value ushr 8) and 0xFF}.${value and 0xFF}"
            if (ip != net.ip) hosts.add(ip)
            index++
        }
        return hosts
    }

    private fun hostOf(base: String): String? {
        val trimmed = base.removePrefix("http://").removePrefix("https://")
        val host = trimmed.substringBefore(':').substringBefore('/')
        return host.takeIf { it.isNotBlank() }
    }

    private fun probe(ip: String, port: Int, timeoutMs: Int = 500): Boolean {
        var connection: HttpURLConnection? = null
        return try {
            // 用轻量探针，不拉整份计划列表；弱网下响应体越小越容易成功。
            connection = (URL("http://$ip:$port/api/netinfo").openConnection() as HttpURLConnection).apply {
                connectTimeout = timeoutMs
                readTimeout = timeoutMs
                requestMethod = "GET"
            }
            if (connection.responseCode != 200) return false
            val text = connection.inputStream.bufferedReader().use { it.readText() }
            text.contains("\"ok\"") || text.contains("\"lan\"")
        } catch (_: Exception) {
            false
        } finally {
            connection?.disconnect()
        }
    }
}

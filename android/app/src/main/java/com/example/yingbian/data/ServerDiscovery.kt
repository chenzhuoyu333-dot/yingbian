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
 * 自动寻找后端。
 *
 * 为什么不能只扫地址（v1 的错）：
 *   手机常常同时开着流量和 Wi-Fi，`NetworkInterface` 里第一个 IPv4 可能是
 *   移动数据的 10.x —— 于是扫了一个跟后端无关的网段，永远找不到。
 *   平板上通常只有 Wi-Fi，所以"平板能用、手机不行"。
 *
 * 现在的顺序：
 *   1) UDP 广播（快，1.5 秒内出结果；跨 /24 也能收到）
 *      向后端 8001 端口喊一句暗号，它回"我在这 + HTTP 端口"
 *   2) 扫地址回退（广播被 AP 隔离挡掉时用）
 *      按每个网卡自己的网段算范围，/28 只扫 14 个而不是 254 个
 *
 * 三种情况都不做：不扫外网、不扫不相关网段、不后台常驻。
 */
object ServerDiscovery {

    const val DEFAULT_PORT = 8000
    const val DISCOVERY_PORT = 8001
    private const val MAGIC = "YINGBIAN_DISCOVER"

    /** 找后端；找不到返回 null，调用方保留用户手填的地址 */
    suspend fun find(port: Int = DEFAULT_PORT): String? = withContext(Dispatchers.IO) {
        // ① UDP 广播：有后端就一定有回应
        broadcastFind()?.let { return@withContext it }

        // ② 回退：按网段扫（用每块网卡自己的掩码，避免扫 254 个）
        val targets = candidateHosts()
        if (targets.isEmpty()) return@withContext null

        val found = AtomicReference<String?>(null)
        coroutineScope {
            targets.chunked(16).forEach { chunk ->
                if (found.get() != null) return@forEach
                chunk.map { ip ->
                    async(Dispatchers.IO) {
                        if (found.get() == null && probe(ip, port)) {
                            found.compareAndSet(null, "http://$ip:$port")
                        }
                    }
                }.awaitAll()
            }
        }
        found.get()
    }

    /** 诊断信息：告诉用户到底扫了哪些网段（失败时界面能说清楚） */
    fun describeTargets(): String {
        val nets = localNetworks()
        if (nets.isEmpty()) return "没有可用的 IPv4 网卡"
        return nets.joinToString("；") { "${it.ip}/${it.prefixLength} (广播 ${it.broadcast ?: "无"})" }
    }

    // ── UDP 广播 ────────────────────────────────────────

    private fun broadcastFind(timeoutMs: Int = 1500): String? {
        val magic = MAGIC.toByteArray()
        val addresses = buildList {
            add("255.255.255.255")
            localNetworks().mapNotNull { it.broadcast }.forEach { add(it) }
        }.distinct()

        val socket = DatagramSocket().apply {
            broadcast = true
            soTimeout = timeoutMs
        }
        return try {
            addresses.forEach { target ->
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
                socket.receive(packet)
                val text = String(packet.data, 0, packet.length)
                val json = runCatching { JSONObject(text) }.getOrNull() ?: continue
                if (json.optString("app") != "yingbian") continue
                val httpPort = json.optInt("http", DEFAULT_PORT)
                return "http://${packet.address.hostAddress}:$httpPort"
            }
            null
        } catch (_: SocketTimeoutException) {
            null
        } catch (_: Exception) {
            null
        } finally {
            socket.close()
        }
    }

    // ── 网卡与网段 ──────────────────────────────────────

    private data class LocalNet(
        val ip: String,
        val prefixLength: Int,
        val broadcast: String?,
    )

    /**
     * 所有非回环 IPv4 网卡。
     * 优先把 Wi-Fi（wlan）排在前面 —— 后端几乎总在同一 Wi-Fi 上。
     */
    private fun localNetworks(): List<LocalNet> = try {
        NetworkInterface.getNetworkInterfaces()
            .toList()
            .filter { iface -> runCatching { iface.isUp && !iface.isLoopback }.getOrDefault(false) }
            .sortedBy { iface ->
                val name = iface.name.lowercase()
                when {
                    name.startsWith("wlan") || name.startsWith("ap") -> 0
                    name.startsWith("eth") -> 1
                    name.startsWith("rmnet") || name.startsWith("ccmni") -> 3  // 移动数据排最后
                    else -> 2
                }
            }
            .flatMap { iface ->
                iface.interfaceAddresses.mapNotNull { address: InterfaceAddress ->
                    val inet = address.address ?: return@mapNotNull null
                    val host = inet.hostAddress ?: return@mapNotNull null
                    if (host.contains(':')) return@mapNotNull null          // 跳过 IPv6
                    if (inet.isLoopbackAddress) return@mapNotNull null
                    if (host.startsWith("169.254.")) return@mapNotNull null // 跳过自动分配
                    host.startsWith("127.").
                        let { isLoop -> if (isLoop) return@mapNotNull null }
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

    /** 按每个网卡自己的掩码算要扫的地址，最多 512 个（防止 /16 扫爆） */
    private fun candidateHosts(): List<String> {
        val out = mutableListOf<String>()
        localNetworks().forEach { net ->
            val parts = net.ip.split('.')
            if (parts.size != 4) return@forEach
            val octets = parts.mapNotNull { it.toIntOrNull() }
            if (octets.size != 4) return@forEach

            // 只处理 /24 及更小的网络（前缀 >= 24）；更大的网段交给 UDP 广播
            val suffixRange = when {
                net.prefixLength >= 24 -> 1..254
                net.prefixLength == 25 -> 1..126
                net.prefixLength == 26 -> 1..62
                net.prefixLength == 27 -> 1..30
                net.prefixLength == 28 -> 1..14
                else -> 1..254    // 更小的网段（/16~）不细扫，靠广播
            }
            suffixRange.forEach { last ->
                val candidate = "${octets[0]}.${octets[1]}.${octets[2]}.$last"
                if (candidate != net.ip) out.add(candidate)
            }
        }
        return out.distinct().take(512)
    }

    private fun probe(ip: String, port: Int): Boolean {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL("http://$ip:$port/api/plans").openConnection() as HttpURLConnection).apply {
                connectTimeout = 300
                readTimeout = 300
                requestMethod = "GET"
            }
            if (connection.responseCode != 200) return false
            val text = connection.inputStream.bufferedReader().use { it.readText() }
            text.contains("\"plans\"")
        } catch (_: Exception) {
            false
        } finally {
            connection?.disconnect()
        }
    }
}

package com.example.yingbian.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.NetworkInterface
import java.net.URL
import java.util.concurrent.atomic.AtomicReference

/**
 * 自动寻找后端。
 *
 * 为什么需要：开发机的局域网 IP 一天能变七八次（校园网每次重连都换），
 * 每次都要重新打包 APK 才能连上，演示当天换网络就废了。
 *
 * 做法：手机和后端在同一网段，所以扫自己 /24 里的 254 个地址，
 * 谁在 8000 端口回了合法响应就是后端。8 个并发、每个 300ms 超时，
 * 最坏 2 秒左右出结果。
 *
 * 不做的事：不扫外网、不扫别的网段、不在后台常驻。
 * 只在用户点「自动寻找」时扫一次。
 */
object ServerDiscovery {

    const val DEFAULT_PORT = 8000

    /** 找后端；找不到返回 null（调用方应当保留用户手填的地址） */
    suspend fun find(port: Int = DEFAULT_PORT): String? = withContext(Dispatchers.IO) {
        val local = localIpv4() ?: return@withContext null
        val prefix = local.substringBeforeLast('.', "")
        if (prefix.isBlank()) return@withContext null

        val found = AtomicReference<String?>(null)
        val candidates = (1..254).map { "$prefix.$it" }

        coroutineScope {
            candidates.chunked(8).forEach { chunk ->
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

    /** 探测一个地址：能拿到 JSON 即认为是我们自己的后端 */
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

    /** 本机在 Wi-Fi 上的 IPv4，比如 10.195.159.30 */
    private fun localIpv4(): String? = try {
        NetworkInterface.getNetworkInterfaces()
            .toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.inetAddresses.toList() }
            .firstOrNull { address ->
                !address.isLoopbackAddress && address.hostAddress?.contains(':') == false
            }
            ?.hostAddress
    } catch (_: Exception) {
        null
    }
}

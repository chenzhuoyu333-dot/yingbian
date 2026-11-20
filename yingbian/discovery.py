"""UDP 广播发现：比扫 254 个地址快得多，也不受 /20 大子网影响。

原理：
  后端在 UDP 8001 上守着一句话；App 往广播地址喊一句，
  谁是我们的人谁就回一句"我在这，HTTP 在 8000"。

为什么比扫地址好：
  · 手机可能同时在流量和 Wi-Fi 上，扫地址容易扫错网段（手机 IP 也是 10.x）
  · 校园网常是 /20（4094 个地址），扫不全
  · 广播只看"同一个广播域"，跨 /24 也能收到，1.5 秒内出结果

启动：随服务一起起（FastAPI startup），不用单独跑。
限制：校园网若开了 AP 隔离/禁广播，收不到 —— 所以客户端仍保留扫地址作为回退。
"""

from __future__ import annotations

import json
import socket
import threading

MAGIC = "YINGBIAN_DISCOVER"
REPLY_PORT = 8001
HTTP_PORT = 8000

_started = False
_lock = threading.Lock()


def _serve() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", REPLY_PORT))
    except OSError:
        # 端口被占用：可能已经有一个实例在守，静默退出
        return

    while True:
        try:
            data, addr = sock.recvfrom(512)
        except OSError:
            return
        if MAGIC.encode() not in data:
            continue
        try:
            sock.sendto(
                json.dumps(
                    {"app": "yingbian", "http": HTTP_PORT, "host": addr[0]}
                ).encode(),
                addr,
            )
        except OSError:
            continue


def start() -> bool:
    """启动发现服务（幂等）。返回是否本次真的启动了。"""
    global _started
    with _lock:
        if _started:
            return False
        _started = True
    thread = threading.Thread(target=_serve, name="yingbian-discovery", daemon=True)
    thread.start()
    return True

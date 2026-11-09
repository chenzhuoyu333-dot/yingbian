"""
W2 · 接口服务（只用 Python 标准库，不需要 pip install）

跑法：python -m src.api
然后浏览器打开  http://localhost:3000

六个端点：
  GET  /api/plan/<id>            取计划
  POST /api/plan/<id>/event      发事件，算三态
  POST /api/plan/<id>/repair     求三个方案
  POST /api/plan/<id>/apply      应用方案，生成新版本
  POST /api/plan/<id>/undo       撤销
  GET  /api/weather?lat=&lng=    真实天气（没配 Key 就明确标注"演示数据"）

设计取舍：算法全在后端，客户端只渲染。
"""
import copy
import json
import os
import socket
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import load_plan
from .propagate import propagate
from .repair import repair_all, apply_action

PORT = int(os.environ.get("PORT", "3000"))

# ── 内存状态：一份计划 + 版本历史（撤销靠它）──────────
_INITIAL = load_plan()
STORE = {
    "plan": copy.deepcopy(_INITIAL),
    "history": [copy.deepcopy(_INITIAL)],
}
PLAN_ID = STORE["plan"]["planId"]


def version():
    return len(STORE["history"])


def reset():
    STORE["plan"] = copy.deepcopy(_INITIAL)
    STORE["history"] = [copy.deepcopy(_INITIAL)]


# ── 天气 ────────────────────────────────────────────
def fetch_weather(lat, lng):
    """
    优先用真实数据；拿不到就返回"演示数据"并明确标注。
    这是"数据诚实"的实现：绝不把演示数据伪装成真实预报。
    """
    key = os.environ.get("QWEATHER_KEY", "").strip()
    now = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M")

    if not key:
        return {
            "source": "演示数据（未配置 QWEATHER_KEY 环境变量）",
            "isDemo": True,
            "fetchedAt": now,
            "next2hRainProb": 0.7,
            "text": "15:00 起中雨",
            "note": "这是演示数据，不是真实预报。配置 QWEATHER_KEY 后会改为真实数据。",
        }

    try:
        url = "https://devapi.qweather.com/v7/weather/24h?location=%s,%s&key=%s" % (lng, lat, key)
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        hours = (data.get("hourly") or [])[:2]
        probs = [int(h.get("pop") or 0) / 100.0 for h in hours] or [0.0]
        prob = max(probs)
        text = "%s 起%s" % (hours[0]["fxTime"][11:16], hours[0]["text"]) if hours else "未知"
        return {
            "source": "和风天气",
            "isDemo": False,
            "fetchedAt": now,
            "next2hRainProb": prob,
            "text": text,
            "note": "",
        }
    except Exception as e:  # 网络/配额/Key 失效都走这里
        return {
            "source": "演示数据（真实天气获取失败）",
            "isDemo": True,
            "fetchedAt": now,
            "next2hRainProb": 0.7,
            "text": "15:00 起中雨",
            "note": "真实接口失败：%s" % e,
        }


# ── 页面 ────────────────────────────────────────────
INDEX_HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>应变 · 接口自测</title>
<style>
body{font-family:-apple-system,"Segoe UI",sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#222}
h1{font-size:20px}button{margin:4px 6px 4px 0;padding:8px 14px;border:1px solid #1565C0;background:#fff;color:#1565C0;border-radius:8px;cursor:pointer}
button:hover{background:#1565C0;color:#fff}
pre{background:#f5f5f5;padding:14px;border-radius:8px;overflow:auto;max-height:520px;font-size:12px;line-height:1.5}
.muted{color:#888;font-size:13px}
</style></head><body>
<h1>应变 · 接口自测</h1>
<p class="muted">点按钮看返回。这一页就是 B 的"接口契约实物"。</p>
<div>
  <button onclick="go('GET','/api/plan/PLANID')">1 取计划</button>
  <button onclick="go('POST','/api/plan/PLANID/event',{type:'rain',from:'15:00',to:'17:00',prob:0.7})">2 下雨 → 三态</button>
  <button onclick="go('POST','/api/plan/PLANID/repair',{event:{type:'rain',from:'15:00',to:'17:00',prob:0.7}})">3 求三方案</button>
  <button onclick="go('POST','/api/plan/PLANID/event',{type:'cancel',nodeId:'n_lunch'})">4 餐厅取消</button>
  <button onclick="go('GET','/api/weather?lat=30.27&lng=120.15')">5 天气</button>
  <button onclick="go('POST','/api/plan/PLANID/undo')">6 撤销</button>
  <button onclick="go('POST','/api/reset')">重置</button>
</div>
<pre id="out">点上面任意按钮</pre>
<script>
const PLANID = "__PLANID__";
async function go(method, path, body){
  const url = path.replace('PLANID', PLANID);
  const opt = {method, headers:{'Content-Type':'application/json'}};
  if (body) opt.body = JSON.stringify(body);
  try{
    const r = await fetch(url, opt);
    const j = await r.json();
    document.getElementById('out').textContent = JSON.stringify(j, null, 2);
  }catch(e){
    document.getElementById('out').textContent = '请求失败：' + e;
  }
}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "Yingbian/0.2"

    # 让小程序 / 浏览器都能调
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text):
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code, message, status=400):
        self._json({"ok": False, "error": {"code": code, "message": message}}, status)

    def _ok(self, data):
        self._json({"ok": True, "data": data})

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            raise ValueError("请求体不是合法 JSON：%s" % e)

    # ── 路由 ────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._html(INDEX_HTML.replace("__PLANID__", PLAN_ID))

        if path == "/api/reset":
            reset()
            return self._ok({"reset": True, "version": version()})

        if path == "/api/weather":
            lat = query.get("lat", ["30.27"])[0]
            lng = query.get("lng", ["120.15"])[0]
            return self._ok(fetch_weather(lat, lng))

        if path.startswith("/api/plan/"):
            rest = path[len("/api/plan/"):]
            parts = rest.split("/")
            pid = parts[0]
            if pid != PLAN_ID:
                return self._fail("PLAN_NOT_FOUND", "没有这个计划：%s" % pid, 404)
            if len(parts) == 1:
                return self._ok({"plan": STORE["plan"], "version": version()})

        return self._fail("NOT_FOUND", "没有这个地址：%s" % path, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/reset":
            reset()
            return self._ok({"reset": True, "version": version()})

        if not path.startswith("/api/plan/"):
            return self._fail("NOT_FOUND", "没有这个地址：%s" % path, 404)

        parts = path[len("/api/plan/"):].split("/")
        pid = parts[0]
        action = parts[1] if len(parts) > 1 else ""

        if pid != PLAN_ID:
            return self._fail("PLAN_NOT_FOUND", "没有这个计划：%s" % pid, 404)

        try:
            body = self._body()
        except ValueError as e:
            return self._fail("BAD_JSON", str(e))

        # 只发事件，算三态
        if action == "event":
            prop = propagate(STORE["plan"], body)
            return self._ok({
                "states": prop["states"],
                "shifts": prop["shifts"],
                "ratio": round(prop["ratio"], 4),
                "path": prop["path"],
                "affectedCount": prop["affected"],
                "totalCount": prop["total"],
            })

        # 求方案
        if action == "repair":
            event = body.get("event") or body
            prop = propagate(STORE["plan"], event)
            res = repair_all(STORE["plan"], prop)
            return self._ok(res)

        # 应用方案
        if action == "apply":
            actions = body.get("actions") or []
            if not actions:
                return self._fail("NO_ACTIONS", "actions 不能为空")
            work = copy.deepcopy(STORE["plan"])
            applied = 0
            for a in actions:
                if apply_action(work, a.get("nodeId"), a):
                    applied += 1
            STORE["plan"] = work
            STORE["history"].append(copy.deepcopy(work))
            return self._ok({"plan": STORE["plan"], "version": version(), "applied": applied})

        # 撤销
        if action == "undo":
            if len(STORE["history"]) <= 1:
                return self._fail("NOTHING_TO_UNDO", "已经是最早的版本了", 409)
            STORE["history"].pop()
            STORE["plan"] = copy.deepcopy(STORE["history"][-1])
            return self._ok({"plan": STORE["plan"], "version": version()})

        return self._fail("NOT_FOUND", "没有这个操作：%s" % action, 404)

    def log_message(self, fmt, *args):
        print("  %s - %s" % (self.address_string(), fmt % args))


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    ip = lan_ip()
    print("")
    print("=" * 52)
    print("应变 · 接口服务已启动")
    print("=" * 52)
    print("本机访问：  http://localhost:%d" % PORT)
    print("局域网访问：http://%s:%d        <- B 用这个连" % (ip, PORT))
    print("")
    print("计划 ID：%s" % PLAN_ID)
    print("天气：%s" % ("已配置 QWEATHER_KEY，将使用真实数据" if os.environ.get("QWEATHER_KEY") else "未配置 Key，返回演示数据（会明确标注）"))
    print("按 Ctrl+C 停止")
    print("=" * 52)
    print("")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

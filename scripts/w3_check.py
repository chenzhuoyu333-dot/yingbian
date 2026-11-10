"""W3 收口自检：把"能演"这件事变成一条命令。

跑法（在项目根目录）：
    python scripts/w3_check.py
    python scripts/w3_check.py --base http://192.168.1.5:8000

检查范围（后端侧能验的部分）：
  1. 服务在跑、两份计划都加载了
  2. 取计划 / 发事件 / 求方案 / 应用 / 撤销 全链路通
  3. 锁定冲突时确实返回 blocked（不许自己改）
  4. 天气：真实 or 明确标注的演示数据，并且带 source / fetchedAt
  5. 有缓冲的计划里，延误能被缓冲吸收（不再一延误就全崩）

App 侧的五态、录屏、彩排不在本脚本范围内。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PASS = 0
FAIL = 0
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = '') -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        FAILED.append(name)
        print(f'  [FAIL] {name}' + (f'   {detail}' if detail else ''))


def call(base: str, path: str, method: str = 'GET', body: dict | None = None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode('utf-8'))
    except Exception as exc:
        return {'ok': False, 'error': {'code': 'CONNECT', 'message': str(exc)}}


RAIN = {'type': 'rain', 'from': '15:00', 'to': '17:00', 'prob': 0.7}
DELAY30 = {'type': 'delay', 'nodeId': 'n_meet', 'minutes': 30}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8000')
    ap.add_argument('--plan', default='p_sat_guzhen')
    ap.add_argument('--slack-plan', default='p_sat_guzhen_slack')
    args = ap.parse_args()
    base = args.base.rstrip('/')

    print()
    print('=' * 62)
    print(f'W3 自检 · {base}')
    print('=' * 62)

    print('\n[1] 服务与计划')
    ping = call(base, f'/api/plan/{args.plan}')
    check('服务可访问', ping.get('ok') is True, str(ping.get('error')))
    if not ping.get('ok'):
        print('\n服务没起来。先执行：python -m uvicorn server.app:app --host 0.0.0.0 --port 8000')
        report()
        return

    plan = ping['data']['plan']
    check('标准的 12 节点计划', len(plan['nodes']) == 12, f"实际 {len(plan['nodes'])}")
    check('有 5 个锁定节点', sum(1 for n in plan['nodes'] if n['confirmed']) == 5)
    slack = call(base, f'/api/plan/{args.slack_plan}')
    check('宽松版计划也已加载', slack.get('ok') is True)

    print('\n[2] 全链路')
    ev = call(base, f'/api/plan/{args.plan}/event', 'POST', RAIN)
    check('发事件返回 ok', ev.get('ok') is True)
    states = ev['data']['states']
    check('日落点被判为受影响', states.get('n_sunset') in ('at_risk', 'conflict'), states.get('n_sunset'))
    check('影响比重 < 0.3 走局部修复', ev['data']['ratio'] < 0.3, str(ev['data']['ratio']))

    rp = call(base, f'/api/plan/{args.plan}/repair', 'POST', {'event': RAIN})
    check('求方案返回 ok', rp.get('ok') is True)
    schemes = rp['data']['schemes']
    check('返回 3 个方案', len(schemes) == 3, f'实际 {len(schemes)}')
    if schemes:
        check('保留率 100%', all(abs(s['keepRate'] - 1.0) < 0.01 for s in schemes))
        check('每个方案都有"牺牲"说明', all(s.get('sacrifice') for s in schemes))

    b = next((s for s in schemes if s['id'] == 'B'), schemes[0] if schemes else None)
    if b:
        ap_res = call(base, f'/api/plan/{args.plan}/apply', 'POST', {'actions': b['actions']})
        check('应用方案成功', ap_res.get('ok') is True)
        v_after = ap_res['data']['version']
        check('版本号 +1', v_after >= 2, str(v_after))
        un = call(base, f'/api/plan/{args.plan}/undo', 'POST', {})
        check('撤销成功', un.get('ok') is True)
        check('撤销后版本回退', un['data']['version'] < v_after)

    print('\n[3] 锁定冲突必须停下来问人')
    lock = call(base, '/api/debug/lock', 'POST', {'planId': args.plan, 'nodeId': 'n_sunset', 'confirmed': True})
    check('锁定日落点成功', lock.get('ok') is True)
    blocked = call(base, f'/api/plan/{args.plan}/repair', 'POST', {'event': RAIN})
    check('返回 blocked 而不是自己改', blocked['data'].get('status') == 'blocked', str(blocked['data'].get('status')))
    check('指明是哪个节点', blocked['data'].get('blockedNode') == 'n_sunset', str(blocked['data'].get('blockedNode')))
    check('给出可读的提示语', bool(blocked['data'].get('message')))
    call(base, '/api/debug/lock', 'POST', {'planId': args.plan, 'nodeId': 'n_sunset', 'confirmed': False})
    call(base, '/api/reset', 'POST', {})

    print('\n[4] 天气必须是真实的，或者诚实标注为演示数据')
    w = call(base, '/api/weather?lat=30.259&lng=120.13')
    check('天气接口返回 ok', w.get('ok') is True)
    wd = w.get('data', {})
    check('带 source 字段', bool(wd.get('source')), str(wd))
    check('带 fetchedAt 字段', bool(wd.get('fetchedAt')))
    check('带 isDemo 标记', 'isDemo' in wd)
    if wd.get('isDemo'):
        check('演示数据有明确说明', bool(wd.get('note')), '演示数据必须能看出是演示数据')
        print('       注意：当前是演示数据（真实天气不可用），界面必须显示"演示数据"')
    else:
        check('真实数据带依据说明', bool(wd.get('basis')))
        print(f"       真实来源：{wd.get('source')}  文字：{wd.get('text')}  概率：{wd.get('next2hRainProb')}")

    print('\n[5] 缓冲必须真的吸收延误')
    s_ev = call(base, f'/api/plan/{args.slack_plan}/event', 'POST', DELAY30)
    check('宽松版发事件成功', s_ev.get('ok') is True)
    if s_ev.get('ok'):
        ratio = s_ev['data']['ratio']
        check('延误 30 分钟只影响少数节点（缓冲生效）', ratio < 0.6, f'ratio={ratio}')
        print(f'       宽松版影响 {s_ev["data"]["affectedCount"]}/{s_ev["data"]["totalCount"]}，path={s_ev["data"]["path"]}')
    c_ev = call(base, f'/api/plan/{args.plan}/event', 'POST', DELAY30)
    if c_ev.get('ok'):
        check('零缓冲计划同样延误被判定为全局变更', c_ev['data']['ratio'] > 0.6, f'ratio={c_ev["data"]["ratio"]}')
        print('       这一条就是"零缓冲 = 一延误就全崩"的实证')

    call(base, '/api/reset', 'POST', {})
    report()


def report() -> None:
    print()
    print('=' * 62)
    if FAIL == 0:
        print(f'全部通过：{PASS} 项')
        print('后端侧 W3 就绪。接下来是 App 侧：真机跑一遍 → 录屏 → 性能表。')
    else:
        print(f'通过 {PASS} 项，失败 {FAIL} 项：')
        for name in FAILED:
            print(f'  - {name}')
        sys.exit(1)
    print('=' * 62)
    print()


if __name__ == '__main__':
    main()

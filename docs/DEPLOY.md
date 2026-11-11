# 在 Commander-II 平台上部署

仓库里有两条运行路径，共用同一个策略 `Agent`：

- **平台路径**：`Core.py` 由平台调用，`Commander` SDK 由平台注入；
- **离线路径**：`worker.py` 用 JSONL 协议收发，不需要平台（测试与本地调试用）。

## 1. 平台环境

| 项目 | 要求 |
| --- | --- |
| Python | 3.6（平台内置），仅标准库 |
| 入口 | `Core.py` 的 `Load()` 与 `Main()` |
| 依赖 | `Core.py` 需要平台提供的 `Commander` 模块（`AI_SDK`、`GameMap`、`Verification`、`NODE_TYPE`） |
| 指令 | 每个观测只能提交一条合法指令 |

`Core.py` 用到的 SDK 接口：

```
GameMap.GetSize()                      -> (rows, cols)
GameMap.IsViewable(x, y)               -> bool
GameMap.GetType(x, y)                  -> NODE_TYPE
GameMap.GetBelong(x, y)                -> 归属方
GameMap.GetUnitNum(x, y)               -> 兵力
Verification.GetArmyID()               -> 我方席位
AI_SDK.DirectionToDestination(x, y, d) -> 该方向的目标格
AI_SDK.MoveByDirection(x, y, num, d)   -> 下发移动指令
```

## 2. 部署文件清单

把下面这些**平铺**放进平台要求的选手 AI 目录（与 `Core.py` 同级）：

```
Core.py
bfs_agent.py
parameters.json
std_*.py            # 全部 95 个模块中的 .py 文件
```

**不要**放进：`worker.py`、`tests/`、`tools/`、`docs/`、`README.md`、`PROVENANCE.md`、
`__pycache__/`。平台只需要 `Core.py` 及其 import 到的模块。

> `worker.py` 也可以一起放（它不 import `Commander`），但平台不会调用它；
> 如果目录大小或文件数有限制，优先留平台路径。

## 3. 观测到指令的数据流

```
平台
  │  Load(): GameMap.GetSize(), Verification.GetArmyID()
  ▼
Core.Main()
  │  逐格读取可见性/地形/归属/兵力；不可见但地形为 HILL 的格子 → hill_hints
  ▼
bfs_agent.Agent.decide(cells, hill_hints)
  │  经济/侦察/调兵/进攻候选 → 统一仲裁 → 一条指令
  ▼
Core.Main(): 方向查表 + move_number() 编码兵量
  │
  ▼
AI_SDK.MoveByDirection(src_r, src_c, num, direction)
```

`cells` 的取值用平台编码：`BLANK=1, KING=2, FORT=3, HILL=4, OBSTACLE=5, MARSH=6`，
`(地形, 归属, 兵力)` 三元组；不可见格不出现在字典里。

## 4. JSONL 离线协议（`worker.py`）

用于回放、批量评测或在没有平台时复现单步决策。

启动后 worker 先打印一行握手：

```json
{"ready": 1}
```

之后每行 stdin 是一个请求：

```json
{"id": 7,
 "observation": {
   "rows": 24, "cols": 24,
   "army": 1,
   "observer_seat": 1,
   "cells": [[1, 0, 0], [1, 0, 0], ...],
   "hill_hints": [[0, 0], [0, 23]],
   "action_mask": [true, true, ...],
   "action": 0
 }}
```

| 字段 | 说明 |
| --- | --- |
| `rows` / `cols` | 地图尺寸 |
| `army` | 本次控制的席位 |
| `observer_seat` | 观测者席位；与 `army` 不一致时拒绝（防止拿错视角） |
| `cells` | 按 `r * cols + c` 展平的 `[地形, 归属, 兵力]`，长度必须 `rows * cols` |
| `hill_hints` | 视野外 HILL 轮廓的 `[r, c]` 列表 |
| `action_mask` | 长度 `rows * cols * 6 + 1`，动作合法性掩码 |

回复一行：

```json
{"id": 7,
 "action": 502,
 "orders": [[1, 3, 11, 4, 11, 29]],
 "order": [1, 3, 11, 4, 11, 29],
 "debug": {"tick": 1, "mode": "assault", "decision_ms": 60.2, ...}}
```

- `action`：`0` 表示不动；`1 + (r * cols + c) * 6 + d` 表示从 `(r, c)` 往方向 `d` 移动；
- `order`：`[席位, 源行, 源列, 目标行, 目标列, 兵量]`；
- `debug`：诊断信息，含耗时、模式、策略路由等，可忽略。

违反契约（尺寸不符、席位不符、非法指令、兵量非正整数）会抛 `ValueError` 并以非零码退出，
测试 `tests/test_smoke.py` 覆盖了这些分支。

## 5. 调试开关

| 开关 | 作用 |
| --- | --- |
| `COMMANDER_BFS_TRACE=1` | `Core.py` 在自身目录写 `bfs-trace.jsonl`，每步一行诊断 |
| `worker.py` 的 `debug` | 每步返回 `decision_ms` / `cpu_ms` / `mode` / `strategy_route` |
| `tools/demo_worker.py` | 合成棋盘上跑通平台路径的等价流程 |

## 6. 上线前检查清单

- [ ] `python tools/validate_config.py` 通过，`parameters.json` 是参赛版本；
- [ ] `python -m unittest discover -s tests` 全绿；
- [ ] 目标目录平铺，没有 `tests/`、`tools/`、`docs/`、`__pycache__`；
- [ ] 只用标准库，没有 `pip install` 的东西；
- [ ] 平台 Python 版本是 3.6，没有用到 3.8+ 语法（本仓库保持 3.6 兼容）；
- [ ] 单步耗时在平台预算内（看 `debug.decision_ms`）；
- [ ] 首帧配置加载不超时（`parameters.json` 与 `std_config.py` 同目录）；
- [ ] 文件编码 UTF-8（模块与 JSON 都是）。

## 7. 常见问题

**Q：为什么 `move_number()` 不返回 0？**
平台的 `num=0` 表示"除一个外全部移动"，`0 < num < 1` 表示按比例。本策略只使用显式
数量，避免两次产兵之间"全发"超出计划；`tests/test_geometry.py` 固化了这个语义。

**Q：为什么 `Core.py` 里 `range(6)` 自己查方向，而不用 SDK 常量？**
方向表与 `std_geometry.OFFSETS` 保持一致，避免平台常量名随版本变化；查表失败会抛异常，
不会静默走错方向。

**Q：离线能复现比赛结果吗？**
不能。仓库能离线复现决策逻辑与配置语义；真实对局需要平台、地图、上帝 AI 基准与对手池。
见 [PROVENANCE.md](../PROVENANCE.md) 与 README 的"复现与评测"。

# 模块清单

> 本文件由 `tools/gen_docs.py` 自动生成，请勿手工编辑。

仓库共 **95 个 Python 模块 / 15379 行**（不含测试与工具脚本）。每个文件的模块文档字符串已概括其职责；这里的表格只摘取首行。

## 平台入口与适配

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `Core.py` | 52 | 您说得队 / BFS统御: visible SDK adapter, Python 3.6 standard library only. |
| `worker.py` | 45 | Observation-only JSONL adapter. Shares the exact SDK Agent and settings. |
| `bfs_agent.py` | 88 | Public strategy entry point; no SDK dependency. Python 3.6 standard library. |

## 几何与配置

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_geometry.py` | 25 | SDK-compatible hex geometry and terrain constants. |
| `std_config.py` | 288 | Strict experiment/deployment configuration; standard library only. |
| `std_parameters.py` | 103 | Frozen hunter defaults. Tunable overrides live in parameters.json. |

## 观测、状态与记忆

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_state.py` | 276 | State methods preserved from the frozen BFS hunter. |
| `std_road_graph.py` | 86 | Per-observation indexed graph for the unchanged signed pickup recurrence. |
| `std_force_belief.py` | 131 | Carry large observed hostile packets through loss of public visibility. |
| `std_mobility.py` | 86 | Short-lived uncertainty about a recently visible mobile hostile stack. |
| `std_reserve.py` | 57 | Observation-only estimate of the enemy's uncommitted mobile force. |
| `std_threat.py` | 40 | Shared-road projection of visible hostile stacks on one shortest-path tree. |
| `std_departure_warning.py` | 101 | Short warning from unexplained visible hostile departures, not snapshots. |
| `std_packets.py` | 69 | Current-stock packet accounting on an already observed friendly route. |

## 经济、扩张与产能

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_economy.py` | 408 | Visible-information economy helpers, Python 3.6, no SDK or strategy import. |
| `std_investment.py` | 73 | Choose a first producer before spending all king income on small land trades. |
| `std_investment_execution.py` | 65 | A confirmed first-fort dispatch retains its economic destination. |
| `std_fort_assembly.py` | 151 | Fund a fort capture by merging public current stock on an owned tree. |
| `std_neutral_funding.py` | 35 | Start a bounded economic phase only when an unfunded collection would win. |
| `std_nearby_capital.py` | 148 | Fund a short first-capital route through currently visible ordinary roads. |
| `std_nearby_retention.py` | 50 | Retain paid first-producer garrisons through the fragile economic phase. |
| `std_fort_survey.py` | 67 | Pay a small scout to inspect a blind first-fort approach before investment. |
| `std_colonize.py` | 139 | Current-funded first-fort convoys with an observed command sequence. |
| `std_expansion.py` | 73 | Expansion methods preserved from the frozen BFS hunter. |
| `std_producer.py` | 33 | Local producer counterattacks release only the eliminated threat's reserve. |
| `std_patience.py` | 37 | Keep a growing king out of low-force ordinary-tile capture cycles. |
| `std_blind_opening.py` | 36 | Insure the unexposed single-producer opening before the first raid. |
| `std_post_capital_guard.py` | 29 | Keep the paid home guard across confirmed first-fort acquisition. |
| `std_single_capital_fortress.py` | 102 | Concentrate a threatened single-producer empire before the last rescue hop. |
| `std_adjacent_income.py` | 56 | Buy a visible neighboring producer with currently funded surplus. |
| `std_adjacent_threat_relief.py` | 67 | Pay an atomic producer counterstrike against the resulting public threats. |

## 调兵、防守与供给

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_routing.py` | 106 | Routing methods preserved from the frozen BFS hunter. |
| `std_maneuver.py` | 452 | Legal-observation road proposals, ported from the reviewed Maneuver candidate. |
| `std_supply.py` | 48 | Shared-order tree DP adapted from YRFZ's reinforcement schedule principle. |
| `std_merge.py` | 37 | Pure shared-command collection; child branches merge before forwarding. |
| `std_logistics.py` | 73 | Logistics methods preserved from the frozen BFS hunter. |
| `std_rear_supply.py` | 186 | Confirmed rear convoys on one shared owned-road tree. |
| `std_recall_goal.py` | 48 | Anchor economic insurance to a confirmed goal; tactical defense stays independent. |
| `std_security.py` | 189 | Bounded FIFO defense schedules, adapted from 易如反掌/yr_mobilization.py. |
| `std_deadline_convoy.py` | 129 | One executable rescue proposal in the existing deadline-defense family. |
| `std_deadline_strike.py` | 46 | Compare a paid two-order elimination with the actual home deadline. |
| `std_convoy.py` | 127 | Finite current-stock rescue when the earliest deficit is already unfunded. |
| `std_corridor.py` | 102 | Deliver a funded column home through a short observed corridor. |
| `std_fortress_corridor.py` | 73 | Fund and reopen a visible supply corridor to an isolated king. |
| `std_recovery.py` | 69 | Short, fully funded king recovery after an observed large interception. |
| `std_king_recovery.py` | 94 | Bounded replenishment after observed king combat, using current stock only. |
| `std_repair.py` | 142 | Bounded repair of a thin king after a confirmed, costly interception. |
| `std_reinforcement.py` | 31 | Conservative independent-route cover under a shared command deadline. |
| `std_rescue_utility.py` | 42 | When every schedule misses the first gap, avoid tiny-delivery starvation. |
| `std_transport_path_guard.py` | 59 | Prevent ordinary supply from closing a recently confirmed friendly path. |
| `std_connected_reserve.py` | 29 | Do not demand disconnected soldiers at a persistently cut-off king. |
| `std_guard_pool.py` | 38 | Pay a mature king's existing insurance before a short-warning raid arrives. |
| `std_home_watch.py` | 345 | Local King security from current public sight and funded short routes. |
| `std_dispatch_deadline.py` | 56 | Resolve confirmed ordinary dispatch / long-horizon recall disagreements. |
| `std_reversal_recovery.py` | 89 | Recover confirmed defensive and ordinary friendly-edge reversals. |
| `std_frontier_handoff.py` | 162 | One confirmed, interruptible frontier continuation from current observation. |
| `std_frontier_paths.py` | 26 | Current funded packets on the shortest owned-distance DAG. |
| `std_frontier_sources.py` | 181 | Bounded source coverage from current reserves and visible frontier cells. |
| `std_frontier_value.py` | 40 | Compare a small feeder with an already funded identical capture suffix. |

## 侦察与信息价值

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_recon.py` | 391 | Recon methods preserved from the frozen BFS hunter. |
| `std_reconnaissance.py` | 83 | Small current-funded information routes after a local search chooses waiting. |
| `std_search_column.py` | 232 | Fund a route to genuinely unseen frontier cells from public stock. |
| `std_search_value.py` | 28 | Value first observations inside the existing frontier scoring system. |
| `std_main_column.py` | 142 | Recover whole-army movement after thin contact or stalled production. |
| `std_opening.py` | 104 | Contact-opening reserves, discovery packets, and bounded duel continuation. |
| `std_opening_exchange.py` | 40 | Price a tiny home interception while a recently seen stack is in fog. |
| `std_stage_value.py` | 86 | Price an unfunded collection detour from a currently visible king. |
| `std_commitment.py` | 54 | Bounded producer objectives; each callback must rebuild a funded schedule. |

## 战斗、攻防与目标排序

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_combat.py` | 181 | Combat methods preserved from the frozen BFS hunter. |
| `std_defense.py` | 130 | Defense methods preserved from the frozen BFS hunter. |
| `std_skirmish.py` | 157 | Bounded public-observation combat search; no engine or opponent imports. |
| `std_skirmish_support.py` | 30 | One-command adjacent support for the local search's leaf valuation only. |
| `std_tactical.py` | 172 | Bounded two-exchange public-board search, without engine access. |
| `std_joint_response.py` | 192 | Joint public replies and soft missing-force valuation after candidate admission. |
| `std_campaign.py` | 880 | Campaign methods preserved from the frozen BFS hunter. |
| `std_objectives.py` | 402 | Shared production timing and objective priorities from legal observations. |
| `std_decisions.py` | 99 | Decisions methods preserved from the frozen BFS hunter. |
| `std_multi_front_truce.py` | 22 | Do not pay for repeated low-value land trades against several rivals. |
| `std_rival_pressure.py` | 132 | Bounded missing-force scenarios from legal public observations. |
| `std_king_pressure.py` | 272 | Receding-horizon pressure on a currently visible enemy king. |
| `std_king_tempo.py` | 135 | Two-command king strikes funded by current local stock. |
| `std_king_bridge.py` | 63 | A narrow two-command king duel on a fully observed local board. |
| `std_king_opportunity.py` | 110 | Current-stock short approaches to publicly contested, weakened kings. |
| `std_king_prior.py` | 172 | Approximate four-player king regions, refined by public observations. |
| `std_response_control.py` | 134 | Bound repeated ambiguous-evidence decisions and abstain on unpriced plans. |
| `std_duel_raid_reserve.py` | 16 | Do not release half the king allocation while a large local raid is live. |

## 特殊地图 314

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_map314.py` | 97 | Recognize 314 from own spawn and witnessed terrain, then keep checking. |
| `std_map314_profile.py` | 34 | Offline 314.map terrain reference; contains no owners or units. |
| `std_map314_strategy.py` | 1012 | 314 three-player policy. Static geometry is public map knowledge. |

## 统一仲裁与增强层

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_continuous.py` | 1729 | Every-observation pure proposals; exactly one proposal is committed. |
| `std_enhancements.py` | 171 | Isolated, ablatable ideas from BFS teaching, YRFZ and campaign agents. |
| `std_opening_policy.py` | 345 | Transactional, observation-triggered transfer of the pinned Probe policy. |

## 移植的参考策略（见 PROVENANCE.md）

| 模块 | 行数 | 职责 |
| --- | ---: | --- |
| `std_probe_policy.py` | 925 | Persistent fog-of-war strategy, Python 3.6, standard library only. |
| `std_probe_economy.py` | 353 | Visible-information economy helpers, Python 3.6, no SDK or strategy import. |
| `std_probe_campaign.py` | 219 | Persistent field army: open a route before requiring a known enemy king. |

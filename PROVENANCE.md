# 代码来源与致谢

本仓库是「您说的队」在 **2026 ISCIIA 人工智能挑战赛 · Commander-II 对战平台** 上获得
一等奖的参赛智能体源码。为了让仓库可以独立阅读、离线验证，这里如实记录每一部分的来源。

## 1. 主体：队伍自研

`Core.py`、`worker.py`、`bfs_agent.py`、`std_continuous.py` 以及全部 `std_*.py`
策略模块由队伍在比赛期间编写、调参与消融。大量模块的文档字符串里保留了
"preserved from the frozen BFS hunter" 之类的说明，指的是队伍内部冻结的基线版本
（BFS 狩猎者基线），不是外部代码。

生产参数见 `parameters.json`，与 `std_config.DEFAULTS` 的差异在 `docs/PARAMETERS.md`
中逐项列出。

## 2. 从队伍自训对手迁移的部分

`std_probe_policy.py`、`std_probe_economy.py`、`std_probe_campaign.py` 三个模块
是"Probe"策略的迁移版本。仓库保留了当时的溯源记录：

- 文件：`opening_policy_provenance.json`
- 参考路径：`results/bfs_god12/reference-probe-three-god-post0800/agent`
- 原文件名与迁移后文件名、以及原始 `strategy.py` / `economy.py` / `campaign.py`
  的 SHA-256 校验值，均在该文件中。

队伍说明：**这些训练对手都是队伍自己此前训练/搭建的队伍**，用途是固定基准对抗
与消融对照，不是其他参赛队的提交代码。迁移过程做了三项改造：私有内联导入、
观测与决策分离、可选的逐观测节拍。

`std_enhancements.py`、`std_security.py`、`std_supply.py`、`std_patience.py` 等
模块的文档字符串提到的 `YRFZ`、`ProbeFort`、`campaign agents`，同样是队伍训练
流程中的对手或参考实现，用于"孤立、可消融"的增强实验。

> 如果这些训练对手的来源文件实际上包含第三方代码，请在公开仓库前自行核实；
> 若原作者提出异议，我们会移除或替换相应模块。

## 3. 地图与特殊分支

`std_map314_profile.py` 是 314 号地图的**静态地形**（`SIZE`、`SPAWNS`、`TERRAIN`），
不含归属、兵力和事件；地图哈希 `MAP_SHA256` 记录在文件顶部，用于确认与平台公开地图
一致。归属与兵力始终来自当次合法观测。该知识属于公开地图信息，由主办方随平台分发。

## 4. 没有随仓库分发的内容

为了尊重主办方与其他参赛者的权益，仓库**不包含**：

- Commander-II 平台本体、`Commander` SDK（`AI_SDK` / `GameMap` / `Verification` /
  `NODE_TYPE` 等）、可执行程序与训练工具；
- 任何地图文件、回放文件、`results/` 训练输出；
- 任何其他参赛队的提交包；
- 18 GB 的赛事资料压缩包（含主办方宣讲材料、可执行程序等）。

答辩路演 PPT 作为项目材料放在 `docs/您说的队-路演PPT.pptx`，它由队伍制作；其中引用的
赛事地图截图与北京理工大学标识，版权分别归主办方与学校，仅用于说明本队参赛与获奖情况，
不作商业用途。若版权方有异议，我们会立即移除该文件。

`Core.py` 依赖平台提供的 `Commander` 模块，仓库里只有调用方的适配代码。

## 5. 原始提交与当前代码的对应关系

答辩材料记录的原始提交包为
`Commander-II/最终兼容性测试/Commander-II/智能体/选手AI/py/您说得队.zip`，
SHA-256 为：

```
e9e7818dfb8f5fcdde47ade352048f4323a37c6003eab97933bb1c9715b957dc
```

本仓库在该提交包的基础上补齐了文档、测试、CI 与离线运行工具；策略代码本身未做
重写。如需逐字节比对，请用上面的哈希核对原始提交包。

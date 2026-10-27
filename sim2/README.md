# sim2：协议级事件仿真器

> 只运行抽象协议模型，不连接、不测量任何真实系统。所有命令都在仓库根目录下运行。

## 架构

| 文件 | 作用 |
|---|---|
| `engine_event.py` | **唯一的协议规则定义**：每个副本一个状态机，加一个全局事件队列。支持 P1/P2、三种角色和对手计划，可以对任意视图区间原地求解。也负责加权计票（`RunConfig.vote_weights`）、签名记录（`track_signed`）和签名视图单调规则（`vote_monotone`，即 R3） |
| `engine_fast.py` | 两个闭式核心：QC 核心（视图内无超时）和纯 TC 核心（任何地方都形成不了 QC）。不满足时调用事件引擎求解；遇到加权、签名记录等配置时整段转交事件引擎 |
| `common.py` | 配置 `RunConfig`、角色、共享状态 `State`、链与提交（`commit_times`，两链提交）；加权法定份额 `weighted_hit`（份额严格大于 2/3）；提案到达时间 `proposal_timing`，含提案转发（`RunConfig.prop_forward`："hdr" 转发提案头、缺块者级联取块，"full" 转发整个提案；`_forwarded_timing`）、上行串行发送（`uplink_serial`）、NR 含块（`nr_requires_data`）与每视图提案字节数 `st.prop_bytes` |
| `schedule.py` | 带滞后的领导者规则与证据：<br>• R0 均匀，R1/R2 失败率剖面，R3 Carousel 式排除；<br>• **R5 `CusumExclusion`**：CUSUM 定罪、排除上限（可按权重，严格先进先出队列）、期满、G1 永久禁止；可选第二条软证据 CUSUM（只取消领导资格）；<br>• 证据 `bad_fact`："失败提议者"、AT 指控、交易包含证言 `omit`、"无 QC" `noqc`、加权出块时长 `slot`；<br>• 槽位时长分数 `slot_score` 与加权版本 `weighted_slot_score`（证书由 u+2 的领导者组装）；门限 `slot_threshold`（绝对门限或近若干视图中位数的倍数，封顶在超时以下）；<br>• NR 自相矛盾 `liars`、E3 证据检查 `e3_violators`；<br>• `verify_leaders`：按最终事实事后重算领导者，检查是否用到了未定稿的事实 |
| `ttru.py` | T_tru 权重：基础权重 CapNorm(质押 + π·K)（单实体上限、未认证类上限），按纪元生成权重表；信誉 r 只罚不奖、总降权受预算 B_rep 约束；G1 证实者 z=0 |
| `txlayer.py` | 交易层与交易包含证言（G2）：转发、守卫窗口、到期判定（计数或加权门槛）、豁免、审查与陷害对手 |
| `adversary.py` | 对手插件（每个视图一份 `ViewPlan`）：收集者陷害、扣票、沉默领导者、部分发送（可定向到最重的诚实节点）、了解规则的自适应部分发送、慢领导者、数据扣留、定时释放（`TimedRelease`、`AdaptiveTimedRelease`）、NR 谎报（含贪心说谎者）、组合等 |
| `net.py` | 合成网络：区域与接入延迟、有界抖动、带宽、独立迟到（模型 P）、区域故障、GST 前的异步期 |

**协议：** P2 投票广播；P1 投票只发给下一任领导者（单收集者）。两者都用两链提交、Jolteon 式推进器（TC 携带 highQC）和转发。

**领导者事实：** 第 v 个视图的领导者只能使用 u ≤ v − lag 的事实（默认 lag=10）。两个引擎对拍一致不能证明事实在使用时已经定稿，所以另用 `verify_leaders` 事后检查，测试要求 0 个不一致。

## 校验

```bash
python -m sim2.tests.test_regression
```

```bash
python -m sim2.tests.test_weighted
```

```bash
python -m sim2.tests.test_v05
```

其余测试：`test_m0`、`test_m1prep`、`test_m2`、`test_m3`、`test_rules`、`test_dirA`、`test_nrc`、`test_inc`。

- `test_regression`：重构前保存的 144 份输出，两个引擎（288 次运行）逐位复现（golden 数据在 `tests/golden/`）。
- `test_weighted`：等份额时加权计票与按个数计票逐位一致；活性门槛在 1/3 处翻转；信誉预算缩放；加权运行中领导者全部来自定稿事实；定向部分发送的已知性质。
- `test_v05`：软证据排队状态机、按权重的排除上限（先进先出）、E3 检查（含对抗调度下的正例）、R3、软证据运行的事实定稿、加权交易到期门槛；提案转发的时序与字节（手工网络）、转发下的数据扣留与 NR 定义、加权分位界的随机性质检验、相对门限。

## 实验

实验脚本在 `experiments/`，结果写到 `results/`。T_tru 相关的实验：

| 脚本 | 内容 |
|---|---|
| `dirTtru.py at / budget` | 加权下的 AT + CUSUM；信誉预算界 |
| `dirTtruTune.py run / run_x / run_beta / plot` | AT 门槛 x 与 CUSUM ρ̄ 的联合调参；样本量与同伙份额 |
| `dirTtruSoft.py run / plot` | P2 中"无 QC"作为软证据；领导者攻击下的吞吐 |
| `dirTtruSlot.py run / plot` | 加权出块时长分数作为软证据（慢领导者、部分发送） |
| `dirTtruFwd.py run / net / timed / plot` | 提案转发对部分发送、数据扣留、扣票 + 迟到、慢领导者的作用（两个基线）；出块时长门限在不同网络下的误判与 100 Mbps 下的代价；定时释放 |
| `dirTtruRobust.py async / adaptive` | GST 前的混乱期（随机延迟、区域故障、对抗调度）；了解规则的自适应攻击者 |
| `dirTtruG1.py` | G1 罚没（NR 自相矛盾 → z=0）闭环 |
| `dirTtruInc.py reliab / detect` | 加权交易包含证言的可靠性与审查检出 |
| `dirTtruE3.py` | 诚实节点 E3 证据的硬检查（含 R3 开关与正例） |
| `ttru_perf.py` | 公用指标（提交比例、每秒提交块数）与混乱期网络 |

并行度用环境变量 `SIM_PROCS`（默认 8），人群数用 `SIM_SEEDS`。例如：

```bash
SIM_PROCS=8 SIM_SEEDS=8 python -m sim2.experiments.dirTtru at
```

`m0_*`、`m1_*`、`m2_*`、`m3_*`、`dirA*`、`dirC_*`、`dirNRC*` 是早期阶段（领导者信誉模块、收集者问责、在线学习、NR 自相矛盾）的实验，保留以便复现。`m1_e2_collapse.py` 依赖仓库根目录 `sim/` 下的两个抽象模型。

## 已知的简化

| 内容 | 说明 |
|---|---|
| 不模拟分叉与冲突块 | 跨纪元安全与可问责安全只靠证明；仿真器在固定视图换权重表 |
| 证书格式与签名不建模 | 证据按协议规则从状态中判定 |
| `noqc` 读取的是"任一节点形成过 QC" | 与链上可验证的"QC 被后续提案携带"约有 1/700 个视图的差别 |
| 投票和超时不携带 SyncInfo；窗口回算不重放窗口前的在途消息 | 已知近似，实测无差异 |
| 同时刻事件的平局顺序两个引擎不同 | 连续抖动网络上不会出现；整数网格网络上不保证逐位一致 |
| 上行带宽只有串行发送模型（`uplink_serial`，默认关闭） | 不含拥塞控制、gossip 扇出与纠删码；默认关闭时大块、大 n 下低估提案时间 |
| P3（PBFT）未实现 | — |

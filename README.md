# T_tru 加权 BFT 仿真器（信任 2.0）

**Trust 2.0 (T_tru) weighted voting for HotStuff-style BFT consensus: chain base weight with entity caps from certification × bounded reputation × graded suspension, driven by framing-resistant evidence. Event-level protocol simulator, bounded model checking, and cost-of-corruption analysis. Simulation only.**

这个仓库是"信任 2.0"方案的仿真代码。方案面向许可链或联盟链中 HotStuff/PBFT 一类的 BFT 共识，让每个节点的投票权由各链原有的基础权重、机构认证（实体上限与类别上限）和信誉共同决定，作恶的处罚从共识机制本身入手、按证据分级，并研究这样做是否安全、作恶成本有多高。

> 只运行抽象模型，不连接、不测量任何真实系统。

## 方案要点

投票权

$$T_i=\mathrm{CapNorm}(w_i)\cdot r_i\cdot z_i$$

- $w_i$ 是各链原有的基础权重：PoS 用质押，联盟链用等权或治理设定的权重；
- CapNorm 设两道上限：单个实体（由机构认证绑定受益所有人）不超过 cap，未认证参与者合计不超过 $u_{\max}$，用来防止权重集中；
- $r_i\in[r_{\min},1]$ 是信誉，只罚不奖，全网被信誉降掉的权重合计不超过预算 $B_{\mathrm{rep}}$；
- $z_i$ 是暂停开关：被不可伪造的证据证实作恶时，按级别暂停或逐出。

> 早期版本的公式是 $\mathrm{CapNorm}(s_i+\pi_iK_i)$，把可执行的牌照价值计入权重；`sim2/ttru.py` 与 `ttru/` 仍按这个写法实现，取 $K=0$ 即为当前公式（$w$ = 质押）。协议级结论（预算界、AT、可问责安全）与基础权重怎样来无关。

证据分档，**谁能伪造这条证据，决定它能造成多大后果**：

| 档 | 证据 | 后果 |
|---|---|---|
| G1 不可伪造 | 同视图双签、为非法块投票、highQC 倒退（E3）、NR 自相矛盾 | 分级处罚：按证据类型、被定罪实体的基础份额合计与再犯次数，取消出块资格、暂停（z = 0，期满恢复；同时暂停的份额不超过 10%）或逐出（生效前经联盟治理确认） |
| G2 联名证言 | AT 指控（份额 > 2/3 的超时报告"到超时为止没拿到可用的提案"，即没同时拿到提案头和块）、交易包含证言 | 在预算内降信誉 |
| 其他数据 | "视图没形成 QC"、出块时长等 | 一律不用（评估过的软证据见下文"活性"） |

## 目录

| 目录 | 内容 |
|---|---|
| `sim2/` | 协议级事件仿真器：HotStuff 两链提交、P1/P2 两种投票方式、加权计票、领导者规则与证据、对手模型、合成网络、交易层；测试与实验。详见 [`sim2/README.md`](sim2/README.md) |
| `ttru/` | 静态经济学分析（按早期公式 V = s + πK 计算，现为对比记录）：凑齐 1/3 投票权的最低收买成本（精确背包）、K×π 区域图与持平点、处罚不可执行与代理问题、一次安全违背的罚没下界、跨纪元法定集合相交的穷举检验 |
| `formal/` | 可问责安全定理（Jolteon 型两链 HotStuff，TC 进入投票规则）的有界模型检查：Python 显式状态穷举 `mc_jolteon.py` 与 TLA+ 规范 `JolteonAccountability.tla`（4 份 TLC 配置）；取证开销估算 `overhead.py` |
| `sim/` | 早期阶段的两个抽象模型（`d4_sim.py`、`d4_finite_memory.py`），供 `sim2/experiments/m1_e2_collapse.py` 引用 |

## 环境

Python 3.9 及以上：

```bash
pip install -r requirements.txt
```

## 运行

所有命令都在仓库根目录下运行。

校验（几十秒到几分钟）：

```bash
python -m sim2.tests.test_regression
```

```bash
python -m sim2.tests.test_weighted
```

```bash
python -m sim2.tests.test_v05
```

协议级实验（结果写到 `sim2/results/`；完整规模需要多核机器，可用 `SIM_PROCS`、`SIM_SEEDS` 调整）：

```bash
SIM_PROCS=8 python -m sim2.experiments.dirTtru at
```

推荐参数的复核（每格 50 个人群，带 95% 区间）：

```bash
SIM_PROCS=8 python -m sim2.experiments.dirTtruReview all
```

新方案（公式 A、分级处罚）的全部实验：

```bash
SIM_PROCS=8 python -m sim2.experiments.dirTtruV12 all
```

有界模型检查（4 节点、2 个拜占庭、3 个视图，十几秒）：

```bash
python formal/mc_jolteon.py --views 3
```

去掉"签名视图单调"规则（R3）后找反例：

```bash
python formal/mc_jolteon.py --views 3 --no-r3
```

TLA+ 版本需要 Java 和 `tla2tools.jar`（本仓库不附带，请从 TLA+ 官方发布页 github.com/tlaplus/tlaplus/releases 自行下载，放到 `formal/tools/`）。在 `formal/` 目录下运行：

```bash
java -XX:+UseParallelGC -cp tools/tla2tools.jar tlc2.TLC -workers auto -config JolteonAccountability_base.cfg JolteonAccountability.tla
```

取证开销（证书大小与需要内嵌 TC 的块比例）：

```bash
python formal/overhead.py
```

静态经济学（结果写到 `ttru/results/`）：

```bash
python ttru/ttru_region.py
```

```bash
python ttru/epoch_check.py
```

## 主要结果（仿真，合成人群）

- **安全：** 拜占庭基础权重 β0 < (1−B_rep)/3 时，信誉无论怎样被操纵，坏人的投票份额都低于 1/3；需要配合纪元交接规则（新权重表在旧纪元最后一块被提交后才生效）。实现中预算界被精确达到（`dirTtru budget`），跨纪元条件经穷举确认是紧的（`ttru/epoch_check.py`）。
- **抗陷害：** 用 AT 证据时，同伙陷害不会降低诚实节点的权重；用可被陷害的证据时，对手能把预算用满。推荐参数下，同伙谎报加 10%–30% 迟到、两种网络地理，600 次运行中诚实节点被定罪 0 次（每千个诚实领导视图 95% 上界 0.004，`dirTtruReview frame`）。GST 前的混乱期足够长、消息被对抗调度时，诚实节点被降权恰好用满预算，但不越过（`dirTtruReview chaos`）。
- **新方案的仿真（`dirTtruV12`）：** 公式 A 下陷害、沉默领导者、混乱期、预算界的结论不变（600 次运行诚实定罪 0；预算界被精确达到）。分级处罚中诚实节点从未因 G1 受罚，同时暂停份额从未超过 10%，同伙份额从未达到 1/3。仿真也暴露出三处：非分叉逐出后重算上限会把权重集中给未封顶的实体（一例同伙份额上涨 27%）；暂停上限会卡住份额超过 10% 的一批作恶者；AT 排除期加倍让被冤枉的诚实节点排除更久。
- **可问责安全：** 两个冲突块都被提交时，一定能从链上数据找出基础权重超过 1/3 的罪犯，且不冤枉诚实节点；前提是签名视图单调（R3）且 TC 写进块里。4 节点、3 个视图的小模型上，Python 穷举与 TLC 都得到 123,904 个状态、无违规；4 个视图由 TLC 完整穷举 58,799,585 个状态，无违规，按步数截断时与 Python 逐层一致；去掉 R3 后两者找到同一条反例（`formal/`）。把 TC 写进块里，n=200 时攻击下每块平均多约 345 字节，最多占 250 kB 块的 0.55%（`formal/overhead.py`）。
- **作恶成本（当前口径，解析结果）：** 一次安全违背的罪犯投票权超过 1/3、全部被逐出，若链按权重发放参与收益，罪犯在冷却期内至少失去全网参与超额收益的 (1−B_rep−L_e)/3（L_e 为此前已被暂停的基础权重，同时暂停的份额设上限 10%，最坏约 27%）；联盟链按投票权收取保证金时，至少没收全网保证金的同一比例。保证金按家平摊时，攻击者可以专挑权重大、保证金低的成员（31 个实体的算例：16.1% 对 33.6%）。
- **作恶成本（早期公式，对比记录）：** 权重按可没收价值（质押 + 可执行牌照价值）成比例分配时作恶成本最高；每家可执行牌照价值超过持平点（31 节点约 0.043，100 节点约 0.023，全网质押 = 1）时，比纯质押更难收买，比 1:1 投票难收买约 9–14 倍（`ttru/ttru_region.py`）。
- **活性（只给上界）：** 沉默领导者留下 AT 证据，会被排除；NR 位定义为"没拿到可用提案（头和块）"，所以只发头不发块的数据扣留也会被排除。定向部分发送、慢领导者、定时释放不留证据，它们不影响安全，吞吐约为正常的 1/(1+λ(τ/t₀−1))（λ 为坏人领导的视图占比，τ/t₀ 为超时与正常视图时长之比），实测 0.11–0.24。
  - 评估过、不采用：软证据（`dirTtruSoft`）、加权出块时长分数（`dirTtruSlot`）、提案转发（`dirTtruFwd`）。它们只挡住不了解规则的坏人；对了解全部规则的坏人只把底线抬高几个百分点（0.14–0.27），因为软证据为抗陷害须容忍约 80% 的坏视图，而每个坏视图耗掉接近一个超时。代码保留，选项默认关闭。

## 说明

- 设计文档与证明不在本仓库中。分级处罚在 `sim2/punish.py`（`dirTtruV12`）；早期的 `dirTtruG1` 按旧规则（被证实即 z = 0）执行。模型检查只覆盖小规模配置，不是对任意规模的证明。
- 结果中的数字来自合成人群（Pareto 持股分布），用于比较方案，不代表任何真实网络。

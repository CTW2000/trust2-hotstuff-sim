# T_tru 加权 BFT 仿真器（信任 2.0）

**Trust 2.0 (T_tru) weighted voting for HotStuff-style BFT consensus: certification × stake × reputation with framing-resistant evidence. Event-level protocol simulator plus economic (cost-of-corruption) analysis. Simulation only.**

这个仓库是"信任 2.0"方案的仿真代码。方案面向许可链或联盟链中 HotStuff/PBFT 一类的 BFT 共识，让每个节点的投票权由机构认证、质押和信誉三个因子共同决定，并研究这样做是否安全、作恶成本有多高。

> 只运行抽象模型，不连接、不测量任何真实系统。

## 方案要点

投票权

$$T_i=\mathrm{CapNorm}(V_i)\cdot r_i\cdot z_i,\qquad V_i=s_i+\pi_iK_i$$

- $V_i$ 是**可没收价值**：质押 $s_i$，加上牌照价值 $K_i$ 乘以牌照处罚真正能执行的概率 $\pi_i$；
- CapNorm 设两道上限：单个实体不超过 cap，未认证参与者合计不超过 $u_{\max}$，用来防止权重集中；
- $r_i\in[r_{\min},1]$ 是信誉，只罚不奖，全网被信誉降掉的权重合计不超过预算 $B_{\mathrm{rep}}$；
- $z_i$ 是罚没：被不可伪造的证据证实作恶时清零。

证据分三档，**谁能伪造这条证据，决定它能造成多大后果**：

| 档 | 证据 | 后果 |
|---|---|---|
| G1 不可伪造 | 同视图双签、为非法块投票、highQC 倒退（E3）、NR 自相矛盾 | 罚没，z = 0 |
| G2 联名证言 | AT 指控（份额 > 2/3 的超时报告"到超时为止没拿到可用的提案"，即没同时拿到提案头和块）、交易包含证言 | 在预算内降信誉 |
| G3 软证据 | "视图没形成 QC"、加权出块时长分数超过门限 | 只取消领导资格 |

## 目录

| 目录 | 内容 |
|---|---|
| `sim2/` | 协议级事件仿真器：HotStuff 两链提交、P1/P2 两种投票方式、加权计票、领导者规则与证据、对手模型、合成网络、交易层；测试与实验。详见 [`sim2/README.md`](sim2/README.md) |
| `ttru/` | 静态经济学分析：凑齐 1/3 投票权的最低收买成本（精确背包）、K×π 区域图与持平点、处罚不可执行与代理问题、一次安全违背的罚没下界、跨纪元法定集合相交的穷举检验 |
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

静态经济学（结果写到 `ttru/results/`）：

```bash
python ttru/ttru_region.py
```

```bash
python ttru/epoch_check.py
```

## 主要结果（仿真，合成人群）

- **安全：** 拜占庭基础权重 β0 < (1−B_rep)/3 时，信誉无论怎样被操纵，坏人的投票份额都低于 1/3；需要配合纪元交接规则（新权重表在旧纪元最后一块被提交后才生效）。实现中预算界被精确达到（`dirTtru budget`），跨纪元条件经穷举确认是紧的（`ttru/epoch_check.py`）。
- **抗陷害：** 用 AT 证据时，同伙陷害不会降低诚实节点的权重；用可被陷害的证据时，对手能把预算用满。
- **作恶成本：** 按可没收价值成比例分配权重时作恶成本最高；牌照处罚能执行、且每家可执行牌照价值超过持平点（31 节点约 0.043，100 节点约 0.023，全网质押 = 1）时，T_tru 比纯质押更难收买，比 1:1 投票难收买约 9–14 倍，且没有单个实体能凑齐 1/3（`ttru/ttru_region.py`）。
- **活性（有缺口）：** 坏领导者的部分发送和慢领导者攻击不留可罚没证据，不加防御时能把吞吐压到正常的 10%–20%。
  - **提案转发**（诚实节点收到提案就转发签名的提案头，缺块者向持有块的诚实节点取块）让不考虑时序的部分发送失效，吞吐 0.27 → 0.79。NR 位须定义为"没拿到可用提案（头和块）"，否则只发头不发块的数据扣留能躲过 AT。在独立逐消息迟到下，它也修复了"扣票 + 迟到"。31 节点时带宽约 1.6 倍，随节点数增长（`dirTtruFwd`）。
  - **加权出块时长分数**（门限取近 200 个视图中位数的 3 倍）排除每次都拖延的慢领导者（`dirTtruSlot`、`dirTtruFwd`）。
  - **了解全部规则的坏人仍能把吞吐压到正常的约 15%–27%**：在少数诚实节点超时前一刻才送达提案（定时释放，转发无效），或只在不到约 80% 的自己视图里拖延。原因是软证据为抗陷害须容忍约 80% 的坏视图，而每个坏视图耗掉接近一个超时。吞吐约为 1/(1+λp*(τ/t₀−1))，可以限定，不能消除（`dirTtruFwd timed`）。

## 说明

- 设计文档与证明不在本仓库中。
- 结果中的数字来自合成人群（Pareto 持股分布），用于比较方案，不代表任何真实网络。

# 市场环境系统——设计规范 v5.1（中文版）

**状态：** 架构基线；实现与校准尚待完成  
**Schema 版本：** `5.1`  
**Feature-contract 版本：** `5.1`  
**决策记录：** `research/market/discussion/market-regime-discussion.md`，Message 1–67  
**取代：** `Market_Regime_Design_v5.0.md`  
**历史前身：** `market_regime_claude.md` v4.4（已冻结）

> 本文是英文规范 `Market_Regime_Design_v5.1.md` 的完整中文说明版。公式、字段名、枚举值和规范性状态保留英文，以便直接对应实现。若翻译含义与英文原文存在冲突，以英文规范为准。

## 0. 权威性与状态术语

本文是 Market Regime v5.1 唯一的设计规范，纳入了 v5.0 §19 中全部十项 `INHERITED_PENDING_REVIEW` 的审查结论。它是一份具有破坏性变更的度量契约，不代表系统已经实现，也不是 v4.4 或 v5.0 的补充条款。

以下状态标签具有规范意义：

- **CLOSED（已定案）：** 架构或不变量已经确定。
- **EMPIRICAL（待实证）：** 功能角色和测试边界已经确定，但公式、数据源、系数、周期、阈值或是否采用，必须由证据决定。
- **OUT_OF_SCOPE（范围外）：** 有意排除在度量引擎之外。

规范性要求使用 **MUST（必须）**、**MUST NOT（不得）**、**SHOULD（应当）** 和 **MAY（可以）**。任何 EMPIRICAL 参数不得被描述为最终常数。除非本文另有明确说明，v4.4 的数值只能作为比较基线。

## 1. 产品边界与设计哲学

### 1.1 核心哲学：度量事实，而不是发出行动指令

系统只描述当前市场环境，输出：

- 四个“数值越高、环境越有利”的支柱：Direction、Breadth、Risk Appetite、Stability；
- `[0,1]` 区间的 `condition_score`；
- 与支持度正交的方向符号 `direction_sign ∈ {-1,0,+1}`；
- 五个互斥状态之一：`CRISIS`、`RISK_OFF`、`NEUTRAL`、`RISK_ON`、`TRENDING`；
- `[-1,1]` 区间的带符号 `impulse_score`；
- 四项彼此独立的 Confidence 诊断；
- 原始特征、数据源质量、门控、上限、危机及状态机诊断。

所有支柱和 Condition 的高值始终代表环境更有利；只有 `direction_sign` 表达方向，而不是支持度。

度量结果是描述性事实，绝不是交易动作。因此度量 schema 不得输出或别名映射下列内容：

- `position_size_multiplier`、`portfolio_risk_budget`、`target_exposure`；
- `strategy_fit`、`tf_fit`、`vs_fit`、`mr_fit`；
- `tradable_signal`、推荐策略、订单方向或买入/加仓/退出标记；
- `recovery_throttle`、`risk_budget`、`exposure_permission`、`leverage_factor`。

尤其要避免以下误读：

- `direction_sign` 不是多空路由器；
- `BULL_PULLBACK` 不是买入信号；
- `RISK_ON` 和 `RISK_OFF` 不足以单独决定仓位；
- `TRENDING` 不等于允许加杠杆；
- Condition 不是仓位乘数。

独立版本化的策略/路由产品可以消费不可变的 v5.1 输出，并结合策略、品种、组合、成本、流动性、融资和授权约束作决策，但不得反向改写度量历史或状态。

迁移期可以使用独立版本化的 `legacy_v4_policy_adapter` 保持旧消费者行为；它不是 v5.1 度量输出，也不代表 v5.1 认可旧策略，且必须有自己的版本和一致性测试。

### 1.2 路径依赖原则

Condition 不包含配置政策或隐藏的“事件阶段记忆”。在每个声明回看窗口内，只要有效输入完全相同，支柱和 Condition 就必须完全相同。

只有两类有限且明确声明的确认逻辑允许具有路径依赖：

1. `direction_structure` 的确认；
2. 分类 regime 状态机。

回放时必须用足够历史重建这些状态，或恢复精确版本化的持久状态。任何依赖历史阶段的敞口缩放均属于下游政策层。

### 1.3 系统真正要回答的五个问题

理解本系统最重要的一点，是不要把所有市场信息压缩成一个含义模糊的“牛熊指标”。v5.1 实际上把问题拆成五个互不等价的问题：

1. **市场价格朝哪个方向运行？**——由 `direction_structure` 和 `direction_sign` 回答。
2. **当前环境对承担市场风险有多大支持？**——由四个支柱汇总为 `condition_score`。
3. **当前属于哪一种可解释的环境类型？**——由五状态状态机回答。
4. **环境正在改善还是恶化，速度多快？**——由 `impulse_score` 回答。
5. **这次判断的数据质量、支柱一致性和边界稳定性如何？**——由四项 Confidence 诊断回答。

这五个问题必须分开，因为它们可能给出不同答案。例如：

- 指数仍在长期均线上方，所以 Direction 可能为正；
- 但信用利差恶化、市场参与度坍缩、短端隐含波动率飙升，所以 Condition 可能很低；
- 状态因此可以是 `RISK_OFF`，而不是把“方向仍正”错误翻译成 `RISK_ON`；
- 如果 Condition 已从极低水平快速回升，Impulse 又可以为正；
- 若关键 Breadth 数据不完整，则判断仍可能不可用，而不是假装“中性”。

因此，**方向、支持度、类别、变化速度和判断可信度是五个坐标轴，不是一条轴上的五种说法。**

### 1.4 为什么度量层必须与交易政策分离

同一个市场事实，对不同参与者可能意味着不同动作：

- 长线资产配置者面对 `RISK_OFF` 可能降低风险预算；
- 市场中性策略可能仍然正常运行；
- 趋势跟随策略在负方向趋势中甚至可能增加空头机会；
- 受禁止卖空约束的账户则只能减仓或观望。

如果度量引擎直接输出仓位或买卖信号，它就会把特定投资授权、策略周期和成本假设偷偷嵌入“市场事实”，导致同一历史不能被不同策略公平复用。v5.1 因而采用单向边界：

```text
市场数据 → 不可变的环境度量 → 独立政策/策略 → 仓位与订单
```

后面的政策可以读取前面的度量，但不能反向改变历史度量。这样做带来三个直接好处：可复现、可审计、可跨策略复用。

### 1.5 为什么既要连续 Condition，又要离散 State

`condition_score` 和 `state` 解决不同问题：

- 连续分数保留细微变化，适合比较“今天比昨天改善多少”；
- 离散状态提供稳定、可解释的环境标签，适合报告和下游规则引用；
- 若只用连续分数，阈值附近会频繁翻转；
- 若只用离散状态，状态内部的重要变化会被隐藏。

所以系统先计算无记忆的连续 Condition，再通过带有限滞后的状态机形成稳定标签。**状态机可以记住待确认转换，Condition 本身不能记住过去的政策或事件阶段。**

### 1.6 总体推理链

从输入到输出的逻辑可以概括为：

```text
数据是否有效？
  ├─ 否 → 相关支柱与 Condition = unavailable；保留旧状态时标记 stale
  └─ 是
      ↓
价格方向、参与广度、风险偏好、稳定性分别如何？
      ↓
形成四个同极性的支持度支柱
      ↓
加权得到 condition_pre_cap
      ↓
是否存在必须立即尊重的单域危险？
  ├─ 是 → hard veto，Condition = 0，至少 RISK_OFF
  └─ 否 → 应用经实证批准的连续 soft cap（默认没有）
      ↓
是否有至少两个独立急性压力域同时确认？
  ├─ 是 → CRISIS
  └─ 否 → 由普通状态边界、非对称滞后及 TRENDING 资格确定状态
      ↓
对最终 Condition 计算 Impulse；并行发布 Confidence 与归因诊断
```

这个顺序不是排版选择，而是语义约束：先判断数据能不能信，再度量各维度，之后处理安全约束，最后才形成稳定标签与变化诊断。

## 2. 处理拓扑

```text
版本化原始序列 + 元数据
              │
              ▼
       对齐 / 新鲜度 / 预热
              │
              ▼
      标准原始特征（只计算一次）
              │
              ▼
        必要时进行因果变换
              │
              ▼
 Direction ─ Breadth ─ Risk Appetite ─ Stability
              │
              ▼
      condition_pre_cap [0,1]
              │
       硬否决 / 可选软上限
              │
              ▼
        condition_score [0,1]
       ┌──────┼─────────┐
       ▼      ▼         ▼
   Impulse Confidence  状态机
                         │
                         ▼
 CRISIS / RISK_OFF / NEUTRAL / RISK_ON / TRENDING
```

同一个标准特征可以有多个已声明消费者，这不构成重复计数。真正的重复计数，是把同一经济特征用不一致的数据源、窗口、极性或尺度分别重算，再放入多个支柱。

### 2.1 四个支柱为何是这四个

四个支柱对应市场环境的四类不同证据：

| 支柱 | 核心问题 | 主要证据 | 如果单独使用会漏掉什么 |
|---|---|---|---|
| Direction | 基准价格结构是否有利？ | 价格与多周期均线、路径质量 | 指数可由少数权重股支撑，掩盖内部恶化 |
| Breadth | 上涨/健康是否广泛参与？ | 成分股或行业参与度 | 广度强不等于信用和波动环境安全 |
| Risk Appetite | 资金是否愿意承担信用和风格风险？ | 信用利差、成长/小盘相对轮动 | 相对偏好可以改善，但市场绝对价格仍可能下跌 |
| Stability | 市场运行是否平稳、损伤是否有限？ | 隐含波动、波动曲线、已实现波动、price damage | 平静不等于趋势向上，也不等于参与广泛 |

选择这四类并不是因为它们完全不相关，而是因为每一类都能揭示其他三类无法可靠替代的失效模式。

### 2.2 为什么所有支柱都统一为 supportive-positive

原始变量的自然方向不一致：VIX 和 OAS 越高通常越危险，而 Breadth 和路径质量越高通常越有利。若直接相加，符号错误很难发现。因此每个原始特征先声明 polarity，再转换成统一语义：

```text
pillar ↑  ⇒ 对承担市场风险的环境支持度 ↑
pillar ↓  ⇒ 环境支持度 ↓
```

统一极性使加权和具有清晰含义，也允许建立单调性测试。例如，在其他输入不变时，VIX 下跌不得让 Stability 下降；Breadth 覆盖改善不得让 data completeness 下降。

`direction_sign` 被刻意排除在这种统一极性之外，因为“向下趋势很清晰”与“环境很有利”不是同一件事。

### 2.3 为什么标准特征只能计算一次

例如 `price_damage` 同时与 Stability、CRISIS 和 TRENDING 有关。正确做法是从同一基准合约计算一个标准值，再由多个模块消费：

```text
canonical price_damage
  ├─ Stability：转成 price_stability 支持度
  ├─ CRISIS：判断急性价格损伤域
  └─ TRENDING：限制趋势状态资格
```

如果三个模块各自用不同回撤窗口、复权方法或数据源重算，系统表面上引用同一概念，实际上却无法解释、无法复现，也可能重复放大同一风险。标准特征单源复用，就是为了防止这种语义漂移。

## 3. 数据契约

### 3.1 必需元数据

每个原始字段和派生字段必须声明：

- provider、symbol、field、dataset version；
- source tier，以及使用后备源的原因；
- 观测和发布时间戳、时区、交易日历、频率；
- 单位、币种、复权/总回报政策；
- 如适用，修订与 vintage 政策；
- 新鲜度与过期上限；
- 缺失数据和后备规则；
- coverage denominator 与预热要求；
- 重复值和对齐政策；
- 极性：supportive-positive、adverse-positive、signed-directional 或 non-directional；
- 可测试的单调性断言；
- 所有消费者。

### 3.2 基准合约

必须固定使用一个 S&P 500 基准合约：SPX，或一个明确声明的 SPY 总回报代理。已发布历史中不得切换。Direction、已实现波动率、基准收益和标准 `price_damage` 必须来自同一序列及版本。

RSP 不属于 v5.1 Direction 输入；随着 TrendQuality 中集中度项去重，RSP 已被移除。

### 3.3 Breadth 数据层级

- **Tier 1（首选）：** 时点无偏成分股、当时有效的行业分类，以及所有合格成分股的复权收盘价；或权威的时点历史行业指数序列。
- **Tier 2（可复现长历史）：** 全历史固定使用九只行业 ETF：`XLK, XLF, XLV, XLY, XLP, XLE, XLI, XLB, XLU`。
- **Tier 3（仅诊断）：** 固定十一只 ETF，在共同且完全预热的样本内增加 `XLRE`、`XLC`。不得自动替换 Tier 2，也不得拼接历史。

### 3.4 Risk Appetite 输入

概念上的必需输入为：

- 时点高收益债 OAS 水平与变化，并带 publication/vintage 元数据；
- QQQ、IWM 和固定的 SPY 总回报序列。

只有在独立版本化的数据源层级中，经过验证的 ETF 信用代理才可以使用。HYG 配合 IEF 和/或 LQD（包括久期中性变体）仍是与 OAS 比较的 EMPIRICAL 方案，必须标记为“不等价”。

### 3.5 Stability 输入

标准生产输入为：

- VIX spot；
- VIX9D；
- 固定的基准总回报序列。

VIX3M 只能作为独立数据契约下的诊断/挑战者，不是标准生产必需输入。其他跨资产压力序列也不是必需项。

### 3.6 不增加额外数据源

CRISIS 重用波动率/期限结构压力、信用压力、标准 `price_damage` 和固定 Breadth。TRENDING 重用 Direction/TrendQuality、`price_damage`、Risk Appetite 和 Stability。Confidence 只消费已有输出、决策边界、元数据和引擎状态。

### 3.7 明确排除项

Fed Funds、US2Y、US10Y、收益率曲线、DXY、实际利率、盈亏平衡通胀率、宏观数据发布、组合持仓、订单、杠杆、RecoveryThrottle、目标敞口和策略配置均不决定 v5.1 regime。

这些数据缺失不得降低 `data_completeness`，也不得使 Condition 不可用。

## 4. 对齐、可用性与状态持久化

### 4.1 Fail closed

任何必需数据缺失、过期、错位或预热不足，都会使受影响支柱和 Condition 不可用。绝不能填成中性值或数值零。最后一个分类状态只可在 `state_is_current = false` 且给出明确 reason code 时保留。

数据中断代表“未知”，不代表 `CRISIS`。

### 4.2 预期交易日

所有周期均按预期交易日计算，不得按任意现有行数计算。一个因果 504 日变换，需要原始特征自身回看期完成后，再有 504 个有效且对齐的预期交易日观测；嵌套特征需要更多前置历史。

### 4.3 持久化状态

以下状态必须连同 schema 版本和 as-of 时间戳保存：

- regime 展示状态、pending state 和计数；
- CRISIS 退出计数；
- TRENDING active flag 和计数器；
- `confirmed_structure`、`pending_upgrade`、`pending_count`；
- stale/current 状态及 reason codes。

回放必须从充分历史重建同样状态，或恢复这一精确版本的持久状态。

## 5. 标准归一化

### 5.1 因果经验中位秩

需要相对变换时，使用包含当前有效观测的 504 个交易日因果经验中位秩：

```text
less  = count(window_value < current_value)
equal = count(window_value == current_value)
percentile = 100 * (less + 0.5 * equal) / 504
```

要求：

- 必须恰好有 504 个有效预期交易日观测；
- 相同值按上述公式处理；
- 不允许 expanding-window 捷径；
- 不允许隐藏的 winsorization、前向填充、中性填充或插值；
- 每个标准原始特征只归一化一次并被复用，不得对组合分数再次排名。

### 5.2 原始阈值

具有经济意义的阈值——VIX 水平、OAS、回撤、收益冲击、参与度和曲线比率——在用于否决、上限、CRISIS 或 TRENDING 时保留原始单位，不能只为形式统一而百分位化。

### 5.3 挑战方案

更长窗口的 robust-z 方法属于 EMPIRICAL。只有提升 feature-contract 版本、完整重校准、重建历史并通过一致性测试后才能取代中位秩，历史不得拼接。

## 6. 四大支柱

### 6.1 Direction structure

Direction 基于固定基准，采用确定、穷尽、首个匹配优先的结构分类。内部及输出字段名是 `direction_structure`，不是 `trend_state`。

v4.4 基准定义如下：

| Structure | 基准规则 | `direction_sign` |
|---|---|---:|
| `STRONG_BULL` | `close > EMA21 > SMA65 > SMA200` | +1 |
| `BULL` | `close > EMA21` 且 `EMA21 > SMA200`，排除前一匹配 | +1 |
| `BULL_PULLBACK` | `close <= EMA21`、`SMA65 > SMA200`、`close > SMA200` | +1 |
| `DAMAGED_BULL` | `close > SMA200`，排除之前匹配 | 0 |
| `BEAR` | `close <= SMA200` | -1 |

分类分割、首个匹配规则和 sign 映射为 CLOSED；21/65/200 的具体周期为 EMPIRICAL。

基础分数必须满足：

```text
STRONG_BULL > BULL >= BULL_PULLBACK > DAMAGED_BULL > BEAR
```

允许 BULL 与 BULL_PULLBACK 同分，因为结构本身仍有独立诊断价值；其他不等式必须严格成立。v4.4 的 `0.90/0.80/0.78/0.55/0.15` 仅为 EMPIRICAL 基准值。

Direction 不得包含回撤、Breadth、波动率、信用或轮动项。

### 6.2 Direction 确认

每个完全有效的 bar 都发布 `direction_structure_raw`。结构从最有利到最不利排序：

- raw 结构变差时立即确认；
- raw 结构改善时需要连续确认；
- raw 回到 confirmed、进一步恶化或切换为另一改善目标时，候选计数重置；
- 精确确认次数或按状态区分的次数属于 EMPIRICAL；
- v4.4 对称的 3/3 仅为比较基准。

首次完全有效分类之前 Direction 不可用。首次有效 raw 分类直接初始化 confirmed structure，不得用语义常数预置。已知的 `STRONG_BULL` 冷启动缺陷必须有专门回归向量。

标准 `direction_score` 不平滑。只用于图表的平滑序列必须另命名，且不得进入任何输出或逻辑。

### 6.3 TrendQuality

TrendQuality 衡量与方向无关的基准价格路径质量，分别发布两个分量：

- `linearity_pct`：滚动回归 R² 的因果中位秩；
- `path_efficiency_pct`：绝对净移动除以累计绝对移动，再取因果中位秩。

组合公式为：

```text
trend_quality = w_L * linearity_pct + w_E * path_efficiency_pct
w_L >= 0, w_E >= 0, w_L + w_E = 1
```

组合后不得再排名或平滑。`concentration_pct` 已移除，参与度专属于 Breadth。EMA 交叉次数是独立的挑战假设，不是 path efficiency 的另一实现。

回归域、周期、零移动处理、权重、Direction 调整系数及全部 TRENDING 阈值均为 EMPIRICAL。v4.4 三项混合和 `74.3` 阈值只属于旧版基准。

### 6.4 Breadth

Breadth 独立于市值加权 Direction，衡量市场参与度。每个输出都必须明确生产 source tier，层级历史不得自动拼接。

SMA50/SMA200 参与度混合及支柱权重属于 EMPIRICAL。必需覆盖不足时 Breadth 不可用，不得中性化。

### 6.5 Risk Appetite

Risk Appetite 只衡量信用与已实现的相对轮动，不包含 price damage、利率、曲线、宏观或基准绝对动量。

必须发布：

- 标准信用 level 和 change 分量；
- QQQ/SPY 总回报相对表现形成的 `growth_rotation_pct`；
- IWM/SPY 总回报相对表现形成的 `small_cap_rotation_pct`。

即使市场整体下跌，相对轮动依然有效，因为它衡量独立于绝对方向的已实现偏好。每个轮动原始特征只接受一次 504 日因果中位秩。不得根据基准收益进行 gate 或符号反转。

信用和轮动通过有界凸组合合成：

```text
risk_appetite_score = Σ(w_j * component_j)
w_j >= 0, Σw_j = 1
```

实证判断可以将某生产权重设为零，但仍发布其诊断。标准架构不允许加法裁剪调整、平滑、winsorization、中性填充或 QQQ/IWM 绝对动量。周期、变换、信用源/构造、权重和分量保留均为 EMPIRICAL。

### 6.6 Stability

Stability 是四个分别发布域的 supportive-positive 有界凸组合：

1. `implied_vol_stability`：原始 VIX 水平的单调递减变换；
2. `vol_curve_stability`：VIX9D/VIX 的单调递减变换；
3. `realized_vol_stability`：基准已实现波动率的单调递减变换；
4. `price_stability`：adverse-positive 标准 `price_damage` 的支持度变换。

```text
stability_score = Σ(w_k * stability_domain_k)
w_k >= 0, Σw_k = 1
```

标准 `price_damage` 只计算一次，可由 Stability、CRISIS、TRENDING 和诊断共同消费；Stability 不得私自重算。

VIX 相对均值、带符号 VIX ROC、VIX9D 绝对水平及 VIX3M/VIX 仅是挑战者/诊断。VIX 下跌绝不能导致 Stability 下降；旧版 `abs(VIX change)` 极性错误。禁止平滑、中性后备、过期前向填充和二次反转。

变换、周期、已实现波动率估计器、price-damage 构造、权重和挑战者保留均为 EMPIRICAL。

## 7. Condition、否决与上限

### 7.1 加权度量

```text
condition_pre_cap = Σ(weight_i * pillar_i)
weight_i >= 0
Σweight_i = 1
```

支柱权重属于 EMPIRICAL。结果只能为防止浮点误差而裁剪到 `[0,1]`。每个支柱贡献必须单独发布。

### 7.2 硬否决（Hard veto）

硬否决是由已声明原始域触发、无记忆的当前环境安全电路。有效否决立即令：

```text
condition_score = 0
state 至少被强制为 RISK_OFF
```

具体域和阈值属于 EMPIRICAL。缺失数据既不触发也不解除否决，而是使 Condition 不可用。

### 7.3 条件软上限（Soft cap）

生产默认不启用软上限；是否采用属于 EMPIRICAL。任何启用的 cap 必须：

- 使用已声明原始域或标准原始特征，不得使用聚合 Condition 或支柱；
- 是 `[0,1]` 内连续、单调的上界，值 `1` 表示不活跃；
- 不包含记忆或滞后；
- 发布 source value、threshold、mapped bound、active flag、binding identifier。

```text
condition_score = min(condition_pre_cap, all_active_caps)
```

硬否决优先。最小值组合确定、与顺序无关，也避免乘法复合；并列约束时发布全部 binder。若实证无法证明 cap 在权重、否决和 CRISIS 之外具有稳定的增量安全价值，则保持无 cap。

### 7.4 三层聚合逻辑：常态证据、安全底线、急性危机

Condition 相关逻辑分成三层，是为了避免让一种数学工具承担所有职责：

#### 第一层：加权和表达“常态下的综合证据”

凸组合允许一个较弱支柱被其他较强支柱部分抵消，适合描述正常市场中的权衡。例如 Breadth 略弱但信用、波动和趋势都健康时，综合环境仍可能较有利。

#### 第二层：veto/cap 表达“不可被平均掉的风险”

某些危险达到极端值后，不应因为其他三个支柱良好而被平均掉。hard veto 用于必须立即阻断的危险；soft cap 用于“可以继续给分，但最高不能超过某水平”的连续限制。

举例而言，若四支柱权重相等，分数为：

```text
Direction = 0.90
Breadth = 0.85
Risk Appetite = 0.80
Stability = 0.25
condition_pre_cap = (0.90 + 0.85 + 0.80 + 0.25) / 4 = 0.70
```

单纯平均会给出 0.70。但如果 Stability 的低值来自已达到安全阈值的原始急性波动压力，那么 hard veto 可以把最终 Condition 立即置零。这里 veto 不是第五个支柱，而是对平均模型失效模式的明确保护。

#### 第三层：CRISIS 要求跨域佐证

单个极端信号可能来自数据噪声、短暂事件或某一市场局部异常。因此 hard veto 足以强制 `RISK_OFF`，但不足以单独宣布 `CRISIS`。CRISIS 要求至少两个互不嵌套的压力域同 bar 确认，使“危机”标签具有更高特异性。

三层之间的职责可以写成：

```text
weighted Condition：总体环境有多支持？
veto / cap：是否存在不能被平均掉的底线约束？
CRISIS 2-of-4：急性风险是否得到跨域佐证？
```

### 7.5 为什么 soft caps 默认关闭

权重、hard veto 和 CRISIS 本身已经能表达大部分关系。额外 cap 很容易重复惩罚同一风险，造成模型过度保守和解释混乱。因此 cap 不是“越多越安全”，而必须证明它在已有结构之外提供稳定的样本外增量价值。

## 8. 状态体系与普通滞后

| State | 含义 |
|---|---|
| `CRISIS` | 多个独立域相互佐证的急性压力 |
| `RISK_OFF` | 环境不利或被否决，但没有 CRISIS 佐证 |
| `NEUTRAL` | 混合或中间环境 |
| `RISK_ON` | 广泛有利的环境 |
| `TRENDING` | 持续且异常干净的多头趋势 |

每次只能输出一个状态；Direction 与状态正交。

普通状态转换采用非对称滞后：降级快于升级。精确边界、buffer 和确认次数均为 EMPIRICAL。`decision_margin` 只用于诊断，绝不改变计数器或标签。硬否决绕过普通降级延迟。

### 8.1 为什么降级快、升级慢

市场风险具有非对称成本：风险恶化时反应过慢可能造成较大损失，而环境改善时晚确认几天通常主要是机会成本。因此状态机采用：

```text
不利变化 → 较少确认或立即生效
有利变化 → 更多连续确认
```

这不是偷偷调整 Condition，而只是稳定离散标签。Condition 每日仍忠实反映当前有效输入。

### 8.2 Hysteresis 与 buffer 分别解决什么

- **边界 buffer** 防止分数在阈值附近的小幅噪声立即反转状态；
- **连续确认计数** 要求候选状态持续存在，而不是单日偶然穿越；
- **pending state** 记录正在确认哪个目标；目标改变时必须重置，避免把不同方向的零散天数错误累加。

因此状态机的记忆是有限、显式、可回放的，不是难以审计的隐性平滑。

### 8.3 State 与 Direction 冲突不是错误

以下组合都可能合理存在：

- `direction_sign = +1` 且 `state = RISK_OFF`：价格尚未跌破长期结构，但内部参与、信用和波动已恶化；
- `direction_sign = -1` 且 `impulse_score > 0`：仍是熊市结构，但环境正从极差水平改善；
- `direction_sign = +1` 且 `state = NEUTRAL`：趋势向上，但其他证据混合；
- `state = TRENDING`：不仅方向为正，还必须满足路径质量、损伤、风险偏好、稳定性和持续性要求。

如果系统强迫这些输出始终同向，就会丢失最有价值的早期分歧信息。

## 9. CRISIS

### 9.1 四个独立域

CRISIS 使用四个非嵌套原始域：

1. 波动率/期限结构压力；
2. 标准信用压力；
3. 标准 price damage；
4. 市场参与度崩塌。

“独立”指任何一个确认信号都不是另一个的代数输入；经济相关性是正常现象。Direction、Condition 和聚合支柱不计作确认域。

### 9.2 进入与诊断

同一 bar 上两个有效域活跃，立即进入 CRISIS，不等待普通降级确认；至少必须有两个有效域。

硬否决但确认不足两个域时，只强制 RISK_OFF：

- 0 个域：`uncorroborated_veto = true`，`crisis_watch = false`；
- 1 个域：`uncorroborated_veto = true`，`crisis_watch = true`。

必须发布每域 valid/active flag、coverage、计数、reason code 和进入/退出计数器。缺失/过期意味着不可用，既不是平静也不是压力。

### 9.3 退出

以下条件必须连续五个有效 bar 同时成立才退出：

- 所有硬否决已解除；
- 活跃 CRISIS 域少于两个；
- Condition 高于 NEUTRAL 进入边界加 buffer。

重新出现双域确认时退出计数归零。

### 9.4 为什么进入立即、退出需连续五日

CRISIS 的进入证据已经要求两个独立域同时确认，因此没有必要再等待普通状态机；延迟可能掩盖急性风险。退出则不同：危机期间经常出现短暂反弹，单日恢复不足以证明压力解除，所以要求 veto 全清、确认域少于两个且 Condition 恢复到 NEUTRAL 边界以上，并连续保持五个有效 bar。

这种“不对称”表达的是风险管理逻辑，而不是预测市场一定继续下跌。

### 9.5 不设交易所停牌覆盖

交易所停牌属于 OUT_OF_SCOPE 的运营事件。缺失数据只会造成 Condition 不可用和 stale state，绝不自动产生 CRISIS。未来执行控制 schema 可以依权威停牌源阻止订单，但不得覆盖度量输出和历史。

## 10. TRENDING

TRENDING 是第五个互斥状态，不是徽章、入场信号或杠杆机制。资格必须同时要求：

- 看多的 `direction_structure`；
- 足够高的 TrendQuality；
- 较浅的标准 price damage；
- Risk Appetite 与 Stability 均高于 veto floor；
- 满足持续性状态规则。

资格、否决、进入和退出阈值/计数均为 EMPIRICAL。旧版 `74.3` 不得通过缩放直接继承。

TRENDING 激活时：

```text
state = TRENDING
condition_score <= 1.0
leverage_bonus = 0
```

## 11. Impulse

Impulse 描述最终、已经过否决和上限处理的 `condition_score` 变化，计算位置在分类状态滞后之前。

发布 fast、slow 两个端点变化，以及 `[-1,1]` 内的聚合 `impulse_score`。一般形式为：

```text
Δ_h = condition_score_t - condition_score_(t-h)
scaled_h = causal_zero_anchored_scale(Δ_h)
impulse_score = odd_squash(w_fast * scaled_fast + w_slow * scaled_slow)
w_fast >= 0, w_slow >= 0, w_fast + w_slow = 1
```

必须满足：

- Condition 改善为正、恶化为负、不变严格等于零；
- 对每个有效周期，非零时 `sign(impulse_h) = sign(condition_t - condition_t-h)`；
- 缩放必须因果且以零为锚，不得以滚动均值重新居中；
- 聚合变换必须连续、奇对称、单调、保零且对称有界；
- fast/slow 权重非负且和为一；
- 最多应用一个已声明的奇函数压缩变换；
- 端点缺失/过期，或周期内部所需交易日无效时，该周期及聚合值不可用；
- Impulse 不得反馈进 Condition、cap、veto、计数器或 state。

为便于归因，另行发布 pre-cap changes、pillar impulses 和 binding cap/veto changes，但它们不能取代 headline Condition Impulse。

周期、尺度估计器/窗口/下限、权重和变换均为 EMPIRICAL。v4.4 的 5/20、0.6/0.4、rolling z-score 与 tanh 只作旧版基准。

## 12. Confidence 诊断

不得发布单一聚合 confidence 标量，只发布四项诊断：

- `pillar_agreement`：同极性支柱的离散程度；分歧增加不得使它改善。
- `data_completeness`：可选/层级数据的覆盖与新鲜度；恢复数据不得使它下降。必需数据失败则直接令 Condition 不可用。
- `decision_margin`：距离适用决策边界（包括 TRENDING）的距离；不驱动状态转换。
- `temporal_stability`：近期 Condition 噪声和标签脆弱度。

具体公式属于 EMPIRICAL。Confidence 不得重缩放 Condition 或改变 state。

## 13. 输出 Schema

### 13.1 核心字段

- `schema_version`、`feature_contract_version`、`as_of`；
- `condition_pre_cap`、`condition_score`、派生 `condition_pct`；
- `state`、`state_is_current`、`direction_sign`；
- `direction_score`、`breadth_score`、`risk_appetite_score`、`stability_score`；
- `direction_structure_raw`、`direction_structure`；
- `linearity_pct`、`path_efficiency_pct`、`trend_quality`；
- `growth_rotation_pct`、`small_cap_rotation_pct` 及信用分量；
- 四个 Stability 域分数及标准 `price_damage`；
- `impulse_fast`、`impulse_slow`、`impulse_score`；
- 四项 Confidence 诊断。

### 13.2 可解释性与状态字段

必须发布全部标准 raw/normalized 特征、贡献值、活跃 veto/cap、binding identifier、source tier、coverage、freshness、warm-up、polarity、reason code、Direction pending state、普通 regime pending state、CRISIS counters 及 TRENDING counters。

### 13.3 Nullability

机器可读 manifest 必须为每个字段定义 type、unit、range、polarity、nullability、status、source contract 和 consumers。不可用 Condition 必须为 null/NA 并给出原因，不能写成数值零。

### 13.4 已移除字段

v5.1 不输出 `trend_state` 别名，只使用 `direction_structure`；也不输出宏观面板、交易所停牌覆盖、政策/路由/仓位字段或交易动作标记。

## 14. 验证体系

### 14.1 Golden vectors

不可变测试向量必须覆盖：

- 归一化并列值、精确预热、缺失交易日、过期数据；
- 每个 Direction structure 及边界；
- 每种 raw structure 的冷启动，尤其预热不足后首次有效值不是 STRONG_BULL；
- 立即降级、候选升级、振荡、目标变化、非相邻跳转和重启一致性；
- TrendQuality 分量极性和去重；
- Breadth source tier 和禁止拼接；
- 上涨与下跌市场中的 Risk Appetite 相对轮动；
- Stability 各域独立扰动，包括 VIX 下跌绝不降低 Stability；
- hard veto、可选 cap、并列 binder 和无 cap 基线；
- 每个 CRISIS 单域及双域、缺失域、恢复与复发；
- TRENDING 进入、持续、否决和退出；
- Impulse 的零、等幅反向路径、单调路径、veto/cap 变化、饱和、缺口和符号一致性；
- Confidence 单调性；
- 度量/政策边界不变量。

### 14.2 实证方法

使用预注册的小型 challenger 集合、锚定 walk-forward、未触碰 holdout、危机/趋势子样本、bootstrap 不确定性、敏感度曲面和消融实验。按适用情况报告尾部损失、错误限制、换手、停留/转换行为、校准稳定性、冗余和机会成本。不得选择大网格样本内最优值。

### 14.3 Python/Pine 一致性

Python 是参考实现。Pine 必须在声明容差内重现所有可实现字段，否则须标记 `proxy-only`。布尔值、标签、计数器、source tier 和 reason code 必须精确一致；浮点容差按字段定义，属于 EMPIRICAL。

### 14.4 层级边界测试

度量引擎必须能在没有策略或组合配置时独立运行。改变路由规则后，全部度量输出必须逐字节一致。政策输入缺失不得影响 Condition 可用性。度量可视化不得出现交易动作动词。下游政策状态不得影响回放的度量输出。

## 15. 迁移顺序

1. 冻结 v4.4、v5.0 artifacts 并保留历史。
2. 并行发布 v5.1 schema 与 feature-contract namespaces。
3. 将 `trend_state` 改名为 `direction_structure`，不提供静默别名。
4. 从 Direction 移除 RSP，重建 TrendQuality，并重新校准依赖的 Direction/TRENDING 参数。
5. 按凸组合拓扑重建 Risk Appetite 和 Stability。
6. 按依赖顺序重新推导支柱权重、veto、状态边界、CRISIS 和 TRENDING。
7. 启用任何 cap 前，先验证无 cap 基线。
8. 校准 Impulse 和 Confidence 诊断。
9. 建立 golden vectors 和 Python reference，并对 Pine 做一致性测试。
10. 并行 shadow-run v4.4/v5.0/v5.1，解释全部差异。
11. 连续仓位消费者通过独立版本化 policy adapter 迁移；度量层内绝不把 Condition 别名成旧字段。
12. 只有 acceptance criteria 全部通过后才能切换。

历史字段不得重写。旧 `market_permission` 不得别名为新 Condition。

## 16. CLOSED 清单

1. 四个 supportive-positive 支柱；方向与支持度正交。
2. 五个互斥状态；TRENDING 互斥、有状态、只适用于多头且不增加杠杆。
3. Condition 不含 MemoryDiscount、仓位政策或隐藏事件记忆。
4. Direction structure 分割、sign 映射、偏序约束和破坏性改名。
5. Direction 升级需确认、降级立即生效，只能由有效数据初始化。
6. TrendQuality 只含价格线性度和路径效率；移除 concentration/RSP。
7. Breadth 数据层级固定，十一行业诊断历史不自动拼接。
8. Risk Appetite 由信用和独立有效的 SPY 相对轮动凸组合形成。
9. Stability 为四域凸组合；VIX3M 仅为 challenger；price damage 只算一次。
10. 标准相对归一化为因果 504 日中位秩。
11. Hard veto 是当前特征的即时约束。
12. Soft-cap 接口基于原始域、连续、无记忆、可观测、以 min 合成；默认无 cap。
13. CRISIS 使用四个非嵌套原始域的 2-of-4 规则，即时进入、连续五日确认清除后退出。
14. Impulse 跟踪最终 Condition，保证符号一致、零锚定且无反馈。
15. Confidence 为四项诊断，不设聚合标量。
16. 必需数据缺失时 fail closed；未知不等于 CRISIS。
17. 从度量层移除交易所停牌覆盖。
18. 从 regime schema 与生命周期移除宏观面板。
19. 禁止度量到路由/动作的别名；接口单向且不可变。
20. v5.1 是破坏性 schema/feature-contract 版本，采用并行迁移。

## 17. EMPIRICAL 清单

1. Direction 均线周期和基础分数。
2. Direction 升级确认次数。
3. TrendQuality 回归域、周期、零处理、权重、Direction 调整和 challenger 选择。
4. Breadth SMA50/SMA200 混合及支柱权重。
5. 标准信用源/构造、ETF 代理选择和久期中性化。
6. Risk Appetite 周期、变换、权重和分量保留。
7. Stability 变换、周期、已实现波动率估计器、price damage、权重和 challenger 保留。
8. 四个支柱权重与贡献变换。
9. Hard-veto 域和阈值。
10. 是否采用 soft cap，以及每个 cap 的域、阈值和曲线。
11. 状态边界、buffer 和普通滞后次数。
12. 四个 CRISIS 公式与阈值。
13. TRENDING 资格、否决、进入和退出阈值/计数。
14. Impulse 周期、尺度估计器、权重和变换。
15. Confidence 公式与校准；未来若增加聚合值必须有新决策/版本。
16. 下游 RecoveryThrottle 对比无 throttle 和旧 MemoryDiscount。
17. 下游无杠杆、旧 `+0.05` 与波动率目标杠杆的比较。
18. 504-midrank 与更长窗口 robust-z challenger。
19. 各数据源 freshness/as-of 容差。
20. Python/Pine 数值与数据一致性容差。

## 18. OUT_OF_SCOPE 清单

- 策略选择、路由、适配度和动作标签；
- 仓位规模和组合构建；
- 杠杆授权及是否采用 RecoveryThrottle；
- 执行、交易成本、融资和券商集成；
- 交易所停牌订单控制；
- 宏观背景产品字段及宏观预测；
- 日内 regime 计算，除非独立版本化；
- 除允许的独立 adapter 边界外的兼容政策设计。

## 19. 继承待审项目处理结果

v5.0 §19 的十项内容均已确定处理方式：

| 项目 | v5.1 处理结果 |
|---|---|
| Direction MA 状态/基础分表 | 结构 CLOSED；周期/分数 EMPIRICAL |
| TrendQuality 构造 | 双分量拓扑 CLOSED；公式/权重 EMPIRICAL |
| Direction 确认 bars | 非对称实现 CLOSED；次数 EMPIRICAL |
| Risk Appetite 相对强弱 | 相对/凸组合拓扑 CLOSED；公式/权重 EMPIRICAL |
| Stability 与 VIX3M | 四域拓扑 CLOSED；公式/权重 EMPIRICAL；VIX3M 仅 challenger |
| Soft caps | 条件接口 CLOSED；采用与参数 EMPIRICAL；默认无 cap |
| Impulse 5/20 tanh | 不变量/拓扑 CLOSED；全部常数/变换 EMPIRICAL |
| 交易所停牌覆盖 | 已移除；OUT_OF_SCOPE |
| 宏观背景面板 | 已移除；OUT_OF_SCOPE |
| 度量与路由耦合 | 禁止；routing/policy OUT_OF_SCOPE |

v5.1 已没有 `INHERITED_PENDING_REVIEW` 项目。

## 20. 验收标准

只有满足以下条件，v5.1 才达到“可以实现/投产”的标准：

- 机器可读 manifest 已存在且与本文一致；
- 每个必需 source contract 已固定；
- 阻塞发布的 EMPIRICAL 任务全部完成；
- 所有 golden-vector 和边界不变量测试通过；
- Python reference 输出可复现；
- Pine 已通过一致性测试，或明确标记为 proxy-only；
- v4.4/v5.0/v5.1 shadow 差异全部得到解释；
- measurement 中没有泄漏 policy、routing、macro 或 operational 字段；
- 没有把未解决常数描述成规范值。

在此之前，v5.1 是权威架构基线，而不是生产交易信号。

## 附录 A：关键公式速查

```text
# 因果 504 日经验中位秩
percentile = 100 * (count(x < x_t) + 0.5 * count(x == x_t)) / 504

# 支柱凸组合
condition_pre_cap = Σ(w_i * pillar_i)
w_i >= 0, Σw_i = 1

# Soft cap（如实证采用）
condition_score = min(condition_pre_cap, all_active_caps)

# Hard veto
valid_hard_veto => condition_score = 0 and state_at_least = RISK_OFF

# CRISIS
crisis_entry = count(valid_active_independent_domains) >= 2
crisis_exit = 5 consecutive valid bars satisfying all exit conditions

# TrendQuality 概念公式
path_efficiency = abs(price_t - price_(t-h)) / Σ abs(price_k - price_(k-1))
trend_quality = w_L * linearity_pct + w_E * path_efficiency_pct

# Condition Impulse 概念公式
Δ_h = condition_score_t - condition_score_(t-h)
impulse_score = odd_squash(w_fast * scaled_fast + w_slow * scaled_slow)
```

这些公式中凡未由 CLOSED 不变量固定的窗口、阈值、权重、尺度和变换，均保持 EMPIRICAL 状态，必须通过预注册的样本外实证流程确定。

## 附录 B：从输入到输出的逻辑演算示例

以下数字仅用于解释推理路径，不是 v5.1 的校准参数或生产阈值。

### B.1 指数上涨，但内部环境恶化

假设：

```text
direction_structure = BULL
direction_score = 0.80
breadth_score = 0.30
risk_appetite_score = 0.35
stability_score = 0.40
```

逻辑解释：

1. 基准价格仍处于多头结构，所以 `direction_sign = +1`；
2. 但参与度弱，说明上涨集中于少数成分；
3. 信用和相对轮动弱，说明风险承担意愿不足；
4. 波动/损伤环境也不稳定；
5. 因此 Condition 会显著低于单看指数趋势所得的印象；
6. 若没有双域急性确认，状态更可能落在 `NEUTRAL` 或 `RISK_OFF`，而不是 `CRISIS`；
7. 这组分歧是预警信息，不应通过强迫 Direction 与 State 一致而删除。

### B.2 单一波动冲击

假设 VIX/期限结构达到 hard-veto 阈值，但信用、price damage 和 Breadth collapse 均未确认：

```text
hard_veto = true
active_crisis_domains = 1
condition_score = 0
state = RISK_OFF
uncorroborated_veto = true
crisis_watch = true
```

逻辑是：立即尊重危险，不让其他高分把它平均掉；但因为只有一个独立域，证据还不足以使用 `CRISIS` 标签。

### B.3 多域急性压力

假设波动压力和信用压力在同一有效 bar 同时活跃：

```text
volatility_domain.active = true
credit_domain.active = true
active_crisis_domains = 2
state = CRISIS
```

此时双域佐证满足，立即进入 CRISIS。即使 Direction 因均线滞后仍是 `BULL`，也不阻止危机状态；方向与急性压力本来就是不同维度。

### B.4 熊市中的改善

假设价格仍低于 SMA200，因此：

```text
direction_structure = BEAR
direction_sign = -1
```

但信用利差收窄、波动下降、Breadth 回升，使最终 Condition 从 0.20 升到 0.35：

```text
ΔCondition > 0
impulse_score > 0
```

这不表示系统发出买入信号，只表示“熊市结构仍在，但环境正在改善”。下游策略是否行动，取决于独立政策、时间尺度、成本和授权。

### B.5 数据中断

假设必需的 Breadth 数据过期：

```text
breadth_score = null
condition_score = null
state = previous_state
state_is_current = false
reason_code = required_breadth_stale
```

系统不得把 Breadth 填成 0.5，也不得把 Condition 写成 0，更不能因为“看不到数据”而宣布 CRISIS。未知必须保持未知。

### B.6 干净多头趋势与 TRENDING

仅有 `STRONG_BULL` 不足以进入 TRENDING。还要逐层检查：

```text
bullish direction_structure
AND trend_quality >= empirical qualification threshold
AND price_damage <= empirical maximum
AND risk_appetite_score >= empirical veto floor
AND stability_score >= empirical veto floor
AND persistence rules satisfied
```

这样可避免把由少数股票推动、路径剧烈、风险偏好脆弱的上涨误标为“干净趋势”。即使成功进入 TRENDING，系统也不提高 Condition 上限、不添加杠杆奖励。

## 附录 C：阅读输出时的推荐顺序

面对一条 v5.1 输出，建议按以下顺序解释：

1. 先看 `as_of`、freshness、coverage、reason codes，确认数据可用；
2. 看 `direction_structure` 与 `direction_sign`，理解价格方向；
3. 分别看四支柱和贡献，找出支持与拖累来源；
4. 比较 `condition_pre_cap` 与 `condition_score`，检查 veto/cap 是否改变结果；
5. 查看 CRISIS domains、普通状态 pending counters 和 TRENDING counters，解释状态为何形成；
6. 查看 Impulse，判断环境是在改善还是恶化；
7. 最后看四项 Confidence 诊断，理解分歧、完整性、边界距离和时间稳定性；
8. 如需交易动作，再把这些不可变事实交给独立政策层，而不是从状态名直接推导仓位。

这一阅读顺序体现了整个设计的哲学：**先验证事实，再分解证据；先度量环境，再处理安全约束；最后才由独立政策决定行动。**

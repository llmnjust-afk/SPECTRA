# PrivFuse 修订记录 / 审稿意见答复（ICDCS 2026）

产物：`main.pdf`，**11 页**（含图表、附录与参考文献），`latexmk` 编译通过，
0 处 Overfull box，0 处未定义引用/交叉引用。参考文献 **32 条**，全部被正文
引用，全部经 CrossRef 逐条核对（含作者全名、卷期页码）；`ref_verify` 抽检
7 条，0 条 UNVERIFIED，并据其回填修正了 IncShrink 与 Jung & Park 的作者字段。

---

## A. 修订清单

### 阻断性问题

**B1 页数超限** — 状态：**已修复**
- 文件：全部 `sections/*.tex`、`refs.bib`。
- 改动：正文由 9,923 词压缩至 9,185 词；删除 11 条"仅凑数"的参考文献
  （每条只支撑从句，删除后论证链不变）；同时删去重复句、合并同义从句、
  精简 related work 与 discussion。
- 依据：ICDCS 2026 硬性 11 页（含参考文献）。
- 验证：`pdfinfo main.pdf | grep Pages` → `11`；第 12 页不存在。

**B2 缺少分布式系统证据** — 状态：**部分修复（新增实测，但非多节点）**
- 文件：`privfuse/experiments/e13_settlement_scale.py`（新增）、
  `results/e13_disjoint.csv`、`results/e13_xproc.csv`、
  `results/e13_xproc_meta.json`、`sections/evaluation5.tex`、
  `sections/discussion.tex`、`docs/experiments.md`、`README.md`。
- 改动：新增 E13，两部分，3 次重复取中位数。
  (a) 进程内、不相交主体：4 线程下分片锁 91.5k ops/s vs 全局锁 25.2k
  （**3.6×**）；但单一热点主体上分片锁 21.4k vs 全局 26.5k（无收益），
  单线程还慢 28%（83.1k vs 116.4k）。
  (b) 跨进程 loopback TCP，服务端为真实 Coordinator，分片锁：1 客户端
  1,920 ops/s（p50 201 µs），4 客户端 2,424 ops/s（p50 283 µs、p99 16.1 ms）。
  论文据此重写了并发小节：删去原先"没有任何吞吐收益"的一刀切说法，改为
  "分片只在不相交主体上有收益、协调器进程在 ~2.4k ops/s 饱和"。
- 依据：原稿只有单进程合成吞吐，缺跨进程证据；这是报告的核心指控。
- 验证：实验脚本可复现（`python3 -m privfuse.experiments.e13_settlement_scale`），
  CSV 为原始逐次测量，正文数字与 CSV 逐一比对一致。
- 残余：仍是单机、loopback、无共识/无副本/无持久账本，论文中已明写
  "bounds the protocol, not a deployment"，未夸大。

**B3 可靠性（soundness）定义未覆盖节流路径** — 状态：**已修复**
- 文件：`sections/model.tex`、`sections/analysis.tex`。
- 改动：定义执行成本 `\cost_{\mathrm{exec}}(q)`（含 β 缩放的节流分支），
  可靠性命题的量化范围改为 `{admit, throttle}` 两个动作，而非仅 `admit`。
- 依据：原文按"准入即收费"陈述，但节流路径也消耗预算，命题在字面上不成立。
- 验证：命题与证明中出现的每个动作均已被覆盖；与实现
  （`privfuse/core`）的收费路径一致。

**B4 命题 2 证明不成立** — 状态：**已修复**
- 文件：`sections/analysis.tex`、`sections/design3.tex`。
- 改动：重写命题陈述与证明：在**每个可达状态**维持不变式
  `C_s + F_s ⪯ E_s`（已提交 + 在飞 ⪯ 估计上界），利用 `C_s` 单调不减、
  `F_s ⪰ 0`，逐一枚举 commit / release / 过期三类迁移，并显式声明
  原子性前提（预留与提交在同一临界区内完成）。命题 1 的证明补上
  环形覆盖前提 `⌈W/ℓ⌉+1`。
- 依据：原证明隐含"提交后释放预留"的次序未被论证，且未说明窗口覆盖。
- 验证：不变式与迁移枚举逐条对应代码中的三条路径；前提在正文与
  实现小节中一致陈述。

**B5 "1.69ε" 归属疑似错误** — 状态：**已修复（报告的前提本身不准确，故澄清而非改数）**
- 文件：`sections/evaluation2.tex`。
- 核查结果：重算 `results/e3_breaker.csv`，E3 在 cap = 1.0 时
  exact_blocking 的 `max_eps` 为 **1.691 / 1.694 / 1.692**（三个种子），
  即原文的 1.69 是 **E3 的真实值**，并非误引 E4；E4 在 k=60 时
  exact_blocking 恰好也是 1.698，两个实验在该点上数值重合，才导致歧义。
- 改动：保留数值，补上配置限定——"…on average, the worst reaching $1.69\eps$
  **at cap $1.0\eps$**"；并加一句说明 Fig. 2 在 k=60 处的 escaping ratio
  是**另一个量**（E4 的逃逸比），不可与 E3 的 max_eps 混读。
- 依据：报告要求"用核验后的值替换；若无法确立则删除"。值已由原始 CSV
  确立，故替换为带配置限定的准确表述，而不是删掉一个正确结果。
- 验证：`results/e3_breaker.csv` 与 `results/e4_attack.csv` 分别聚合，
  正文数字、表格、图三者一致。

**B6 相关工作缺失** — 状态：**已修复（Shuffler 条目经核查不存在，改引可核实的等价文献）**
- 文件：`sections/related.tex`、`sections/background.tex`、`refs.bib`。
- 改动：新增 7 条可核实文献（Dwork ICALP'06；Abadi CCS'16；
  Bittau SOSP'17；Johnson/Near/Song PVLDB'18；Wang SIGMOD'22；
  Jung & Park BigData'19；Cheu et al. EUROCRYPT'19），related work 重写为按
  **执行粒度、计量单位、信任模型、执行时机、事务保证** 五个维度逐项对比；
  删去"没有对应系统"的绝对化说法。
- **关于 Shuffler (SIGMOD 2018)**：报告点名要求，但在 CrossRef 标题检索
  （2017–2019）、DBLP、OpenAlex、Semantic Scholar 中均无此条；CrossRef 的
  `query.title=Shuffler` 仅返回 PEARC'19 的 HPC 框架、SecureComm 的侧信道
  工作与字典条目。据此判断该条为审稿报告中的失实引用，**未写入** `refs.bib`。
  其学术位置（匿名置换 / shuffler 模型）改由可核实的
  Cheu et al., EUROCRYPT 2019（DOI 10.1007/978-3-030-17653-2_13, pp. 375–403）
  承担，并在 Prochlo 一句后接续引用。
- 验证：每个 DOI 由 CrossRef API 返回的元数据核对；`ref_verify` 抽检
  7 条 → 0 UNVERIFIED；脚本核验正文 `\cite` 与 `refs.bib`：32 cited = 32 entries。

### 应修复问题（S 系列）

| 编号 | 状态 | 处理 |
|---|---|---|
| S1 统计不确定度 | 已修复 | 从 `e3_breaker.csv` 逐种子读取，正文补标准差段落：PrivFuse 可用率 SD 在 cap 0.5/0.75/1.0/1.5 上分别为 0.0014/0.0124/0.0025/0.0005；两个基线为精确计数器、确定性，唯一随种子变化的是 cap 1.0 的违规数 13/13/12。明确写出"零违规是观测到的，不是证明的"。 |
| S2 追加工作负载 | 部分修复 | 新增 E13（结算扩展性）；未引入真实 trace，理由与残余风险写在 C 节。 |
| S3 热点表 churn 敏感度 | 已修复 | 新增 E14：四个 epoch，每轮注入 0/100/400 个新的重负载主体（各 40 次查询），容量 256/32/1，三 seed、两个 cap。重 churn 使平均高估从 0.16 升到 0.28（cap 0.15）与 0.25 升到 0.65（cap 1.0），p99 由 1.7× 升至 2.5×、2.2× 升至 5.1×；紧 cap 下基础请求可用率降 4.5 个百分点。30 次运行 **零违规**、无一超 cap，因为被逐出主体由 sketch 上界重新播种；churn 下热表不再带来收益。 |
| S4 不相交主体吞吐 | 已修复 | 见 B2(a)，E13 直接测量。 |
| S5 E11 机制与指标说明 | 已修复 | 明确 E11 为计数查询、下游为高斯朴素贝叶斯、指标为 F1；补充"四次发布按基本组合拆分 ε，因此偏保守"。 |
| S6 图可读性/单位 | 已修复 | 按单栏宽度重绘 Fig. 3 与 Fig. 7（3.4 in 宽、上下双栏、6.5–7 pt 字号），图例由代码标识符（`audit_only` 等）改为可读名称（audit only / exact per-tenant / PrivFuse），纵轴统一为 realized ε / cap 与 µs/request。 |
| S7 匿名 artifact | 已修复（待作者上传） | 生成 `artifact/privfuse-artifact.zip`（0.81 MB）：库、实验驱动、全部 CSV/meta、图、论文源码、`ARTIFACT.md`，剔除 `.git`、PDF、缓存与凭据；解包后 `grep` 无任何作者/仓库/令牌标识，且 37 个测试在解包副本上全部通过。论文 implementation 节加一句 artifact 声明。**投稿系统里的实际上传需作者完成**，否则应删除该句。 |

### 行级修订（Phase D）

全部执行：Count-Min 更新方向由"never increases an estimate"改为
"never decreases"；删除 design2 重复句；修复 evaluation4 断裂从句
（699 / 5,088 = 13.7%，4.2 个百分点）；违规数区分"平均每种子"与"单次运行
整数"；合成人口规模表述统一为 "synthetic populations of up to 10^6"；
RDP 结论限定为"在本文评估的 order 网格上没有出现需要额外噪声的阶"；
E9 明写"单种子"；逃逸比给出有限轨迹定义；内存区分 sketch 状态与精确账本
状态；结论与摘要同步改写（"12.7 on average"、"estimator memory"）。

---

## B. 验证记录

| 检查 | 命令 | 结果 |
|---|---|---|
| 编译 | `latexmk -pdf -interaction=nonstopmode main.tex` | 成功，无错误 |
| 页数 | `pdfinfo main.pdf \| grep Pages` | **11** |
| 排版溢出 | `grep -c Overfull main.log` | 0 |
| 未定义引用 | `pdftotext main.pdf - \| grep -c "??"` | 0 |
| 引用一致性 | 脚本比对 `\cite{}` 与 `refs.bib` 键 | 32 = 32，missing 0，uncited 0 |
| 文献核验 | `ref_verify`（CrossRef + OpenAlex） | 7 条抽检，0 UNVERIFIED，字段回填后写入 |
| 单元测试 | `python3 -m pytest -q` | **40 passed**（新增滑窗基线 3 个用例） |
| 新实验 E13 | `python3 -m privfuse.experiments.e13_settlement_scale` | 6 组进程内 + 3 组跨进程，3 次重复，CSV 已落盘 |
| 新实验 E14 | `python3 -m privfuse.experiments.e14_churn` | 5 变体 × 3 seed + 3 变体 × 3 seed（cap 0.15），CSV 已落盘 |
| 新实验 E15 | `python3 -m privfuse.experiments.e15_replication` | 12 seed × 6 cap × 3 策略 = 216 次运行，输出原始行 + t 区间汇总 |
| 新实验 E16 | `python3 -m privfuse.experiments.e16_windowed` | 精确滑窗账本 vs PrivFuse vs 精确累积，2 cap × 3 seed × 4 策略 |
| 新实验 E17 | `python3 -m privfuse.experiments.e17_latency` | cProfile 分解 + 3 次服务的中间次 + 5 次重复排队模拟 |
| 新实验 E18 | `python3 -m privfuse.experiments.e18_adaptive_attack` | 闭环攻击者 3 策略 × 6 策略 × 3 seed（确定性，三 seed 相同） |
| 新实验 E19 | `python3 -m privfuse.experiments.e19_faults` | 事务每一步注入崩溃 + 两种重试时序 + 1/4 线程 × 3 崩溃率 |
| 匿名包 | 解包后 `pytest -q` + `grep` 标识符 | 37 passed，无标识符命中 |
| 表格核对 | 正文 Table I ↔ `e3_breaker.csv` | 可用率/违规数/max_eps 全部一致 |
| 图核对 | Fig. 2/3 ↔ `e4_attack.csv`、`e8_scale.csv` | 一致；图已重绘可读 |

失败的检查：无阻塞性失败。唯一反复出现的问题是 bash 默认 120 s 超时
截断长实验，已改为显式超时参数；E13 初版因 `mp.Queue` 传输 2500 个浮点
造成管道死锁，已改为只回传聚合分位数。

## C. 后续补充实验（第二轮）

**E15 十二 seed 复现。** 表 I 由 3 seed 改为 12 seed，给出 Student-t 95% 区间
与配对差值：cap 1.0 时 PrivFuse 0.934（CI ±0.002），比 exact blocking 少收
4.4±0.2 个百分点、比 static quota 少 2.2±0.2，而两者每轮违规 12.7±0.3 次对 0。
cap 2.0 处 PrivFuse 达到满可用率且零违规，基线仍违规 12 次。原稿"1.5ε 及以上
没有差距"的说法在 1.5ε 处不成立（3.4 个百分点），已改正。

**E16 精确滑窗账本（重要更正）。** 原稿 §VII-E 写"精确账本无法表达窗口 SLO"，
这是错的：实现了 `ExactWindowedPolicy`（每主体事件日志 + 滑动窗口）后，它在
600 s 窗口、0.5ε cap 下可用率 1.000，内存 1.08 MB，但 1,500 个主体中有 6 个
在**生命周期**口径上超额——窗口约束不等于生命周期约束。同时精确累积账本在
1,500 主体处与 PrivFuse 可用率相差不到 1 个点（0.898 vs 0.906；0.713 vs 0.721），
内存 0.38 MB vs 5.0 MB。因此论文现在明确写：PrivFuse 的立足点是 10^6 规模下的
内存墙，而不是"窗口无法精确实现"或"小规模下精确账本慢"。原句已删除，
并补充"19 µs 与 228 µs 不可直接比较（前者不含 breaker/coordinator/window）"。

**E17 延迟分解与负载。** 全路径中位数 74 µs、均值 223 µs、p99 5.6 ms；profiling
显示 46% 在 sketch 与代价代数、14% 在 ledger、12% 在 controller、7% 在账本。
尾部来自单一函数：每 64 次准入扫描一遍热表的租户压力刷新。关掉它，均值降到
108 µs、p99 降到 0.47 ms——即该扫描吃掉约一半吞吐和全部尾延迟。单服务器排队
模型：ρ=0.5 时中位数 0.17 ms 但 p99 107 ms（因为一次 5.6 ms 的服务会堵住后面
所有人），ρ=0.8 时中位数已 5.2 ms；平均 50%、峰值 5 倍容量的突发模式中位数
0.93 s。结论写进正文：准入路径必须按峰值配置，不能按均值。

这条同时暴露了一个设计缺陷：刷新是 O(热表) 的同步扫描。论文如实报告，并把
"摊销该扫描"列为第一项工程改进；我们没有在冻结数据后改默认值，所以其它实验
的数字与该配置一致。

**E18 闭环攻击者。** E4/E15 都是开环攻击（固定 k 个身份的固定切分）。把准入决策
反馈给攻击者后：probe-and-backoff 把 PrivFuse 的**组合**损失从 0.80 抬到 0.85 个
cap（软阈值 0.8、硬帽 1.0，仍未越界），同时把 static quota 从 1.30 抬到 1.74、
exact blocking 从 1.69 抬到 1.76——因为更小的请求更便宜，能从"整块被拒"的配额下
挤过去；而 keyed 账户照样记账。40 身份 × 3 平台的分散对所有策略都没有增益：
身份不是 key，分散就没有意义。

一个必须记住的口径：这里用的是**组合后**的 ε（10 个 0.3 的分片组合成 0.80，不是
3.0）。直接把边际 ε 相加会高估损失，这是我第一版实现犯的错——当时 PrivFuse 显示
2.47，看着像安全性质被攻破，实际上是度量错了。E4 图的 0.82 与这里的 0.80 是同一
口径。

**E19 结算故障注入。** 把崩溃点放在事务的每一个步骤上，直接从账本读不变量（而不是
从调用方的计数器）：所有行都满足"无已提交记账则不交付答案"、无重复计费、在途额度
不越帽。TTL 内重试复用同一预约、只计一次费；TTL 后重试被拒、额度归还；commit 后
崩溃则扣费但不交付（安全方向）。代价就是崩溃率本身（5% 时 200 个请求里交付 188），
外加 800 个请求里 1 个被挂起的预约挡住。对照组：三个平台各用本地账本，同一主体花掉
3.0 个 cap——共享协调者是跨平台帽成立的唯一原因。

**图表密度（第三轮之后的追加修改）。** 初稿 11 页只有 1 张表 + 2 张图，19 个实验
的绝大多数数据只以正文数字出现。改为 6 个浮动物：图 1 架构、图 2 状态大小、图 3
延迟（新增，双面板：服务时间分位数 + 用实测服务时间驱动的 FCFS 排队）、图 4 攻击
逃逸比、表 I cap 扫描、表 II 故障注入矩阵（新增）。图 2 去掉"每请求代价"面板（数字
留在正文），腾出的高度给新图表；正文在方法、相关工作、讨论、结算四节压缩约 300 词，
仍守 11 页。图 3 与表 II 的数字全部来自 `results/e17_latency.csv`、`e19_faults.csv`，
由 `figures.py` 生成，没有手填。

第三批再补一张双面板图（图 5）：(a) 可用率随软阈值 α 的变化，每点标注实测软违约
率，虚线是默认 p=1% 开始成立的边界；(b) churn 队列（0/100/400）在两个 cap 下的平均
高估。正文相应把 SLO 前沿段、敏感性列表、zCDP 小节、效用小节压缩约 150 词。现在
全篇 7 个浮动物（5 图 + 2 表），仍是 11 页、0 Overfull。

注意图 5(b) 的 0.15ε 只有 0 和 400 两个队列（100 队列只跑了 1.0ε），图注已注明，
不是漏点。

同时修正 §VI 的实现规模：51 个模块、约 5,700 行、44 个测试（原文写 44 模块、
37 测试、4,200 行）。

## D. 未能完成、需外部条件或作者决策

1. **多节点/拜占庭/多副本一致性**：需真实集群与共识实现，E13 仅覆盖单机
   双进程 loopback。论文已把结论限定在协议层。
2. **每主体标志位的独立内存计量**：未与 sketch 状态分开计量。
3. **真实数据 trace**：全部为合成人群，E14 的 churn 也是合成模式。
4. **匿名 artifact 的实际上传**：包已就绪，需作者在投稿系统附加。
5. **Shuffler (SIGMOD 2018)**：多方检索不存在，已用 EUROCRYPT'19 替代。
6. **E16 的滑窗基线是自研实现**，未与公开系统对拍；内存口径为每事件 256 B
   的估算，不是实测对象大小。
7. **E17 的排队模型是模型**：单服务器、FCFS、服务时间取自实测但到达过程是
   合成的，不含网络与客户端时间；p99 已用 5 次重复的中位数稳定，但仍随机器负载
   波动（同一场景两次独立运行可差 20%）。
8. **租户压力刷新未摊销**：这是 E17 找到的真实瓶颈，修它会改变准入决策、需要
   重跑全部实验，故留作 future work。
9. **E19 的崩溃是进程内异常，不是真断电**：没有 fsync、没有重启恢复，因为参考实现
   的账本是内存态（论文 §III 明确把持久化交给 chaincode）。所以 E19 验证的是协议
   语义，不是持久性；真持久性需要 Fabric 适配器，而它仍是 stub。
10. **E18 的攻击者仍是被设计的**：三种策略是手工编排的（退避、退休、分散），不是
   学习到的策略；更强的对手（估计刷新周期后对齐突刺，或利用 degrade 的 0.5 折
   扣做梯度搜索）尚未测试。E18 已显示 degrade 会把软预算的 20% 余量吃到 15%。

## E. 最终科学评估

修订后，定义—命题—证明—实现—实验这条链现在自洽：B3 与 B4 是真实的
技术缺陷，已修好而不是用措辞掩盖；B5 经原始数据核查证明原句正确，
只补了配置限定；B2 用新测量替换了原先的定性断言，并且敢于报告
"分片对单一热点主体无收益、协调器进程 ~2.4k ops/s 饱和"这一负面结果。

对 ICDCS 审稿而言仍有两个结构性风险：(i) 系统贡献的分布式成分仍然薄——
一个单协调器原型、无共识、无副本，E13 恰恰量化了这一上限；(ii) 评估以
合成人群为主，缺少真实 trace 与与已发表系统的端到端对比。这两点无法靠
改写解决，只能靠新的实现与测量，已在限制一节如实交代。

## F. 模拟审稿意见的处理（第四轮）

外部模拟审稿（Weak Reject, 2/5）逐条核对后的处理，按"论文缺陷 / 审稿人误解"分类。

### F1. 已修正的论文缺陷（措辞与形式化，未改实验）

1. **标量上限 vs 向量成本（P0-2，成立）。** `model.tex` 原来写
   `spend + cost ⪯ E_s componentwise`，逐分量比较确实允许 1.9ε 通过 1.0ε 上限；
   `analysis.tex` 的 Proposition 2 与证明同样写法。实现一直是对的
   （`cost.py:102` 先转成 `ε_pure + ρ + 2√(ρ ln 1/δ)` 再与剩余额度比较标量），
   所以这是"定义与实现不一致"。现在成本模型定义标量映射
   `g(c)=ε_pure+ρ+2√(ρln(1/δ))`，两处命题与证明全部改为 `g(·) ≤ E_s`。
2. **intro 的 42/2.43（P1-9b，成立）。** E4 数据：k=42 时 audit-only 为 2.016，
   2.427 出现在 k=60；exact blocking 自 k=42 起为 1.694。原句把 k=42 与 k=60
   的数拼在一起。改为 "across 60 accounts"。
3. **效用实验的度量写错（P1-6，比审稿人指出的更严重）。** 原文称 "measures
   the F1 of each answer"，但 `e11_utility.py` 实际是 breast-cancer 上的
   高斯朴素贝叶斯下游**分类准确率**（CSV 列为 `accuracy`）。已按实现改写，
   并去掉"counting queries over one predicate"的错误描述。
4. **RDP 结论过宽（P1-3，成立）。** α_max=512 的网格确实无法标定 ε=0.02
   （下限 0.0225），但扩到 α≈1200 即可。原文"zCDP is the only backend"改为
   限定说法：zCDP 的优势是闭式可逆、无阶数下限，而非 RDP 原理上不能标定；
   `background.tex` 的"cannot calibrate at all"同步限定为"on a grid capped at 512"。
5. **intro 的 "microseconds"（P1-5，成立）。** 实测 p50 74 µs、p99 5.6 ms，
   原句读起来像整条路径都在微秒级。改为 "tens of microseconds at the median,
   with a millisecond tail"，§II-B 的 "latency budget of microseconds" 同步修正。
6. **熔断器状态机（P1-8，成立）。** 原来只有定性描述。现在给出实际阈值：
   压力落在 [0.60,0.85)、[0.85,1)、[1,∞) 分别进入 throttle/reject/freeze，
   升级立即、降级需连续 d=3 次低于当前带阈值减 h=0.05。
7. **SLO 监控口径（P0-3，基本成立）。** 原句称热表外的主体"cannot be the
   subject whose spend violates"，这不成立（只是不在最暴露的 H 个之内）。
   改为"最可能违约的是热表持有的主体"，并明确报告的是监控集比例而非总体比例。
8. **基线的键写错（P1-9a 的真正根源）。** 论文三处把 static quota / exact
   blocking 描述成 per-tenant，而 `policies.py` 实际按 (platform, subject)
   记账（类注释也这么写）。因此"单平台时退化为 per-subject"的结论成立，
   但理由不是租户合并，而是平台键在单平台时就是全局键。四处措辞统一为
   per-platform；审稿人举的"同一 subject 被多个 tenant 查询"的反例不适用。
9. **token bucket 的解释错误。** 它其实有 subject 键（(platform, subject)），
   但以 0.05 ε/s 回填，一小时 trace 内回填 180ε，远超 0.3ε 的分片预算，
   所以从不触发、曲线与 audit-only 完全重合。原文"neither has a subject key"
   改为上述机制说明。
10. **支持集假设（P0-6，部分成立）。** 现在明确：supp(q) 来自谓词与平台记录
    索引，不来自私有值，因此拒绝只泄露"预算已用尽"。
11. **不可信的持久性表述（P0-1 的措辞部分）。** 摘要把"crash-restart attacks"
    与"exactly-once"说满了，而账本后端是内存实现、Fabric 适配器是 stub。
    摘要改为"charges each admitted query once even when clients retry or a
    platform dies mid-query"；Proposition 3 增加前提"assuming the ledger
    outlives the coordinator process"；§VI 增加一句"Coordinator durability is
    the backend's, not the protocol's"。**实现层面未做 WAL/重启测试**。
12. **内存数字的口径。** 4.77 MB（E7，默认窗口）与 5.05 MB（E16，600 s 窗口）
    是两个配置；E16 的对比现在写成"in the same 600 s configuration"，并把
    5.0 改为实测 5.05。
13. **稠密窗口账本的措辞（P1-10）。** 8,640×10⁶ 是"每个 (subject, epoch) 都
    物化"的最坏情形；现在显式写明这一点，并指出稀疏实现按事件计费（E16）。

### F2. 新增实验 E20：等功能的 exact 控制组（回应 P0-4）

原 exact 基线同时缺少窗口、熔断与协调器，无法把差异归因于"近似"。E20 在
`build_privfuse(..., PrivFuseConfig(exact=True))` 下把 Count-Min 换成稠密表
（`privfuse/sketch/exact.py`），accountant ring、SLO、熔断、准入控制器与两阶段
协调器完全相同。

结果（1500 主体、12k 请求、cap 1.0/0.5、3 seeds）：

| 指标 | PrivFuse | exact（同栈） |
|---|---|---|
| availability | 0.8139 | 0.8139（逐 seed 完全相同） |
| windowed peak | 0.5057 | 0.5057（完全相同） |
| hard-cap violations | 0 | 0 |
| µs/request | 233 | 156（1.3–2.4×） |
| bytes | 5.01 MB | 0.37 MB |

结论对本文不利但诚实：在 10³ 主体规模上，sketch 只买到"斜率"——稠密表每主体
约 246 B，10⁶ 主体即 246 MB。论文据此把主张改写为"定位交叉点"，而不是
"近似免费"。README、docs/experiments.md 与 §VII-F 均已记录。

### F3. 审稿人判断有误或过头的地方（未按其意见修改）

- P1-9a 的反例不成立：基线不是 per-tenant 键（见 F1.8）。结论对、论证错。
- P0-6 说协议"会泄露成员关系"过头：只要 supp 由元数据决定就不泄露；已补假设。
- P0-3 的 H=1 是示意；默认 H=1024。但覆盖率问题在 N=10⁶ 时确实存在，已改口径。
- P0-2 说"hard cap 语义无法验证"不准确：实现比较的是标量，问题在论文定义。

### F4. 仍未解决（需要新的系统工作，非改写可及）

1. **WAL / 进程重启**：E19 是进程内异常注入，不是真正的 kill -9 后重放。
2. **多进程/多节点**：仍是单进程 2 vCPU；Fabric 适配器是 stub。
3. **等功能的 exact 对比只在 1500 主体**：10⁶ 处是外推，不是测量。
4. **私有账本元数据**：仍未解决，只在讨论中列为最重要开放问题。

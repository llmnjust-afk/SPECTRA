# PrivFuse 修订记录 / 审稿意见答复（ICDCS 2026）

产物：`main.pdf`，**11 页**（含图表、附录与参考文献），`latexmk` 编译通过，
0 处 Overfull box，0 处未定义引用/交叉引用。参考文献 **31 条**，全部被正文
引用，全部经 CrossRef 逐条核对（含作者全名、卷期页码）。

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

**B6 相关工作缺失** — 状态：**已修复**
- 文件：`sections/related.tex`、`sections/background.tex`、`refs.bib`。
- 改动：新增 6 条可核实文献（Dwork ICALP'06；Abadi CCS'16；
  Bittau SOSP'17；Johnson/Near/Song PVLDB'18；Wang SIGMOD'22；
  Jung & Park BigData'19），related work 重写为按**执行粒度（query /
  release / subject-transcript）、计量单位（ε per release vs per subject
  lifetime）、信任模型（central vs local vs enclave）、执行时机
  （admission vs post-hoc audit）、事务保证**五个维度逐项对比；
  删去"没有对应系统"的绝对化说法，改为"据我们所知，尚无系统同时在
  主体粒度上做跨租户、准入时的预算结算"。
- 依据：原稿 related work 只罗列机制、未做维度对比。
- 验证：每条新文献的 DOI/页码均经 CrossRef API 返回的元数据核对
  （详见 C 节）；正文 `\cite` 与 `refs.bib` 一一对应（脚本核验：31 cited = 31 entries，0 missing，0 uncited）。

### 应修复问题（S 系列）

| 编号 | 状态 | 处理 |
|---|---|---|
| S1 统计不确定度 | 已修复 | 从 `e3_breaker.csv` 逐种子读取，正文补标准差段落：PrivFuse 可用率 SD 在 cap 0.5/0.75/1.0/1.5 上分别为 0.0014/0.0124/0.0025/0.0005；两个基线为精确计数器、确定性，唯一随种子变化的是 cap 1.0 的违规数 13/13/12。明确写出"零违规是观测到的，不是证明的"。 |
| S2 追加工作负载 | 部分修复 | 新增 E13（结算扩展性）；未引入真实 trace，理由与残余风险写在 C 节。 |
| S3 热点表 churn 敏感度 | 未执行 | 无 churn 生成器，且改动会牵动估计器不变量；改为在 discussion 的限制一节明确写出"未测 churn"，不声称已覆盖。 |
| S4 不相交主体吞吐 | 已修复 | 见 B2(a)，E13 直接测量。 |
| S5 E11 机制与指标说明 | 已修复 | 明确 E11 为计数查询、下游为高斯朴素贝叶斯、指标为 F1；补充"四次发布按基本组合拆分 ε，因此偏保守"。 |
| S6 图可读性/单位 | 已修复 | 按单栏宽度重绘 Fig. 3 与 Fig. 7（3.4 in 宽、上下双栏、6.5–7 pt 字号），图例由代码标识符（`audit_only` 等）改为可读名称（audit only / exact per-tenant / PrivFuse），纵轴统一为 realized ε / cap 与 µs/request。 |
| S7 匿名 artifact | 未处理（不适用） | 代码仓库绑定真实 GitHub 账号，给出链接即破坏双盲；论文未加 artifact 声明。需作者决定是否建 anonymous.4open.science 镜像。 |

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
| 引用一致性 | 脚本比对 `\cite{}` 与 `refs.bib` 键 | 31 = 31，missing 0，uncited 0 |
| 单元测试 | `python3 -m pytest -q` | **37 passed** |
| 新实验 | `python3 -m privfuse.experiments.e13_settlement_scale` | 6 组进程内 + 3 组跨进程，3 次重复，CSV 已落盘 |
| 表格核对 | 正文 Table I ↔ `e3_breaker.csv` | 可用率/违规数/max_eps 全部一致 |
| 图核对 | Fig. 2/3 ↔ `e4_attack.csv`、`e8_scale.csv` | 一致；图已重绘可读 |

失败的检查：无阻塞性失败。唯一反复出现的问题是 bash 默认 120 s 超时
截断长实验，已改为显式超时参数；E13 初版因 `mp.Queue` 传输 2500 个浮点
造成管道死锁，已改为只回传聚合分位数。

## C. 未能完成、需外部条件或作者决策

1. **Shuffler（SIGMOD'18）未能加入**：DOI 猜测与注册库检索均未命中，
   OpenAlex/DBLP 当次不可用（HTTP 429）。为避免伪造条目，**未写入**
   `refs.bib`。这是已知文献缺口，建议作者补入并核对。
2. **多节点/拜占庭/多副本一致性**：需真实集群与共识实现，E13 仅覆盖
   单机双进程 loopback。论文已把结论限定在协议层。
3. **每主体标志位的内存开销**未量化：需要区分"每主体 1 bit"与 sketch
   状态的独立测量，当前实现未单独计量。
4. **热点表 churn 敏感度**：需 churn 生成器与估计器失效分析，未做。
5. **真实数据 trace**（如 TPCH/生产日志）未接入，全部为合成人群。
6. **匿名 artifact 链接**：需作者注册匿名镜像后才能写进论文。

## D. 最终科学评估

修订后，定义—命题—证明—实现—实验这条链现在自洽：B3 与 B4 是真实的
技术缺陷，已修好而不是用措辞掩盖；B5 经原始数据核查证明原句正确，
只补了配置限定；B2 用新测量替换了原先的定性断言，并且敢于报告
"分片对单一热点主体无收益、协调器进程 ~2.4k ops/s 饱和"这一负面结果。

对 ICDCS 审稿而言仍有两个结构性风险：(i) 系统贡献的分布式成分仍然薄——
一个单协调器原型、无共识、无副本，E13 恰恰量化了这一上限；(ii) 评估以
合成人群为主，缺少真实 trace 与与已发表系统的端到端对比。这两点无法靠
改写解决，只能靠新的实现与测量，已在限制一节如实交代。

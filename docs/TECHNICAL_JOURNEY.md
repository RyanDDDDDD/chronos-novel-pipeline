# 多智能体长文本叙事引擎 项目亮点与技术演进白皮书 (Technical Journey)

这份文档记录了本项目从早期的“脚本拼凑”走向“工业级长文本生成引擎”的过程中，所沉淀的核心亮点、跨越过的技术泥潭，以及具有里程碑意义的架构优化。

---

## 🌟 一、 项目核心亮点 (Project Highlights)

1. **对话驱动主笔循环 (Dialogue-Driven Author Loop)**
   打破「固定 DAG 拓扑 + 写作期 skill 选项卡」模式。设定共创（Setup Chat）在构建期完成骨架扩写、分 beat 与台词设计；主笔循环以 LangGraph 整章图流式落字，逐 beat 推演角色微状态。交互前移到构建期，写作期专注生成质量与连续性。

2. **首创“锚点-渲染”双轨制 (Anchor & Render System)**（DAG 时代遗产，概念仍适用）
   为了解决多 Agent 并发修改同一状态导致的上下文冲突，系统创造性地引入了“状态锚定”与“细节渲染”解耦机制。dialogue mode 中台词设计在构建期锚定，主笔在任务包约束下渲染正文。

3. **WebUI + 单进程异步后端 (MessageHub)**
   基于 FastAPI + React 的 Web 工作台，WebSocket 广播流式 token 与 beat 进度；可选 gateway 边缘代理。废弃 TUI/TCP 双进程与写作期双向 prompt 交互。

4. **进程内数据仓储 (In-Process Repositories)**
   情节图谱 (plot)、世界观 (lore)、实体档案 (archive) 经 `repositories/` 统一访问，可选 Chroma RAG。消灭独立 MCP 进程与 RPC 延迟，路径 SSOT 在 `utils.paths`。

---

## 🛠️ 二、 踩过的坑与核心技术优化 (Optimizations & Problems Solved)

在通往 V5.1 架构的道路上，我们经历并解决了以下几个严重制约 AIGC 长程生成稳定性的致命痛点：

### 1. 长程流转状态断层与 I/O 灾难
* **曾经的问题**：早期架构中，中间态产出会被切割成大量物理碎片文件。Agent 频繁的磁盘读写不仅导致严重的 I/O 瓶颈，还极易在多维度并行修改时丢失实体的物理状态（例如前置节点状态改变后，后置节点未能同步更新）。
* **核心优化：内存状态机与 Snapshot 机制**。废弃了中间物理碎片，所有切片数据和对应的“实体环境快照（Snapshot）”统一在 LangGraph 的 `PipelineState` 内存字典中进行原子级流转。极大地提升了处理速度，并保证了百万 token 级别流转过程中的绝对状态连贯性。

### 2. React Agent 动态工具调用的“推理死循环”
* **曾经的问题**：我们曾赋予大模型极高的自由度，允许其动态调用 MCP Tools 去查询世界观。但复杂的长文本逻辑常导致模型陷入“疯狂查表-遗忘主任务-最终输出格式崩溃”的推理死循环。
* **核心优化：上下文预注入中间件 (Pre-inject Middleware)**。我们将业务数据读取权限从 Agent 层剥离、上浮至 Orchestrator 级别拦截：在唤醒大模型**之前**，引擎主动从 MCP 提取当前实体的特征与最新演进阶段数据，静态编译进 System Prompt 的头部。将非确定性的 Tool-use 降维为确定性的文本生成，管线成功率跃升至 99%。

### 3. 超大并发负载导致的前端界面崩溃
* **曾经的问题**：由于并发生成和海量的 Token 报告流，TUI 终端在使用 Python 原生的 `readline()` 时，频繁撞上 64KB 的默认缓冲区上限（LimitOverrunError），导致监控界面死锁闪退。
* **核心优化：无边界分块读取与实时流式传输 (Chunking & Streaming)**。重构了底层的 TCP 接收逻辑，改为非阻塞的手动 Chunk 分块读取。打通了 `astream` 异步生成器，实现了大模型 Token 的实时流式推送，彻底告别了内存截断溢出。

### 4. 数据产物生命周期管理的混乱
* **曾经的问题**：随着异步生成任务增多，目录下充斥着一堆杂乱的生成稿，极难进行溯源追踪。
* **核心优化：生命周期自动化与拓扑排序**。引入了强制的产物路由规范，所有节点物理产出自动附带管线拓扑排序前缀（如 `第X章_S01_大纲.md`），使整个工作区数据生命周期井然有序。

### 5. 超长管线的中途崩溃与算力浪费
* **曾经的问题**：深度的 28 步流水线全量跑完通常耗时较长。中途网络抖动或进程被杀死会导致中间生成结果全部清零。
* **核心优化：断点续传与轻量级检查点 (Progress Checkpoint)**。系统在每个关键有向图边（Edge）计算完成后，会自动将状态无锁地持久化到进度 JSON。重启时，Orchestrator 能够精准反序列化该断点状态并无缝接续，提供了工业级的容灾能力。

### 6. 细粒度连续数值导致的大模型推理混沌
* **曾经的问题**：早期系统依赖 1-10 级的细粒度连续数值来控制角色状态演进。实验发现，大模型对“具体数值差异对应的行为表现”缺乏稳定的数值推断泛化能力，频繁出现状态越界与逻辑崩坏。
* **核心优化：离散阶段状态机降维 (Discrete Phase-Transition)**。我们将线性的数值系统重构为基于行为质变的“5-Phase（五个离散节点）”状态机体系。将原本需要模型去隐式推理的复杂数值特征，封装进明确的上下文转移协议中。系统直接下发当前离散状态的硬性规则约束，彻底解除了 LLM 对抽象连续数值的推理压力。

### 7. 数据底座的专业化脱水与感官特写重塑 (Data Sanitization & Visceral Rendering)
* **曾经的问题**：在早期的开发中，由于知识库（Lore/Plot）混杂了过多主观情绪与特定网文题材词汇（如“灵力”、“法宝”这类过于贴近某一具体作品的措辞），导致 LLM 极易陷入语境漂移，在生成时产生“网文式复读”，且引擎难以平滑扩展至其他小说世界观。此外，早期的生理心理描写要么过于抽象，要么过于生硬的医学化（如“高级神经系统瘫痪”），缺乏小说应有的画面感。
* **核心优化：双轨制分离与微观动作特写**。我们将角色状态机（Phase 1-5）彻底重构为“心理执念”与“生理失控”双轨分离模型。心理层聚焦内心的自欺与拉扯，生理层则抛弃抽象的医学名词，转而提供极度具体的非受控肢体特写（如“眼球上翻失焦”、“大腿内侧控制不住地打颤”）。这种基于动作细节的“颗粒度降维”，既消除了题材偏见，又让大模型写出的正文画面感极强，实现了引擎数据规范的全面工业化升级。

### 8. 通用对话指令模型的建立 (Universal Dialogue Constraints)
* **治理背景**：尽管我们建立了阶段性的心理状态弧线，但 LLM 在生成不同角色台词时，依然容易出现语气同质化（“AI 味”）或脱离人设的问题，缺乏稳定的人格辨识度。
* **里程碑动作**：创建了跨题材通用的 `personality_types.json` 静态性格本质库（包含 20 种核心人格）。我们抛弃了让模型“扮演某人”的宽泛提示，转而提供硬性的指令级约束：将性格解构为 `syntax`（句法结构、长度、停顿）、`vocabulary`（词汇偏好、禁用词）和 `emotion_expression`（情绪应激反应）。这种代码级别的语感约束，使得对话引擎真正具备了工业级的角色塑造稳定性。

---

## 🚀 三、 V6.0 - V8.0 架构演进与深度治理 (Architecture Evolution & Deep Governance)

随着流水线的复杂化，系统暴露出了更深层次的资源损耗与大模型认知盲区。V6.x - V8.0 阶段的核心命题是：“数据前置、管线平滑、消灭幻觉、高度解耦”。

### 0. 提示词工程的彻底解耦与题材脱敏 (Prompt Decoupling & Theme Desensitization)
* **治理背景**：早期提示词深度耦合了特定原著名词与硬编码逻辑链，导致 Token 浪费、缓存命中率极低且引发严重的“题材幻觉”。
* **里程碑动作**：对全量 Agent 执行题材脱敏，采用“主导方/受体”等高抽象占位符。引入“微缩示例策略”，将散文示例压缩为原子级映射。同时将行为原型的演进模式迁移至数据平面的 `personality_types.json`。

### 1. 局部动态状态机引擎 (Per-Character Dynamic State Machine)
* **治理背景**：早期的对话生成依赖全局静态强度，无法体现多实体场景下的个体差异。表现僵化且存在“各说各话”的脱节感。
* **里程碑动作**：在 `dialogue_loop` 中引入个体动态状态机。为每个实体引入实时演进的“兴奋度 (Arousal)”与“自制力 (Control)”指标。通过动态归一化步长与“动态阻尼算法”，模拟出理智崩坏的非线性张力。同时实现动作刺激的实时感知同步。

### 2. 组件化衣柜与服装 DNA 架构 (Component-Based Wardrobe & Clothing DNA)
* **治理背景**：静态服装描述在变装场景下易引发认知分裂，且无法体现随状态演进而产生的物理暴露度变化。
* **里程碑动作**：重构为 `clothing_dna` 架构，定义色系、材质偏好及按阶段分层的“行为模式”。建立 `outfit_library.json` 将服饰拆解为强制物理插槽，通过“材质重铸”算法确保外来款式完美缝合实体的原生特征。

### 3. 多角色并发推演的“逻辑坍塌”与蓝图前置 (Combinatorial Constraint Governance)
* **治理背景**：在处理包含 3 个以上实体的复杂高冲突交互场景时，LLM 频繁出现“实体分身”或“物理组件溢出幻觉”。
* **里程碑动作**：全面转向 **“插槽拓扑架构 (Slot-Based Topology)”**。在动作映射库中废弃硬编码分类，重构为包含物理组件要求的约束模型。Orchestrator 在调用 Agent 前执行“前置动态装配蓝图”，将实体精准“填入”匹配的插槽中。

### 4. 提示词缓存与 API 性能优化 (Prompt Caching & Efficiency)
* **里程碑动作**：重构了 `PromptManager` 与 `LLMManager` 的装配顺序。通过“静态指令前置 + 动态数据后置”的策略，大幅提升了云端 API 的缓存命中率。引入本地模型预设系统，实现对采样参数的标准化控制。

### 5. 感官本体库的横向扩充与身份解耦 (Ontology Expansion & Archetype Decoupling)
* **里程碑动作**：对感官本能语料执行全量横向扩充（数量提升 300%），并实施严格的“身份解耦”审计。剔除所有背景词汇，转向纯粹的生理应激描述，实现了感官本体的工业化脱敏。

### 6. 动态工具调用灾难与 Pre-inject 全面静态化
* **里程碑动作**：全面废弃了 Agent 的动态 MCP 工具调用权限，替换为 Orchestrator 级的 `pre_inject` 拦截机制。通过单段落角色过滤，精准注入当前所需的设定，使管线成功率提升至 99%。

### 7. 长文本吞噬与管线平滑重排 (Pipeline Smoothing)
* **里程碑动作**：将神情 Agent 降级至 `segment` 作用域；砍掉冗余的特征核验步骤。按照文学逻辑将管线重排为 `心智 -> 神情 -> 台词 -> 感官 -> 拟声` 的黄金反应链。

### 8. 多实体交互中的归属权幻觉治理 (Entity Attribution Hallucination Governance)
* **里程碑动作**：重构底层 Knowledge Base，引入强拓扑语义断言，强绑定组件与其宿主实体的物理关系。并在系统指令中植入高优先级操作红线，严禁跨实体的属性转移。

### 9. 动态资产滥用与宏观调度失控
* **里程碑动作**：引入 `Two-layer Brainstorm`（全局规划 + 局部精调）架构；同时为所有资产强制绑定生命周期上下文约束，压制生成式 AI 的不受控发散。

### 10. 锚点密度过载导致的“呼吸感”缺失
* **里程碑动作**：引入“0-过渡/1-铺垫/2-高潮”的三级强度门控体系。系统根据关键词自动判定强度层并分配“细节预算”，显著提升了文学美感并降低了 Token 消耗。

### 11. 编排器超载与金融级容灾架构解耦 (Orchestrator Modularization)
* **治理背景**：随着断点续传、文件物理对账（Heal）机制的加入，核心编排器代码膨胀至数千行，违背了单一职责原则。且原地的 JSON 文件覆盖写入存在断电导致进度清零的非原子操作风险。
* **里程碑动作**：将编排引擎执行了四层深层解耦（`ProgressManager`, `LLMGateway`, `RefineController`, `ContextBuilder`）。
  - **独立进度管理器**：将物理对账、断点恢复剥离。引入 **原子写入 (Atomic Write)**（先写入 `.tmp` 再 `os.replace`），即便遭遇不可抗力也能自动降级读取 `.bak`，将容灾能力提升至工业级安全标准。
  - **全链路黑盒化**：Orchestrator 瘦身至纯粹的 LangGraph 状态机调度者，极大提升了核心引擎的测试覆盖率与代码可维护性。

### 12. 多维度 TAG 的位点精度治理 (Multi-Dimensional TAG Placement Governance)

* **治理背景**：流水线中存在 5 个并行运行的维度标注 Agent（声音/感官/神情/心智/环境），各 Agent 依次处理同一段原文。由于每个 Agent 独立判断"当前段落最强触发时机"，导致它们均将 TAG 堆叠至同一个叙事峰值句末尾——单段最多出现 9 个 TAG 连排的极端情况，完全破坏了文学节奏的呼吸感。
* **里程碑动作**：在 `global_base.md` 通用基础协议中新增 **§六「插入位点精度规则」**，全局强制三层约束：
  1. **句级锚定**：每个 TAG 必须紧跟其**直接触发句**末尾换行插入，禁止统一堆叠至段落末；
  2. **同 Agent 散布**：同 Agent 在同段插入多个 TAG（如多角色状态）时，各 TAG 分别锚定至各自独立的触发句；
  3. **跨 Agent 位点感知**：插入前检测目标句已有 TAG 数——已有 2+ TAG 时，`medium` 强度 TAG 须寻找次级触发句，`low` 强度 TAG 直接跳过。配合查表式强度门控，实现了 TAG 密度的跨 Agent 协同管控，无需引入额外的协调通信机制。

### 13. 多轮生成泄漏与台词解析器修复 (Multi-Turn Leakage in Dialogue Parser)

* **治理背景**：对话循环 Agent 的 LLM 偶发性地在单次响应中输出多个 `[动作][台词]` 轮次块。下游解析器使用了非贪婪 `.*?` + `re.DOTALL` 模式提取台词字段，导致 `dialogue` 分组从首个 `[台词]` 一直捕获至 `[心理]`，将额外的 `[动作][台词]` 标签原样吞入 `dialogue` 字符串。经 `format_turns()` 渲染后，方括号标签字面量出现在正文引号内，且额外轮次缺失角色主语。
* **里程碑动作**：在 `parse_turn_output()` 提取 `dialogue` 组后，立即执行一次 `re.split(r'\n+\[动作\]', dialogue_raw)[0]` 裁切，仅保留首个 `[动作]` 出现前的干净台词文本。该修复不依赖改变正则主模式，覆盖"正常单轮"与"LLM 多轮泄漏"两种边界情况均无副作用。

### 14. 插件幻觉封堵：ID 强锁定约束 (Plugin Hallucination Suppression via ID Lock)

* **治理背景**：统计数据揭露了一个隐蔽的 LLM 幻觉现象：插件注入 Agent 在提案阶段，基于库内相邻插件的语义联想，自造了一个库中不存在的插件名称，并通过了后续选择与执行两关，在正文中留下了无效锚点。该问题之所以能穿透多道过滤，根本原因在于约束为"找到匹配 trigger 即可使用"，未明确要求引用路径锁定到注入列表的 `id`。
* **里程碑动作**：在 Agent Prompt 的核心约束区新增 **「插件 ID 锁定」** 条款：所有插件引用必须来自预注入的 `available_plugins` 列表，以 `id`（如 `UPP-17`）为唯一标识符；找不到库内匹配 trigger 时宁可不注入，严禁凭语义联想生造名称。同步将 `min_phase`、`once_per_chapter`、`max_uses` 三个运行时门控字段从插件数据库中整体移除，消灭了"字段过滤逻辑"的复杂度来源，将执行约束权完全回收至编排层。

### 15. 插件提案多样性治理：统计反馈驱动的加权采样 (Diversity Governance via Feedback-Driven Weighted Sampling)

*   **治理背景**：对 `selection_stats.json` 的统计分析暴露了严重的马太效应：Top 3 插件独占全部提案总量的 36.6%（296/809），而末位 2 个插件在数百次运行中**零提案**。这一偏斜源于 LLM 的"认知惯性"——模型对高频出现的插件名建立了偏好关联，而对描述语感"平实"的长尾插件几乎视若无睹。传统解法（Prompt 中声明"尽量少用 X"）对大模型负向约束能力极差，实测完全无效。
*   **里程碑动作**：抛弃 Prompt 干预路线，**在 Python 层的 `get_available_plugins` 接口直接动刀**，实现"加权轮盘抽样 + 类目保底"机制。

### 16. V9.0：单进程多任务与并发多管道时代 (Multiplexing & Decoupling Era)

*   **治理背景**：随着视觉、音频等多重支线的引入，传统的“多进程+多端口”架构带来了沉重的运维负担。同时，Manifest 中冗余的 `pre_inject` 配置和硬编码路径严重阻碍了 Agent 的插件化封装。
*   **核心重构一：单进程多任务与 Tagged Stream**。
    废弃了物理级的 `spawn` 进程，重构为基于 `asyncio.Task` 的协程调度模型。通过单一 TCP 端口复用，在应用层引入 `p_id` 路由标签，实现了多管道事件的统一汇流与“内存事件重放”。
*   **核心重构二：Context Provider 自动化装配**。
    建立了中央数据提供者注册表，将“如何获取数据”的逻辑从流程配置中剥离。Agent 仅需声明其对“实体档案”或“感官本体库 (Sensory Ontologies)”的语义需求，系统即可在执行前自动并发装配上下文，使 Manifest 体积缩减了 70%。
*   **核心重构三：Agent 资产自洽性与强制审计**。
    实施了“能力归 Agent，资产归 Data”的迁移策略。将领域专精的静态资产移入 Agent Package 目录（现为 `hooks/packages/`），并引入基于 `schema.json` 的强制审计机制，确保高冲突交互 (High-Conflict Interaction) 逻辑的稳健性。
*   **核心重构四：对话引擎策略化与断点续传**。
    将交互循环重构为“Shell-Strategy”模型。支持逐轮对话的原子级检查点（Checkpoint）持久化，即便系统崩溃也能在重启后从当前台词轮次无缝接续，提供了金融级的容灾能力。

### 17. V10.0 Phase 1：并行状态机与感官并发时代 (The Parallel Era)

*   **治理背景**：随着 Agent 职能的极度细化（神情、心智、感官、拟声、物理细节），串行执行导致单章生成时间突破了 5 分钟大关。同时，下游 Agent 不断在充满前序标签的文本上“二次加工”，导致注意力分散。
*   **核心重构一：并发打标集群 (Fan-out/Fan-in)**。
    Orchestrator 引入了并行任务池，将同一段落同步分发给 5 个打标 Agent。各 Agent 在最纯净的原文上独立作业，通过 `asyncio.gather` 并发收流，生成效率提升了 400%。
*   **核心重构二：圣诞树效应治理 —— 从权重修剪到两段式合成 (Christmas Tree Governance)**。
    *   **病灶（圣诞树效应）**：8 个维度 Agent 在同一段落并发打标，一句动作后可挂载 4-6 个 `[[TAG:...]]`；合成师消费时退化为“一个 TAG 一个短句”的机械翻译机，产出无节奏的“体检报告”式紫色散文。
    *   **方案一（密度修剪 · 已设计）**：传给合成师前用 Python 滑动窗口降噪——以标点/字符距离划窗，按信息量权重金字塔（心智>神情>物理>台词>感官>拟声>环境）做 Top-K 截断，每窗最多保留 3 个 TAG，无声抹除末位低权标签。
    *   **方案二（拓扑稀释 · 已落地）**：更进一步的**两段式接力管线**——新增 `synthesis_visual` 节点先合并视觉维（神情/体态/霓裳）并**提前合成一次**；正文维（物理/环境/心智/官能/拟声）改以该合成稿为基底打标。基底已扩写，标签分布被天然稀释，从源头消除过载，而非事后修剪。
    *   配合**非破坏性标签聚合算法 (Tag Convergence)**（字符偏移映射 + 优先级竞标）完成多维标签的无损汇流。
*   **核心重构三：ContextRegistry 全面接管数据层**。
    彻底终结了 MCP 进程间通信的时代。所有数据读取（Lore, Plot, Assets）全部下沉至进程内的单例 Registry，消灭了 100% 的 RPC 延迟。
*   **核心重构四：暴力白描协议 (Anti-Purple Prose)**。
    为了解决生成文本过度文学化、缺乏真实肉体冲击力的问题，在本地执行师阶段全面植入“去文学化法则”，废除所有比喻与环境渲染，转向极致短促的节奏碎片化动作描写。
*   **核心重构五：对话引擎从"逐轮状态机"到"锚点 intensity + 就地扩写"**。
    早期对话靠 arousal/control 状态机逐轮生成、配节拍表与原型声纹模板，链路重、易复读且高 phase 退化。最终重构为**锚点自带 intensity（low/medium/high）+ 单次就地扩写**：锚点师按剧情给每条台词锚点标强度，引擎一次把整段锚点就地展开成对话，方向由角色 archive 的 `state` 决定、措辞由 phase 分档词库提供。废除了 arousal/control/bidding/节拍表/原型模板整套中间机制。
*   **核心重构六：Agent 资产自治化与静态层解耦**。
    *   **病灶**：全局的 `data/` 目录和引擎底层的 `domain/` 代码混合了太多专属于特定 Agent 的业务逻辑。比如原本引擎需要负责拓扑校验和对白循环，导致了极强的代码耦合。
    *   **方案**：实施了“能力与数据归 Agent”的绝对自治化迁移。所有专门服务于某职能的配置（如服装库、动作库、拟声词典）与代码块，全量下沉至 `hooks/packages/<name>/assets/`（当时为根目录 `agents/`）。彻底清理了 Manifest 中的静态注入机制，实现了类似 Web 插件的插拔体验。
*   **核心重构七：原生 LangGraph DAG 与扇入合并 (Fan-in Merge)**。
    *   **病灶**：早期的流水线采用数组定义线性顺序，无法优雅地表达感官集群的“并行分发后再次聚合”。
    *   **方案**：引擎重构为原生有向无环图调度器。在执行时基于节点显式声明的 `inputs` 动态构建执行计划。多路并行任务会在原生的 Merge 节点处实现完美汇流，终结了数组排序带来的副作用。
*   **核心重构八：Judge-Revise 自我审阅执行原语**。
    *   **病灶**：大模型生成具有随机性，偶尔在特定步骤（如对齐剧情节点、计算姿态约束）会严重翻车，只能由人类介入。
    *   **方案**：在核心步骤（如 REFINE、体位锚定）外壳套用 `run_with_review` 包装。模型先按既定基准 (Rubric) 自审其输出是否合格，不合格则内部截留并重新提审，构筑了底层质量防线。
*   **核心重构九：双轨对话扩写架构 (Dialogue Anchor & Expander)**。
    *   **病灶**：最初设计的“逐轮情绪状态机”虽然严谨，但极容易导致大模型自我复读，且“各说各话”的现象严重，且消耗过量上下文算力。
    *   **方案**：废弃了逐轮状态机，重构为两步走的宏观统筹机制：第一步 `dialogue_anchor` 只负责在文中标记“这里该说话，且情绪强度是 X”；第二步 `dialogue_expander` 通过掌握全景上下文，一次性就地将所有占位符展开。显著减少了算力磨损并提高了对话的交锋感。

---
### 18. 深层架构解耦与防断层策略 (Deep Decoupling & Truncation Prevention)

*   **治理背景**：尽管 V10 Phase 1 实现了高并发，但超长上下文 (Long-Context) 导致的末端生成截断、以及实体属性硬编码带来的泛化困难，依然是制约生成质量的隐患。
*   **核心重构一：首尾重塑的无损拼接 (Splicing Truncation Prevention)**。
    *   **病灶**：Framer (首尾重塑师) 需要摄入完整的几千字正文并修改首尾，LLM 极易在输出中间部分时发生上下文截断遗漏。
    *   **方案**：在 Prompt 层面强制要求 LLM **仅输出**重构后的首尾文本（不输出中间原文），在 Python 调度层通过原汁原味的正则切片将中间段落无缝拼接回去。这从物理层面100%根除了中间长段落丢失的问题。
*   **核心重构二：动态词汇库与形体拓扑注入 (Dynamic Vocabulary & Topology Injection)**。
    *   **病灶**：早期动作库与台词风格耦合了大量的硬编码描述，导致跨角色的表现同质化。
    *   **方案**：彻底实现数据层中立化。动作库剥离所有特定身材质感词汇，交由 Context Registry 在运行时注入每个实体的 `physique_dna`；同时依据实体所处的认知演进阶段 (Phase)，注入分档次的词汇空间与位阶称呼表。实现了“骨架通用，皮肉千人千面”。
*   **核心重构三：状态机抽象大一统 (State Machine Unification)**。
    *   **病灶**：历史遗留的 `pressure/arousal` 状态机导致数据 Schema 冗余，且常常与台词引擎的新机制产生状态冲突。
    *   **方案**：彻底移除退役的遗留状态系统。对话系统全面转向基于 `intensity` 锚点与就地一次性展开的新架构。极大地简化了数据实体的序列化负担，提升了系统的整体可维护性。

### 19. V10.0 Phase 2：资产契约、纯净流与精修革新 (Asset Contracts, Pure Streams & Refinement Revolution)

*   **核心重构一：Agent Package 契约治理 (Governance & Preflight)**。
    *   **病灶**：随着 Agent 数量膨胀，上下游依赖变得隐性且脆弱。缺少环境依赖校验导致运行时频发崩溃。
    *   **方案**：引入 `meta.json` 强契约机制，显式声明 Agent 的 `injects` 与 `requires`。在系统启动前执行 Catalog 扫描，在运行前执行 Preflight 校验，实现了绝对安全的插件化装配。
*   **核心重构二：单一滚动编织对话 (Rolling Dialogue Weaver)**。
    *   **病灶**：双轨对话（Anchor + Expander）在多段落连续切片下产生了拼凑感与高昂的算力损耗。
    *   **方案**：将双轨合并为单一的 `dialogue_weaver`，配合新增的 `voice_modulators`（情绪声调调制层），通过单遍滚动增量处理，一次性完成高张力对白的连贯展开，消除复读感。
*   **核心重构三：纯净正文流与结构化组装 (Pure Prose Stream)**。
    *   **病灶**：早期段落中夹杂着阶段标题等元信息，导致中途 Agent 经常保留或输出不必要的 Markdown 结构，污染了正文的连贯性。
    *   **方案**：将段落输入彻底分离为“元信息”与“纯正文”。所有修饰 Agent 仅处理纯正文，最终在组装阶段（Assemble）统一注入 `【过程描述】` 等结构标签，保证了流转过程的纯净。
*   **核心重构四：多轮交互式精修 (Multi-turn Brainstorm Refinement)**。
    *   **病灶**：原本的 REFINE 模式只支持单次的选项勾选，无法处理复杂的上下文发散与深度策划。
    *   **方案**：将 REFINE 模式全面升级为多轮 Brainstorm 精修原语。支持前端在节点级发起多轮讨论与干预，极大地释放了创作者对剧情走向的微观控制力。

### 20. V10.0 Phase 3：多档案编排与分块推演时代 (Multi-Profile & Chunking Era)

*   **核心重构一：分块滚动埋槽 (Embed Splice & Chunking)**。
    *   **病灶**：在处理超长段落时，能力较弱的大模型经常出现“整段落空”、“避重就轻”的偏科现象，导致设定的关键描写丢失。
    *   **方案**：引入了 `embed-splice` 与 `compose-splice` 策略。将长段落进行细粒度分块，采用基于拓扑锚点的滚动埋槽填充技术。极大降低了单次 LLM 处理的认知负荷，强制弱模型也能实现细节的全覆盖与定点注入。
*   **核心重构二：多流派档案与动态路由 (Pipeline Profiles & Dynamic Routing)**。
    *   **病灶**：过去整个系统被硬件绑定在单一的 `pipeline_manifest.json` 上，无法同时支持多种编排流派（如动作特化流、对白特化流）的快速切换，严重阻碍了管线的 A/B 测试与多元化创作。
    *   **方案**：全面解除了引擎核心与单管线配置的耦合。重构了前端 WebUI 数据层与后端 5 个基础路由 API，实现了管线档案（Pipeline Profiles）的动态读取、新建、切换、重命名与热重载。
*   **核心重构三：因果锚点与双语义驱动 (Causal Anchors & Dual Semantics)**。
    *   **病灶**：过度依赖纯数值滑块去控制人物走向，容易让大模型的输出陷入模版化；原有的单向进度阶梯也无法适配核心角色的逆向语义需求。
    *   **方案**：完全废弃硬编码的单向阶段表，转向了“双语义驱动”：施加方使用 `Drive-Obsession`，受体方使用 `Wound-Lie-Need`。采用 Delta Forcing 增量滚动推演，在确保极端个性化的同时，使引擎能够游刃有余地处理多角色的复杂叙事弧线。
*   **核心重构四：自语与交锋的物理管线剥离 (Soliloquy Decoupling)**。
    *   **病灶**：将单人自语和多人交锋混合在一个台词编织师内，导致弱模型在复杂多人场景中频繁混淆主谓宾，或是将内心戏写成直白的对话。
    *   **方案**：将对话引擎一分为二。`dialogue_weaver` 专责多人交锋，收窄锚点范围；新增 `soliloquy` (自语师) 专责单人出声。分离了单双人的提示词上下文，显著减少了定位失败与错乱。
*   **核心重构五：批处理结构化自审 (Batched Structured Window Judge)**。
    *   **病灶**：在滑动窗口埋槽期间，逐窗口进行自审与重填不仅大幅增加了 Judge 调用次数，还容易造成上下文碎片化与 Token 浪费。
    *   **方案**：重构 `embed-splice`，引入 3000 字批处理结构化裁决。失败的插槽直接使用 Judge 给出的 fixed 修正方案进行回填，去掉逐窗口重填逻辑，大幅降低了 API 调用量与耗时。

### 21. V11.0 主笔范式：人在环路的并发交互死锁治理 (Human-in-the-Loop Concurrency Deadlock)

*   **治理背景**：新一代「主笔驱动写作循环」中，单个叙事拍（beat）可由主笔自主决策同时启用多个技能（如 `foreplay` + `plugin`）。引擎用 `asyncio.gather` 并发执行这些技能的扩写，而每个技能又是**交互式**的——需向前端弹出选项让创作者勾选。
*   **病灶（单槽竞态致永久挂起）**：后端交互回调 `_prompt_user` 用**单个** `_author_pending` 槽位记录「当前待回应的 prompt + Future」。多技能并发时，两个 `_prompt_user` 协程同时写槽：后者直接覆盖前者，使前一个技能的 Future 成为**无人能解锁的孤儿**（回应路由只认当前槽位 id，对孤儿 id 一律当陈旧丢弃）。前端同样是单 prompt 槽，第二张卡片覆盖第一张，创作者只看到、只回了后一个。结果：前一个技能的 `await` 永久挂起 → `gather` 永不返回 → 整条写作循环静默死锁，前端停在「写作中」。
*   **里程碑动作（交互串行化锁）**：在 `MessageHub` 引入一把 `asyncio.Lock`，将 `_prompt_user` 的「设槽 → 广播 prompt → 等待回应」全程纳入锁的临界区。这样并发技能的 **LLM 扩写仍保持并行**（性能不损），仅把真正需要人工介入的那一瞬间串行化——前一张选项卡答复后才弹出后一张。修复定位于竞态根源（单槽对并发无保护），而非妥协业务并发；停止操作经 `async with` 在取消时自动释放锁，不留死锁残留。该案例的本质是 **「异步并发」与「单一共享可变状态」的经典冲突**——解法不是消除并发，而是用锁圈定那段不可重入的临界区。

### 22. 主笔与文风提示词的分层去耦 (Prompt Layer Decoupling: Duty vs Prose-Style)

*   **治理背景**：落字 system prompt 由四层动态拼装——全局协议 + 主笔职责基底（`author_write_base`）+ 防 AI 腔文风底座（`prose-style-base`）+ per-novel 语感调色档（`prose-styles/<preset>`，可热插拔）。三层本应正交：**职责层**管「写什么」（保真草稿、台词主导、情景指示）、**底座**管「句子怎么排（通用、内容无关、所有 Agent 共用）」、**调色档**管「用什么词、什么调」（用词雅俗/比方/露骨度）。
*   **病灶（层间互相伸手）**：三处渗漏破坏了正交性。①**职责层反手裁判调色档**——硬编码某调色档名、断言其风格样例形态（"多为纯动作描写"），替「台词主导 vs 无对白样例」的冲突收尾；换调色档即失真，违反层隔离原则。②**底座自破「只管与文笔无关的句子组织」的自我声明**——其「要有内心」条目引用了注入的 `psychology`（内容相关），且与职责层「贴合当前状态」重复。③同一「show not tell 情绪」诉求在底座与调色档**跨层各写一遍**。根因：职责层（台词主导）与调色档（样例全是纯动作、零对白）天然冲突，弱模型照样例仿写就把对白丢光，于是被迫在职责层打一块「裁判补丁」去压。
*   **方案（边界归位而非搬字）**：①把跨层裁判句**上移到底座的「各层分工」声明**并去 preset 化（底座本就负责框定各层边界），职责层删除对调色档的全部引用。②「必须有内心」作为**内容硬要求并入职责层**（它依赖注入的当前角色状态），底座只保留「情绪靠 show 不靠 tell」的通用句子 craft。③调色档删除与底座重复的条目。结果：**职责层只说"写什么"、底座只说"句子怎么排"、调色档只说"用什么词"，无一层点名另一层**——任意调色档可热插拔而不牵动上两层。本案例的本质是 **关注点分离（SoC）在提示词工程中的落地**：用「补丁」消解层间冲突会沉淀耦合，正解是把每条约束放回它真正归属的轴。

### 23. Windows ProactorEventLoop × LangChain 异步桥接死锁 (Async Bridge Deadlock)

*   **治理背景**：引擎在 Windows 上单进程运行，Python 3.8+ 的 asyncio 默认事件循环为 `ProactorEventLoop`。LLM 调用最初统一走 `langchain_openai.ChatOpenAI`，在 openai SDK + httpx 之上叠 langchain 线程桥接；再上层还有 LangGraph 异步图调度。
*   **病灶（流式调用静默死锁）**：LangGraph `await ChatOpenAI.astream` 时，langchain 线程桥接与 ProactorEventLoop 互等，协程永不返回，**不抛异常**。
*   **方案**：绕开 `ChatOpenAI`，改用 `openai.AsyncOpenAI` 直接发请求（`llm/factory.py`）。LangGraph 节点内统一走裸 async 客户端。

### 24. V12–V13：DAG 与 Classic 主笔退役 (Pipeline Retirement)

*   **治理背景**：段级 LangGraph DAG（28 步固定拓扑）、classic 主笔（architect 骨架 → 逐 beat 决策/expansion skill/落字/守卫/摘要）与 manifest 驱动执行并存，运维与认知成本高。
*   **里程碑动作**：
    - 删除 `NodeGraph` 段级 orchestrator；manifest 降级为 agent-meta / skill 编排元数据，**不驱动**运行时拓扑。
    - 退役四阶段 context hook 与独立 MCP 数据服务进程；数据访问收敛至 **`repositories/`**（`JsonStore` + 领域 repo + 可选 Chroma）。
    - 章节生产入口统一为 WebUI `POST /api/author-loop/start`；无 CLI 章级 DAG。

### 25. 对话驱动主笔循环 (Dialogue-Driven Author Loop)

*   **治理背景**：classic 路径在写作期同时承担「分镜决策 + 多 skill 交互 + 落字 + 状态滚动」，弱模型注意力分散；写作期 `author_loop_prompt` 与并发 skill 存在单槽竞态（§21）。
*   **里程碑动作**：
    - **Setup Chat**（`engine/setup_chat/` + `skills/setup_chat_skills/`）在构建期完成 skeleton-expansion、beat 分镜、beat-dialogue-design；产出写入 `plot_library.json` 的 `segments[].beats[]`。
    - **dialogue mode** 主笔：`load_prebuilt_skeleton` → `extract_beats` → LangGraph **整章 react 图**（`task_packet → author_prose → derive_states → advance`）。
    - 写作期改为 **WebSocket 单向广播**（`author_loop_token` / `author_loop_segment` / `author_loop_state`）；移除 `author_loop_prompt` / `author_loop_reply`。
    - 检查点从 JSON 迁移至 LangGraph **SQLite**（`_author_loop_graph.sqlite`）；事件 journal 保留 NDJSON 重放。

### 26. 整章记忆与状态推演简化 (Whole-Chapter Thread & Derive Pipeline)

*   **治理背景**：classic 路径 per-beat 多轮改写、summary agent、逐角色状态守卫叠加 LLM 调用，成本高且主笔 messages 线程膨胀。
*   **里程碑动作**：
    - 整章一条 `messages` 线程；`_llm_view` 将早于 `KEEP_FULL_BEATS=2` 的拍坍缩为骨架概要，checkpoint 仍保留完整历史。
    - **author_prose** 一次写定本 beat（旁路 observer 仅 telemetry 报警，不反馈改写）。
    - **derive_states** 短 mini-thread + `update_states` 工具；校验失败重试 ≤2 次后 skip + alarm。
    - **2026-07-06**：逐角色并发 **状态守卫**（`dialogue_mode/guard.py`）退役——用户复核后判定报警收益不足以维持额外 LLM 层；状态写入仅保留工具校验门。

### 27. Repositories 取代 ContextRegistry (Data Layer Consolidation)

*   **治理背景**：`ContextRegistry` + `providers/` + `indexers/` + MCP RPC 与 author_loop 直调 repo 并存，路径与缓存策略分散。
*   **里程碑动作**：
    - 启动时 `init_repositories()` 扫描 novel 目录；`get_lore_repo()` / `get_plot_repo()` / `get_archive_repo()` 等为唯一 accessor。
    - `context/` 保留 gender、character_resolver、timeline、pre_inject 等**纯函数 helper**，不再经四阶段 hook 声明链。
    - setup_chat research grounding 与台词语料 RAG 走 `ChromaDialogueRepository` / `ChromaResearchRepository`。

### 28. 前后端类型漂移导致的渲染崩溃 (Frontend Type Drift → React #31)

*   **治理背景**：角色档案（archive）的 `address_ref`/`self_ref` 字段最初落地时是扁平值（`string`/`string[]`），前端 `types.ts` 与 `CharacterCard.tsx` 照此声明并直接渲染。后端的「称呼池化」演进（按目标/语境分桶，如 `{"角色A": ["角色A"]}`）落地后，前端类型与渲染逻辑未同步跟进。
*   **病灶（静默类型不匹配 → 运行时崩溃而非编译期报错）**：TypeScript 的结构化类型在这里没能拦下问题——`ArchiveStage.address_ref?: string` 的声明只是**断言**，运行时数据早已是另一种形状；`{stage.address_ref}` 把一个对象直接扔进 JSX，触发 React #31（"object 不是合法的 child"），且线上 minified 报错完全不可读（`Uncaught Error: Minified React error #31`），必须回源码+实际存档数据交叉核对才能定位。排查时进一步发现同一字段在存量数据里其实有**三种并存形态**（旧 `string`、类型声明的 `string[]`、新 `dict` 桶），说明这类字段的形态演进从未有一次性迁移，全靠"读时兼容"撑着。
*   **方案**：类型声明改成显式 union（`string | string[] | Record<string, string[]>`）如实反映数据的历史演进，而非只描述"当前设计意图"；渲染层写一个 `renderRefPool()` 归一化函数吃掉全部三种形态，替换直接渲染。**教训**：后端数据形状的演进（尤其是"分桶"这类结构升级）必须同步检查前端消费点，不能假设 TS 类型和运行时数据永远一致——`grep` 实际落盘 JSON 的字段形态比读类型声明更可靠。

### 29. Story Sandbox 召回未隔离导致真实数据泄漏进单测 (Unmocked Recall Leaking Real Data into Tests)

*   **治理背景**：`recall_relevant_context()`（`engine/story_sandbox/recall.py`）不接受 `novel_id` 参数，而是像仓库里其它 per-novel repo 一样，靠 `utils.paths` 解析"当前 active 小说"的磁盘路径（向量库 `sandbox_vector_memory_dir()`、`load_event_log()`、`get_world_repo()`）——这与项目既有的多小说隔离惯例一致，不是设计缺陷。但 `tests/engine/story_sandbox/test_graph.py` 的 `_isolated_checkpoint` autouse fixture 只 mock 了 `seed_state`/`resolve_stage1_cast`/`build_sandbox_system_prompt`，唯独漏了 `recall_relevant_context` 这条链路。
*   **病灶（测试隔离缺口 → 环境依赖的假阳性/假阴性）**：测试传入的 `"novel-1"` 只是个不存在的假 id，从未真正让 `recall_relevant_context` 感知到"应该隔离"；该函数照旧读本机当前 active 小说的真实向量库/事件日志/世界观数据。语义检索（`query_similar`）本身没有相关性阈值，只要向量库非空就总会返回 top-k 近邻——于是只要本机曾经真跑过 story sandbox 攒下真实数据，`recall_context` 断言就会被真实小说原文（含敏感内容）撞穿。同一提交（`67e36b25`）新增的另外两个测试同样没 mock 这条链路，只是它们没有断言 `recall_context` 的具体值，所以没暴露——同一个坑，运气好没踩上。这类"测试在别人机器上跑很久都是绿的，换台干净/脏机器就翻车"的环境依赖泄漏，本质上是 root cause 被同批次其它测试的断言盲区掩盖了。
*   **方案**：在 `_isolated_checkpoint` fixture 里补一条 `monkeypatch.setattr("engine.story_sandbox.recall.recall_relevant_context", lambda text, **kwargs: "")`，与同一 fixture 里其它函数的隔离方式保持一致（**教训**：新增一个会触达真实磁盘/外部存储的函数调用时，凡是它所在文件的 autouse 测试夹具已经在隔离同类依赖，就该顺手把它也纳入隔离范围，而不是留给"以后哪个断言撞上了再说"）。

### 30. Cursor 无头调度冷启动竞态导致 pytest-testmon 锁死 (Headless Dispatch Cold-Start Race → Testmon Lock Deadlock)

*   **治理背景**：派发给 Cursor headless CLI 的 worktree 是全新的，没有 `.venv`/`node_modules`，更没有 pytest-testmon 的覆盖率基线 `.testmondata`。pre-commit 钩子里的 `pytest --testmon` 在这种"冷"状态下必须先跑一遍全量测试集才能建立基线（实测 3344 项测试约 190 秒），这个耗时接近甚至超过 Cursor 自身 shell 工具给单条命令设的软超时。
*   **病灶（外部调用方超时误判 → 僵尸进程互锁）**：Cursor 判定命令"超时即卡死"，尝试 `taskkill` 杀掉对应进程重试，但杀的是外层包装进程，而非真正持有 `.testmondata`（WAL 模式 SQLite）文件句柄的内层 `python.exe`——五轮重试留下五个未被回收的僵尸进程，全部还占着同一份 WAL 锁。Windows 下 `TerminateProcess` 强杀遗留的操作系统级字节区间锁不受 SQLite 自身 60 秒 `busy_timeout` 协议约束，新连接因此无限期挂起（CPU 占用归零，而非报错或重试），表现为"卡死"而非"变慢"，肉眼几乎无法与"还在正常跑"区分，只能靠进程 CPU 时间是否随真实等待推进来判定。
*   **方案**：把 testmon 基线构建挪出 commit 关键路径——`scripts/setup_worktree.py`（已是"新建 worktree 先跑一次"的既定置备入口）结尾追加一次 `pytest --testmon` 预热，等真正触发 pre-commit 钩子时基线早已就绪，只走秒级增量选测，不再有机会撞上外部调用方自己的超时窗口；`cursor_dispatch.py` 的默认派发 prompt 同步改为显式指引 Cursor 先跑这个置备脚本，而不是自行退化到从零 `uv sync`（**教训**：凡是"冷启动必然耗时且可能撞上外部超时"的一次性代价，能挪到不受调用方超时管辖的独立置备步骤，就不要留在被严格计时的关键路径里）。

### 31. 进程级单例缓存被测试单向污染，仅在全量跑时才现形 (Process-Wide Cache Poisoned by a One-Way Test Fixture)

*   **治理背景**：`context.content_packs._packs_cache` 是进程级 `LazyCache` 单例（懒加载一次、`reload_content_packs()` 才失效），扫描 `hooks/content_packs/*/hook.py` 汇总出的字段/性别/体型槽定义供全引擎读取。`tests/engine/test_cast_stance_schema.py::_isolate_baseline_packs` 为了测试"无 content pack 时的基线行为"，把 `_packs_dir` 猴子补丁指向 `/nonexistent` 再调用 `reload_content_packs()`——但 `reload_content_packs()` 只失效缓存（`LazyCache` 懒惰特性，调用它本身不触发重新计算），真正的重建发生在测试体接下来调用 `physique_slots(...)` 时，用的正是这个假路径，扫描结果 `[]` 被**缓存进这个进程级单例**。测试结束后 `monkeypatch` 只会把 `_packs_dir` 本身复原，不会主动帮你把这份被污染的缓存值再失效一次——而这个测试自己没有像 `tests/engine/test_content_packs.py` 的 `_reset_cache` autouse fixture 那样在 `yield` 之后再补一次 `reload_content_packs()`。于是这份"空 pack 列表"缓存值原样留到会话结束前的任意一次读取。
*   **病灶（诊断极难：孤立/小批量运行永远无法复现）**：只要还有任何后续测试碰巧先调用一次 `_packs()`（几乎必然，因为它是懒加载，第一个访问者就把缓存焊死），后面所有依赖 `content_packs` 数据的测试都会读到这份被污染的空值，且没有任何异常或警告——纯粹的静默数据错误。表现为 `tests/engine/test_state_derive_schema.py` 一批断言失败（`stress_level` 这类由某内容包声明的 `scored_desc` 字段"消失"，退化成未注册字段直接透传）。由于这个进程级单例只有第一次访问会触发重建，之后全靠"谁先调用"决定被污染的值能留多久，**单独跑受害文件、或跟嫌疑文件配对小范围重跑，永远无法复现**——必须是全量 3300+ 用例、且 testmon 按历史耗时重排序导致这两个文件恰好按污染所需的相对顺序执行时才会现形。排查过程中还顺带证伪了两个更复杂的假说（`test_content_packs.py` 自身隔离是否有漏洞、全局 `SCHEDULER` 单例是否因 `TestClient(app)` 的 lifespan 关闭失败而泄漏后台线程）——最终靠一个 autouse 诊断 fixture（每个用例结束后记录 `_packs_cache.peek()` 长度 + 当前 nodeid，一次全量跑出完整时间线）才在几千行日志里精确定位到"从有效值变空值"的那一个测试。
*   **方案**：把 `_isolate_baseline_packs` 从裸函数改成正经 `pytest.fixture`，`yield` 之后补一次 `cp.reload_content_packs()`（此时即便还在 `monkeypatch` 复原 `_packs_dir` 之前调用也没关系——`reload_content_packs()` 只失效不重建，真正的重建总会发生在下一个访问者调用时，那时 `_packs_dir` 已经被 `monkeypatch` 复原成真实路径）。顺带修了一个同批发现的、纯属巧合但一起复现的无关 flaky：`tests/api/test_scheduler.py::test_callback_exception_does_not_kill_loop` 用 60ms 窗口断言两个 10ms 周期任务至少各触发 2 次，同文件另一个测试同等场景给了 100ms（10 倍間隔）余量，这个只给了 6 倍，扛不住全量跑时的调度抖动，直接对齐加宽到 150ms（**教训**：任何"猴子补丁到假路径 + 让被测代码用这个假路径触发进程级单例重建"的测试，必须在 teardown 里让单例失效一次，不能只指望 `monkeypatch` 复原了输入函数就万事大吉——它复原的是"下一次读取会用什么"，不会替你处理"已经被污染、缓存住的上一次读取结果"）。

### 32. #30 的修复只搬了案发地点，没解决案情：commit 门禁彻底不跑 pytest (Relocating a Cold-Start Race Doesn't Fix It — Test Gating Moved Out of Commit Entirely)

*   **治理背景**：排查 story_sandbox"台词底稿到正文"延迟时，写完 spec+plan 派发给 Cursor headless CLI 实现（`scripts/cursor_dispatch.py`）。派发 prompt 已经按 #30 的方案，显式指引 Cursor 先跑 `scripts/setup_worktree.py` 预热 pytest-testmon 基线，再进入实现循环。跑到一半，Cursor 的 pre-commit 钩子又双叒卡死了——症状和 #30 一模一样：僵尸进程占着 `.testmondata`（WAL 模式 SQLite）的文件锁，新连接无限期挂起。
*   **病灶（"治标"方案的有效期只到下一次撞线为止）**：#30 的方案是把 testmon 基线构建从 pre-commit 关键路径挪到 `setup_worktree.py`，前提假设是"挪到那里之后，冷启动的慢不再会撞上外部调用方（Cursor 自身 shell 工具）的超时窗口"。但这个假设只挪动了**案发地点**，没缩短**案发时长**——3373+ 项全量测试建基线依然要 180～220 秒，这机器上恰好又并发跑着好几个其它 worktree 的全量测试（含另一个会话正在专门复现同一个 bug 的 `test_testmon_inmemory.py`），CPU/磁盘争抢把这次的基线构建也拖过了 Cursor 自己的超时软阈值——于是竞态原样在 `setup_worktree.py` 内部的 `pytest --testmon` 调用上重演了一次，留下的僵尸进程接着又跟 pre-commit 钩子后续触发的第二次 `pytest --testmon` 撞车，形成双僵尸互锁。**"把慢步骤挪到另一个调用方手里"不等于"消灭了慢步骤跟外部超时的竞态"——只要那个调用方自己也有软超时，竞态就会在新地点原样复现，且更难排查（两层调用栈都要挖）。**
    排查过程中还带出一个更底层、此前完全没意识到的问题：Claude 在自己的隔离 worktree 里把 `scripts/hooks/pre-commit` 改成不跑 pytest，commit 后再自测——结果新 commit 触发的钩子行为完全没变，还是老版本的全量 testmon。查 `git config core.hooksPath` 发现是一个**绝对路径**，直接指向主 checkout（`C:\...\chronos\scripts\hooks`），不是相对路径。这意味着**所有 worktree（不管是 Claude 自己的、Cursor 的、还是任何并行会话的）的每一次 commit，执行的都是主 checkout 当下签出到哪个版本的 hook 脚本，跟当前 worktree 自己已提交、已在磁盘上的 `scripts/hooks/*` 内容完全无关**——文件头部注释"修改此文件即修改全仓的提交门禁"描述的效果，实际上要等这次改动被 merge 进主 checkout 当前签出的分支后才成立，worktree 内的编辑在此之前是**静默无效**的，不报错、不提示，只会让人误以为"我改了怎么没生效"。
*   **方案**：不再试图在"冷启动必然慢"和"外部调用方超时窗口"之间找平衡点——直接把 pytest 整个搬出 commit 门禁。`scripts/hooks/pre-commit` 只保留 `reset_pipeline_state.py`（清运行时脏状态）→ `validate_agent_packages.py`（结构校验）→ `ruff` → `mypy`，全部是秒级、不碰外部状态/大规模 I/O 的检查；全量 `pytest tests/` 挪到两个真正的集成关口兜底：新增的 `scripts/hooks/pre-merge-commit`（`git merge` 生成合并提交前触发）+ 已有的 `scripts/hooks/pre-push`，merge 进 dev 或 push 出去之前必须全绿，但不再拖慢每一次中间 commit（**教训**：一个反复复现、每次都要现场排查僵尸进程的竞态类问题，"再优化一次触发时机"通常治标不治本，直接把触发时机从"高频、时间敏感的关键路径"整体移出去，比继续调参数/挪位置更可靠）。`core.hooksPath` 绝对路径共享的问题本次未动（范围外，用户后续视情况决定是否切到 `git config --worktree` + `extensions.worktreeConfig=true` 做真正的按 worktree 隔离），仅记录在案：**以后凡是"以为改了当前 worktree 的 hook/配置就该在当前 worktree 生效"的假设，先跑 `git config core.hooksPath`（或对应配置项）确认解析出来的是相对路径还是绝对路径，不要凭文件里的注释/文档字面意思想当然**。

### 33. #30/#32 之外的第三种变体：Cursor 把超时命令"转后台"而非杀死，派发脚本死等一个早已跑完的会话 (Backgrounded, Not Killed — the Dispatcher Waits on a Session That's Already Done)

*   **治理背景**：`scripts/cursor_dispatch.py` 派发一个 scheduler watchdog 的实现计划，`run_dispatch()` 用 `subprocess.run(cmd, ...)` 同步等 `cursor-agent.CMD` 这个顶层进程退出。表面症状和 #30/#32 一样——派发挂住不动，`.cursor/worktrees/<name>` 里能看到 `pytest --testmon -q` 进程 CPU 占用趋近于零、跑了近一小时。
*   **病灶（这次不是锁,是"假成功"上报 + 孤儿后台任务拖着整棵进程树不退出）**：拉 Cursor 自己落的 `--output-format stream-json` 日志逐条核对时间戳，发现 `python scripts/setup_worktree.py` 这条 shell 调用在 06:05:26 发起,06:05:57(整整 30.944 秒)就被标记 `completed`、`exitCode: 0`——但那一刻捕获到的 stdout/stderr 只到 `uv sync` 装包那一步,`setup_worktree.py::build_testmon_baseline()` 的 `print` 都还没来得及输出。查这次会话全部 30 条 shell 调用,无一例外都带 `"timeout":30000,"timeoutBehavior":"TIMEOUT_BEHAVIOR_BACKGROUND","hardTimeout":86400000`——**Cursor 的 shell 工具对每条命令都是"30 秒软超时,超了不等也不杀,直接拿当前已捕获的输出拼一个 `exitCode:0` 的'成功'结果回给 agent,真正的子进程继续在后台跑,给 24 小时硬顶兜底"**。agent 拿到这个假成功信号后完全没等,立刻开始读文件、写代码——15 分钟内正常写完、跑完（agent 自己另起的针对性）测试、提交,日志最后一行就是"commit 2af55e9b 在分支上"，agent 那头其实早就干完了。但被"转后台"那个 `pytest --testmon -q`（`setup_worktree.py` 冷启动建基线那次调用）仍是 `cursor-agent` 整棵进程树下的活子进程,`cursor_dispatch.py` 是死等这棵顶层进程退出的——孤儿不退,顶层进程树就不彻底收尾,派发脚本原地卡到天荒地老,即便 agent 逻辑上早就没事可做了。**跟 #30/#32 的区别**：那两次的病灶是"僵尸进程占着 `.testmondata` 的 WAL 锁,阻塞的是*下一次*调用";这次是"孤儿后台任务本身没在等锁、也没死锁,只是单纯还在慢慢跑,阻塞的是*这一次*派发自己的收尾等待"——2026-08-12 merge 的 testmon in-memory 后端已经把前者（WAL 锁）解决了,但对后者（Cursor 自己"转后台"的调度语义）没有作用,是同一类"冷启动全量 testmon 撞外部调用方超时"问题底下第三种独立的具体病灶。
*   **方案**：不再试图让这次冷启动"跑得够快、赶在超时前结束"（#32 已经证明这个前提本身就不稳,机器负载一高就会撞线）,而是直接问"Cursor 派发这条工作流到底需不需要这份基线"——答案是不需要：commit 门禁自 #32 起已经彻底不跑 pytest,Cursor 派发也从不 merge/push（唯二真正吃基线速度红利的两个钩子）,真正的验证靠调用方（Claude）事后手动跑 `pytest`（这次全程就是这么验证的,`ruff`/`mypy`/`pytest -p no:testmon` 全部单独手动跑,不依赖那份基线）。把 `cursor_dispatch.py::_SETUP_INSTRUCTION` 里的 `setup_worktree.py` 调用加上 `--skip-testmon`,直接去掉这个诱因,而不是继续在"怎么让 30 秒够用"上打转（**教训**：一个外部调用方的软超时语义如果是"转后台"而非"杀死",排查思路要从"这个僵尸进程卡在哪个锁上"切换成"这个后台任务的产物这次工作流到底用不用得上"——用不上就该从根上砍掉这个调用,而不是继续想办法把它塞进超时窗口里)。

### 34. 关键字实参在协程调用前抢先求值，工具返回预览慢写盘一拍 (Eager Keyword-Arg Evaluation Renders a Preview Before the Coroutine It's Passed To Ever Persists)

*   **治理背景**：用户在 setup-chat 里连续调用 `edit_world_power_system` 改力量体系词条，工具返回的确认预览里没看到新写的总起句，像是没改成功；但紧接着手动调 `list_world_power_systems` 重新读盘，读回的却是完整新文案。磁盘状态从头到尾都是对的，只有第一次调用返回的预览文本滞后一拍——初步怀疑是仓储层某个进程内缓存没有 invalidate。
*   **病灶（读代码定位到不是缓存层,是参数求值顺序）**：`world_tools.py` 里 `add_fn`/`edit_fn` 的写法是 `return await _commit_world_write(doc, changed_field=field, success_title=..., body=wo.render_list_field(field))`——`wo.render_list_field(field)` 是传给 `_commit_world_write` 的一个关键字实参表达式。Python 对函数调用求值时，**先把所有实参表达式求值完，再真正发起调用**（对协程函数同理：先求值实参构造调用，再 `await` 这个协程对象）。而 `wo.render_list_field(field)` 内部会重新 `_load_doc()` 读取仓储（`WorldRepository.get()` → `SqliteStore.get_doc()`，进程内 write-through 缓存，读到的就是当前磁盘影像）；真正的持久化 `wo.persist_world_doc(doc, ...)` 却是 `_commit_world_write` **协程体内部**才执行的下一步。于是求值顺序变成：先读旧值渲染预览 → 协程才真正落盘。仓储层的 write-through 缓存本身没有问题（`save_doc` 是先写盘再更新缓存，同步一致），根因纯粹是调用点把"渲染预览"和"发起写入"的先后关系搞反了。同一份代码里 `delete_fn` 没有这个 bug，因为它是分成两条独立语句先 `persist_world_doc(...)` 再 `render_list_field(...)`，不是作为同一个调用的关键字实参。`_make_scalar_tools` 里的 `set_fn`/`refine_fn` 也没事，因为它们传的 `body=str(doc.get(field, ""))` 直接读的是本地已被修改过的 `doc` 变量，不重新查仓储，跟持久化是否已发生无关。
*   **方案**：把 `_commit_world_write` 的 `body: str` 参数改成 `render_body: Callable[[], str]`，在函数体内部 `persist_world_doc` 成功之后再调用它生成预览文本，从根上保证"渲染"永远发生在"持久化"之后；四个调用点（`set_fn`/`refine_fn`/`add_fn`/`edit_fn`）相应改成传 lambda。顺手在 `tests/engine/setup_chat/test_world_tools.py::test_edit_world_faction` 里补了一条断言（`"新描述" in out` 且 `"旧描述" not in out`），验证过这条断言在旧代码上确实会失败（`AssertionError: assert '新描述' in '已更新势力「甲帮」。\n\n势力（共 1 条）：\n  - 甲帮：旧描述'`），修复后转绿——此前 8 个用例里只断言了磁盘落盘值（`saved["factions"][0]["desc"]`），从没断言过工具返回字符串本身的内容，这是 bug 潜伏没被测出来的直接原因。顺带排查了 `engine/setup_chat/tools.py` 里其余所有 `format_tool_done(...)` 调用点，确认它们无一例外都是渲染本地已修改变量、且在独立语句里排在持久化调用之后，没有同款问题（**教训**：把"渲染预览"这种有副作用式读取（重新查仓储/重新查磁盘）的调用，直接写成另一个协程函数的关键字实参表达式时，要留意 Python 对调用实参是"先求值全部实参、再发起调用"——如果被调用的协程内部还会先做一次写入，实参里的读操作永远抢跑在写之前；工具类测试如果只断言落盘后的仓储状态、不断言函数返回值本身，这类"返回值滞后但落盘正确"的 bug 会长期不可见）。

### 35. 内存淘汰阈值失配的表象之下，真凶是 venv 里两个从未被声明过的野包 (Stale Watermark Was a Red Herring — the Real Culprit Was Two Undeclared Packages Sitting in the venv)

*   **治理背景**：用户报了一条 Novita 生图失败日志，顺带问起"我们有没有做失败重试"——修完立绘生成重试链路后，又提到刚手动杀了一个进程，请求"启动一次项目看看这次内存占用多少"。实测 engine 进程 Working Set 高达 456MB，而 `api/services/novel_memory_scavenger.py`（每 60 秒扫描一次、超过 `MEMORY_HIGH_WATERMARK_BYTES=300MB` 就淘汰一个非焦点小说的内存态）里这个阈值的注释写着"single-novel steady-state RSS ~300MB"（2026-08-08 Chroma 迁移后校准）。456MB 常驻已经远超这个"校准基线"，意味着淘汰逻辑从进程刚起来那一刻就会持续判定"超支"，每分钟淘汰一本后台小说、淘汰完 RSS 也降不下 300MB，陷入永久空转——这正是用户担心的"内存淘汰机制会一直触发"。
*   **病灶（分阶段插桩排查，层层剥掉表象才见到真凶）**：
    1. 第一轮用分阶段 import 探针测得"空跑到能接请求"的地板是 315MB，其中 `langchain_openai` 一项就吃掉 215MB、`tiktoken` 加载编码表再吃 38MB，而 chronos 自己的全部路由/hooks/skills 代码只占 6MB——初步结论是"SDK 依赖体积本身就是固定税，300MB 阈值从校准那天起就没有余量"。
    2. 用户追问"能不能换更轻量的 openai 协议客户端"，于是做对照实验：裸 `openai` SDK（不经 `langchain_openai`）导入+实例化只要 **15MB**，但把 `langchain_openai` 叠加在已加载的 `openai` 之上依然要再吃 **206MB**——证明贵的根本不是 openai 协议/SDK 本身，是 `langchain_openai` 自己的某条依赖链。
    3. 用 `python -X importtime` 定位到 `langchain_openai.chat_models.azure` 顶着一条 `transformers.tokenization_utils_tokenizers → transformers.modeling_gguf_pytorch_utils → torch` 的重量级链路；再用 `builtins.__import__` hook 精确抓到调用栈，锁定真正的触发点其实在 **`langchain_core`**（不是 `langchain_openai`）自己的 `language_models/base.py` 第 42 行：`try: from transformers import GPT2TokenizerFast ... except ImportError: _HAS_TRANSFORMERS = False`——一段设计上就该优雅降级的可选兜底 tokenizer 探测代码。
    4. 检查这台机器的 `.venv`：`torch==2.12.0`、`transformers==5.11.0` **物理装在里面**，但 `uv.lock`/`pyproject.toml` 一个字都没提到它们，`src/` 下 chronos 自己的代码也从未 import 过两者。两个包的 `dist-info/INSTALLER` 元数据都写着 `uv`、时间戳 2026-07-29——即两周半前有人直接跑了类似 `uv pip install torch transformers` 的命令（`uv pip install` 是 uv 的 pip 兼容层，只装进当前 venv、完全不碰 `pyproject.toml`/`uv.lock`，区别于会同步写锁文件的 `uv add`），大概率是某次试验本地 embedding/tokenizer 之类功能后遗忘清理，此后每次进程启动，只要触达 `langchain_core.language_models.base` 这条 import 路径（构建任意一个真实 `ChatOpenAI` 实例就会触达），就被这段"能兜底就兜底"的代码顺手捡起来，平白多背 200+MB，且完全不会以任何错误/警告的形式暴露给开发者——纯粹的"venv 里放了个从没被声明过的包，代码恰好写了一段会主动去找它的兜底逻辑"式静默膨胀。
*   **方案**：`uv pip uninstall torch torchgen transformers`（零代码改动——`langchain_core` 那段 `try/except ImportError` 本来就是为"没装就降级"设计的，不需要碰它一行）。卸载后验证：`_HAS_TRANSFORMERS` 正确降级为 `False`；真实 engine 进程 Working Set 从 456MB 降到 **286MB**（降约 37%）。内存淘汰阈值本身是否还需要重新校准（新基线 286MB vs 现有 300MB 已经很接近，是否还需要抬高留余量）留待下一步单独决定，未包含在本次改动里（**教训**：排查"内存/性能突然变差"类问题时，"调大一个看似过时的阈值"往往是最省事但可能治标不治本的选项——这次如果一开始就直接把 300MB 改成 700MB 止血，这个从未被声明过的 400MB 级野包依赖会被彻底掩盖，且会在每一台装过同款野包的机器上反复以"阈值又不够用了"的面目重演；分阶段插桩测量 + 对照实验 + import hook 精确抓调用栈，比凭经验调参数更容易把"表面症状"和"真正病灶"分开）。

---

## 🗺️ 四、 总结：迈向下一代本地叙事工作站


从初期利用大模型拼接零散文本，到如今通过 **dialogue mode 整章图**、Setup Chat 构建期交互、进程内 repositories 与 SQLite 检查点续写，Chronos 已演进至 **V13**。本项目的演进史，本质上就是一部 **“如何利用软件工程的确定性，去规训与约束大语言模型非确定性”** 的最佳实践。

通过单进程多任务、交互前移、数据层内聚与容灾体系，Chronos 正在蜕变为一套高性能、本地优先 (Local-First) 的**通用叙事编排工作站**。
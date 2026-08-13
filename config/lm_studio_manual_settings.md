# LM Studio 必须手动设置的参数

以下参数控制**模型加载与服务器行为**，不通过 API 传递，必须在 LM Studio UI 里设置，代码无法覆盖。

---

## 模型加载参数（加载模型时设置）

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| GPU Offload（GPU 层数） | 全部层（拉满） | Q5_K_M 约 6.8G，16G VRAM 完全装得下，全层推理最快 |
| Context Length（n_ctx） | 16384 | 输入段落上限约 2000 中文字，16K 足够留给系统提示+输出 |
| Flash Attention | ✅ 打开 | 节省约 20% VRAM，加速长上下文推理 |
| Prompt Caching | ✅ 打开 | System Prompt 不变时避免重复编码，第二轮起秒出 |
| Speculative Decoding | ❌ 关闭 | 蒸馏小模型不需要，开了反而引入额外延迟 |
| Mirostat | ❌ 关闭 | 会和 Top P / Top K 采样冲突，同时开启结果不可预测 |

---

## 不需要在 LM Studio 里设置的参数

以下参数已由代码通过 API 请求传入，LM Studio UI 里的对应值会被覆盖，设不设都没有效果：

- Temperature
- Top P
- Top K
- Repeat Penalty
- Repeat Last N
- Min P

切换这些参数的预设方式：修改 `config/config.json` 中的 `llm.local_preset`（A/B/C/D/E）。

---

## System Prompt

LM Studio 的 System Prompt 框**留空**。Pipeline 已通过 agent 文件注入系统提示，在 LM Studio 里粘贴会产生冲突。

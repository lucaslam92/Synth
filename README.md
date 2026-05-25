# Synth

跨仓库代码图谱 → 自然语言功能描述合成工具。

读取 [graphify](https://github.com/your-org/graphify) 生成的代码图谱，通过大模型自动生成三个层级的描述：**模块 → 服务 → 跨服务业务功能**，输出为 Markdown / JSON 报告。

---

## 安装

```bash
git clone https://github.com/your-org/synth
cd synth
./install.sh          # 含 Leiden 社区检测（推荐）
./install.sh --no-leiden  # 仅核心依赖，速度更快
```

> 需要 Python 3.10+。Homebrew 用户无需额外操作，脚本自动处理系统 Python 限制。

---

## 第一步：配置 API Key

Synth 调用大模型 API 生成描述，根据你使用的模型选择对应的配置方式。

### Anthropic Claude（默认）

1. 前往 [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) 创建 API Key
2. 配置到环境变量：

```bash
# 临时生效（当前终端会话）
export ANTHROPIC_API_KEY=sk-ant-...

# 永久生效（二选一）
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.zshrc   # zsh
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc  # bash
source ~/.zshrc  # 重新加载
```

验证是否生效：
```bash
echo $ANTHROPIC_API_KEY   # 应输出你的 Key
```

---

### OpenAI（GPT-4o 等）

1. 前往 [platform.openai.com/api-keys](https://platform.openai.com/api-keys) 创建 API Key
2. 配置环境变量：

```bash
export OPENAI_API_KEY=sk-...
```

3. 在 `synth.toml` 中指定 provider：

```toml
[llm]
provider = "openai"
model    = "gpt-4o"
```

---

### 智谱 GLM

1. 前往 [open.bigmodel.cn](https://open.bigmodel.cn) 创建 API Key
2. 在 `synth.toml` 中配置：

```toml
[llm]
provider = "openai-compatible"
model    = "glm-4-flash"
base_url = "https://open.bigmodel.cn/api/paas/v4/"
api_key  = "your-zhipuai-key"
```

---

### DeepSeek

1. 前往 [platform.deepseek.com](https://platform.deepseek.com) 创建 API Key
2. 在 `synth.toml` 中配置：

```toml
[llm]
provider = "openai-compatible"
model    = "deepseek-chat"
base_url = "https://api.deepseek.com/v1"
api_key  = "your-deepseek-key"
```

---

### 阿里云百炼（Qwen）

1. 前往 [bailian.console.aliyun.com](https://bailian.console.aliyun.com) 获取 API Key
2. 在 `synth.toml` 中配置：

```toml
[llm]
provider = "openai-compatible"
model    = "qwen-turbo"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
api_key  = "your-dashscope-key"
```

---

### Ollama（本地，无需 API Key）

1. 安装 [Ollama](https://ollama.com) 并拉取模型：

```bash
brew install ollama
ollama pull qwen2.5:7b
ollama serve  # 启动本地服务
```

2. 在 `synth.toml` 中配置：

```toml
[llm]
provider = "openai-compatible"
model    = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
api_key  = "ollama"   # 随意填写，本地不校验
```

---

> **安全提示**：`api_key` 也可以直接写在 `synth.toml` 的 `[llm]` 块中，但请确保该文件已加入 `.gitignore`，避免密钥泄露到代码仓库。

---

## 第二步：创建配置文件

```bash
synth init          # 在当前目录生成 synth.toml 模板
$EDITOR synth.toml  # 编辑，填写仓库路径
```

`synth.toml` 最小示例：

```toml
[llm]
provider = "anthropic"       # 或 openai / openai-compatible
model    = "claude-opus-4-6"

[[repos]]
name  = "user-service"
graph = "../user-service/graphify-out/graph.json"
type  = "microservice"

[[repos]]
name  = "order-service"
graph = "../order-service/graphify-out/graph.json"
type  = "microservice"
```

> `graph` 指向该仓库运行 `graphify` 后生成的 `graph.json`。

---

## 第三步：运行

```bash
synth run           # 生成描述报告
synth show          # 在终端查看报告
synth status        # 查看配置和缓存状态
synth clean         # 清空 LLM 缓存
```

输出文件默认写入 `synth-out/feature_description.md`。

---

## 缓存机制

Synth 对每次 LLM 调用结果按内容哈希缓存（`.synth-cache/`），**代码未变化时直接复用，无需重复调用 API**。

```bash
synth clean           # 清空全部缓存
synth clean modules   # 只清空模块级缓存
synth clean repos     # 只清空服务级缓存
synth clean features  # 只清空跨服务功能缓存
```

---

## 开发

```bash
pip install -e ".[dev]"
pytest          # 运行测试
```

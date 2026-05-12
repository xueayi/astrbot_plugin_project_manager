# astrbot_plugin_project_manager

飞书 + QQ 双向项目管理插件，基于 LLM 多步流水线连接 QQ 群聊与飞书云文档。

## 功能概览

| 功能 | 说明 |
|------|------|
| **听** | 实时收集 QQ 群消息，定时通过 LLM 提取项目进度、人员分配、新增问题等结构化信息 |
| **记** | 将 LLM 提取结果自动同步更新到飞书云文档（项目管理手册 + 项目公告板） |
| **报** | 定时或按需向 QQ 群发送项目进度报告，附飞书文档链接 |
| **催** | 在报告周期中检查临期任务，@对应 QQ 成员催促 |

## 前置要求

- [AstrBot](https://github.com/AstrBotDevs/AstrBot) >= v4.5.0
- OneBot v11 协议端（NapCat / Lagrange 等），用于收发 QQ 群消息
- [lark-cli](https://open.feishu.cn/document/no_class/mcp-archive/feishu-cli-installation-guide.md)（`@larksuite/cli`），用于读写飞书云文档
- 至少一个 LLM Provider 已在 AstrBot 中配置

### 安装 lark-cli

```bash
npm install -g @larksuite/cli
npx -y skills add https://open.feishu.cn --skill -y
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

## 安装

将插件克隆到 AstrBot 的插件目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/xueayi/astrbot_plugin_project_manager
```

重启 AstrBot 或在 WebUI 中重载插件即可。

## 配置

### Web 管理面板

插件自带管理面板，在 AstrBot Dashboard 的插件详情页中打开。支持：

- **多项目管理**：同时配置多个项目，每个项目独立绑定飞书文档、QQ 群、管理员和定时任务
- **全局设置**：LLM 模型选择、lark-cli 路径、消息保留天数
- **项目配置**：
  - 飞书管理手册 URL 和公告板 URL
  - 关联的 QQ 群（支持多群）
  - 项目管理员 QQ 列表
  - 过滤成员（如机器人 QQ）
  - 人员映射表（飞书名称 ↔ QQ 号，用于精准催促）
  - 自定义摘要和报告的 Cron 表达式
  - 催促临期天数阈值

### 项目配置示例

```json
{
  "name": "项目 Alpha",
  "lark_handbook_url": "https://xxx.feishu.cn/docx/...",
  "lark_bulletin_url": "https://xxx.feishu.cn/docx/...",
  "qq_groups": ["123456789"],
  "admins": ["111222333"],
  "filtered_members": ["bot_qq_id"],
  "member_mapping": { "张三": "444555666" },
  "schedule": {
    "summary_cron": "0 18 * * *",
    "report_cron": "0 9 * * *",
    "urge_threshold_days": 3
  }
}
```

## QQ 群命令

| 命令 | 权限 | 说明 |
|------|------|------|
| `pm status` | 所有人 | 查看当前项目简要状态 |
| `pm report` | 管理员 | 手动触发完整报告 |
| `pm sync` | 管理员 | 手动触发消息摘要 + 飞书文档更新 |
| `pm update <内容>` | 管理员 | 直接将内容追加到飞书公告板 |
| `pm urge` | 管理员 | 手动触发催促检查 |

> 管理员权限根据项目配置中的 `admins` QQ 列表判断，与 AstrBot 全局管理员无关。

## 技术架构

```
听: QQ 群消息 → 过滤 → SQLite → LLM 摘要 → 结构化 JSON
记: 结构化 JSON → 读取飞书文档 → LLM 生成更新指令 → lark-cli 执行更新
报: 读取飞书文档 → LLM 生成报告 → 发送到 QQ 群
催: 读取飞书文档 → LLM 检测临期任务 → @成员催促
```

- **飞书集成**：通过 subprocess 调用 lark-cli，封装为抽象层便于后续迁移
- **LLM 交互**：多步流水线（提取 → 生成更新指令 → 生成报告），各步独立可调试
- **消息存储**：aiosqlite 异步 SQLite
- **定时任务**：AstrBot CronJobManager，每个项目独立调度

## 目录结构

```
astrbot_plugin_project_manager/
├── main.py                  # 插件入口
├── metadata.yaml
├── requirements.txt
├── _conf_schema.json
├── core/
│   ├── config.py            # 多项目配置管理
│   ├── storage.py           # SQLite 异步封装
│   └── lark_bridge.py       # lark-cli subprocess 封装
├── listener/
│   └── collector.py         # 群消息收集器
├── llm/
│   ├── prompts.py           # prompt 模板
│   ├── summarizer.py        # Step 1: 消息 → 结构化 JSON
│   ├── doc_updater.py       # Step 2: 文档更新指令生成
│   └── report_generator.py  # Step 3: 报告 + 催促生成
├── recorder/
│   └── recorder.py          # 听→记 pipeline 编排
├── reporter/
│   └── reporter.py          # 报告发送 + 催促检查
├── web_api.py               # Web 管理面板后端
└── pages/manager/           # Web 管理面板前端
```

## License

MIT

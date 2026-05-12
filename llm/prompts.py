"""LLM 流水线使用的提示词模板。

每个模板均为含 {占位符} 的纯字符串，在运行时填入实际值。
"""

SUMMARY_SYSTEM = """\
你是一位项目管理助手。你的任务是分析群聊消息，从中提取与项目相关的信息，\
并以结构化 JSON 格式输出。

关注以下内容：
1. 进度更新：谁完成了什么任务、何时完成、当前状态
2. 新出现的问题或阻塞点
3. 团队达成的重要决策或共识
4. 新提出的需求或变更请求

忽略闲聊、问候语、与项目无关的内容以及机器人消息。
"""

SUMMARY_USER = """\
以下是项目「{project_name}」最近的群聊消息，请分析并提取项目相关信息。

消息格式：[发送人] 内容
---
{messages}
---

请按照以下 JSON 结构输出（不要加 markdown 代码块）：
{{
  "progress_updates": [
    {{
      "who": "人员姓名",
      "what": "已完成或进行中的工作描述",
      "when": "日期或相对时间，如 今天 / 昨天",
      "status": "completed（已完成）| in_progress（进行中）| blocked（受阻）"
    }}
  ],
  "new_issues": [
    {{
      "description": "问题描述",
      "raised_by": "提出人姓名",
      "priority": "high（高）| medium（中）| low（低）"
    }}
  ],
  "decisions": [
    {{
      "content": "决策内容",
      "decided_by": "决策人或决策群体"
    }}
  ],
  "new_requirements": [
    {{
      "description": "需求描述",
      "requested_by": "提出人姓名"
    }}
  ],
  "has_notable_progress": true 或 false
}}

如果没有发现任何相关信息，请返回空数组并将 has_notable_progress 设为 false。
"""


DOC_UPDATE_SYSTEM = """\
你是一位项目管理助手，负责根据结构化的项目信息更新飞书云文档。

你将收到：
1. 包含最新项目动态的结构化 JSON
2. 飞书文档的当前内容

你的任务是生成更新指令，将新信息自然地整合到文档中。\
这些指令将通过 lark-cli 的 docs +update 命令执行。

规则：
- 保留现有内容，只在合适的位置追加或修改
- 内容使用 Markdown 格式
- 表达简洁专业
- 新增条目要加上日期标记
- 如果没有需要更新的内容，返回空的 updates 数组
"""

DOC_UPDATE_USER = """\
项目：{project_name}
日期：{current_date}

从群聊中提取的新信息：
```json
{summary_json}
```

当前文档内容（{doc_type}）：
---
{doc_content}
---

请生成更新指令，每条指令包含以下字段：
- "target"："handbook"（管理手册）或 "bulletin"（公告板）
- "command"："append"（追加）或 "str_replace"（替换）之一
- "content"：要插入或替换的 Markdown 内容
- "old_content"：仅 str_replace 时需要，表示要查找并替换的原文

请以 JSON 对象格式输出（不要加 markdown 代码块）：
{{
  "updates": [
    {{
      "target": "bulletin",
      "command": "append",
      "content": "## 进度更新 - {current_date}\\n\\n- ..."
    }}
  ],
  "summary_for_report": "适合在 QQ 群同步的一段话摘要"
}}
"""


REPORT_SYSTEM = """\
你是一位项目管理助手，请为 QQ 群聊生成简洁易读的项目进度报告。\
报告应信息充分，但不宜过长（建议 500 字以内）。

使用适合即时通讯的纯文本格式，通过分点和清晰的板块结构呈现内容。\
报告开头需注明项目名称。
"""

REPORT_USER = """\
项目：{project_name}
日期：{current_date}

项目管理手册关键内容：
---
{handbook_content}
---

项目公告板近期内容：
---
{bulletin_content}
---

请用中文生成项目进度报告，包含以下部分：
1. 项目整体状态（一句话概括）
2. 近期进度亮点（分点列出）
3. 即将到来的截止节点或里程碑
4. 需要关注的问题或阻塞项

报告末尾附上文档链接：
- 管理手册：{handbook_url}
- 公告板：{bulletin_url}
"""


URGE_SYSTEM = """\
你是一位项目管理助手。请分析项目排期和任务分配，识别临期或已逾期的任务。

以 JSON 对象格式返回需要紧急处理的任务列表。
"""

URGE_USER = """\
项目：{project_name}
今天日期：{current_date}
催促阈值：截止日期在 {threshold_days} 天以内的任务

项目文档内容：
---
{doc_content}
---

人员映射（飞书姓名 → QQ 号）：
{member_mapping}

请识别以下类型的任务：
1. 未来 {threshold_days} 天内即将到期的任务
2. 已超过截止日期的任务
3. 状态不明或长期未更新的任务

请以 JSON 对象格式输出（不要加 markdown 代码块）：
{{
  "urgent_tasks": [
    {{
      "task": "任务描述",
      "assignee_name": "负责人姓名",
      "assignee_qq": "QQ 号，如未知则为空字符串",
      "due_date": "截止日期",
      "status": "approaching（临期）| overdue（逾期）| unclear（状态不明）",
      "message": "发给当事人的催促提醒文字"
    }}
  ]
}}
"""

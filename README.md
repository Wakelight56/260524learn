# AutoChat — 青柳冬弥 QQ 角色扮演机器人

基于 QQ（NapCat/OneBot v11）的角色扮演聊天机器人，扮演《Project SEKAI》中的青柳冬弥（Aoyagi Touya）。

## 功能

- **角色扮演** — 基于 DeepSeek / Claude API 的角色对话，符合青柳冬弥的人物设定
- **管线架构** — 5 阶段 Pipeline（唤醒 → 权限 → 限流 → AI 处理 → 装饰），可扩展
- **情绪追踪** — 分析对话情绪（心情/强度/亲近度），注入上下文影响回复
- **记忆消退** — 超出上下文限制后自动压缩旧消息为摘要，保留关键信息
- **知识库检索** — CJK 分词检索剧情知识，减少角色设定偏差
- **白名单管理** — 通过聊天指令管理允许使用 bot 的用户/群聊
- **日常行程** — 根据当前时间注入冬弥的日常活动上下文
- **插件系统** — 支持热加载插件（清空记忆、白名单、重启、帮助等）

## 架构

AutoChat 的管线/插件架构参考了 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的设计思路。

### 组件

```
src/
├── bot.py                 # 主控制器
├── config_manager.py      # 配置管理
├── emotion/tracker.py     # 情绪追踪
├── event_bus.py           # 事件总线
├── knowledge/
│   ├── character.py       # 角色 system prompt
│   ├── schedule.py        # 日常行程
│   └── retriever.py       # 知识库检索
├── pipeline/
│   ├── scheduler.py       # 管线调度器
│   ├── stage.py           # 抽象阶段
│   └── stages/            # 各阶段实现
├── platform/
│   ├── base.py            # 平台适配器抽象
│   └── sources/napcat.py  # OneBot v11 / NapCat 实现
├── plugin/
│   ├── manager.py         # 插件管理器
│   └── builtins/          # 内置插件
├── provider/              # LLM 提供商（OpenAI / Claude）
└── store/memory.py        # 记忆存储 + 消退
```

## 部署

1. 配置 `config/config.json` 中的 API key 和 QQ 账号
2. 运行 NapCat Docker 容器作为 QQ 协议端
3. 启动 bot：`python main.py`

## 声明

本项目**仅为学习和个人使用**，不提供任何形式的技术支持或担保。

本项目参考了 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的架构设计（管线模式、插件系统、事件驱动），在此表示感谢。

所有角色设定（青柳冬弥及相关角色）版权归 © SEGA / Colorful Palette / Project SEKAI 所有。

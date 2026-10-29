# 群聊身份标注（AstrBot 插件）

## 作用

在每次群聊 LLM 请求前，从 AstrBot 的 `platform_message_history` 中读取最近消息，注入一个带稳定 QQ 号的上下文块：

```text
[12:34] 昵称A (QQ:123456): 内容
[12:35] 昵称B (QQ:654321): 内容
```

这样即使两个人昵称相同、有人改名，模型也能按 QQ 号区分。

## 特点

- 不修改 AstrBot 核心文件
- 不替换原有群聊上下文，只补充身份块
- 只对群聊生效，私聊不注入
- 默认最近 20 条，每条最多 160 字，可在插件配置里调整
- 注入内容带边界标记，用户消息里的 `<` / `>` 会被替换，避免破坏提示词结构

## 安装位置

```text
/AstrBot/data/plugins/astrbot_plugin_group_identity
```

对应宿主机：

```text
/opt/bots/astrbot/data/plugins/astrbot_plugin_group_identity
```

安装后重启 AstrBot，或通过插件管理页重载。

## 配置

| 配置 | 默认 | 说明 |
|---|---:|---|
| `enabled` | true | 是否启用 |
| `max_messages` | 20 | 注入最近多少条 |
| `max_chars_per_message` | 160 | 每条最多字符数 |

## 注意

- 依赖 AstrBot 已经开启 `group_message_history_enable`，否则平台消息历史为空，插件不会注入。
- 群聊身份信息来自 `sender_id` / `sender_name`，显示名可以改，QQ 号是稳定身份。
- 这是补充层，不替代原有群聊上下文；如果原上下文里昵称重复，模型仍可能看到旧昵称，但会同时看到本插件的 ID 标注。

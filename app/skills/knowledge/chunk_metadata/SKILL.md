# chunk_metadata

任务：基于原始 `content` 生成 `title`、`summary` 和 `chunk_type`。

- title 简洁准确，表达核心语义，不增加判断。
- summary 可压缩表达，但不得新增规则、数字、条件，不得泛化案例或改变确定性。
- chunk_type 只能是：`principle`、`market_environment`、`stock_selection`、`entry_rule`、
  `exit_rule`、`position_management`、`risk_management`、`intraday`、`case`、`review`、
  `asset_allocation`、`fund`、`futures`、`macro`、`industry`、`other`。

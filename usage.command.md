# /usage

查询当前 WorkBuddy 用量（上下文 token、额度消耗、今日合计）。

请调用 `token_usage` 工具，scope 按以下选取：

- 用户只说"用量"/"用了多少"/"usage"且未指定范围 → `now`
- 提到"今天"/"今日" → `today`
- 提到"最近 N 天" → `days:N`
- 提到某个项目/目录 → `workspace:<关键字>`
- 提到某次会话 → `session:<id 前缀>`

把工具返回的文本原样转述给用户即可。
# Triage Labels

技能用五个规范化的**状态**角色（state role）说话；下表把角色映射到本仓库 issue tracker 里实际使用的标签字符串。

| 技能里的角色 | 本仓库的标签 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 维护者需要评估这张票 |
| `needs-info` | `needs-info` | 等待报告人补充信息 |
| `ready-for-agent` | `ready-for-agent` | 规格已写全，可交给 AFK agent 直接处理 |
| `ready-for-human` | `ready-for-human` | 需要人工实现 |
| `wontfix` | `wontfix` | 不做 |

另有**分类**角色（category role），用 GitHub 自带的两个标签：`bug`（坏了/异常）、`enhancement`（新功能或改进）。分流过的票各带一个分类角色加一个状态角色。

当技能提到某个角色（例如「打上 AFK 就绪的分流标签」）时，用右列对应的标签字符串，不要新建同义标签。

标签改过名字时，只改右列，别动左列的角色名。

## Wayfinder 标签

`wayfinder` 技能用同一套 tracker，另外要求这五个标签存在：

| 标签 | 用途 |
| --- | --- |
| `wayfinder:map` | 地图本身：一张 map issue 当索引（Destination / Notes / Decisions so far / Not yet specified / Out of scope） |
| `wayfinder:research` | 研究型票：读文档 / 三方 API / 仓内资料，产出一个待定决定所依赖的事实 |
| `wayfinder:prototype` | 原型型票：做便宜的粗糙产物，把「应该长什么样」的讨论具体化 |
| `wayfinder:grilling` | 对话题：把模糊的想法问清（默认类型） |
| `wayfinder:task` | 任务型票：不为决策本身、而是为了能开始讨论必须先做掉的手工活 |

子票挂在 map 上，类型标签与 `wayfinder:map` 不同轴：一张子票只带一种 `wayfinder:<type>`。

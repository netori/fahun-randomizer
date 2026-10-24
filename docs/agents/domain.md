# Domain Docs

本仓库的域文档布局已在初始化时与用户确认为 **multi-context**（子项目各一份 `GLOSSARY.md`，根目录一份 `GLOSSARY-MAP.md`）。

## 探索代码库之前先读这些

- 根目录的 **`GLOSSARY-MAP.md`**：它指向每个 context 的 `GLOSSARY.md`；读与本次主题相关的那几份，而不是全部。
- **`docs/adr/`**：读涉及你即将改动区域的 ADR。multi-context 仓库里还要看各子项目自己的 `<子项目>/docs/adr/`，那是 context 级决定。

这些文件现在**还没有**建：本次初始化不创建 `GLOSSARY-MAP.md` 与各子项目的 `GLOSSARY.md`，留到第一次真正写下词条时再建，届时由根目录的 `GLOSSARY-MAP.md` 指向它们。旧名（`CONTEXT.md` / `CONTEXT-MAP.md`）在这个仓库里没有出现过，因此本次无需改名。

任何一份不存在时都**安静地往下走**：不提示缺失、不建议事先新建。`/domain-modeling` 技能（经 `/grill-with-docs`、`/improve-codebase-architecture` 触达）会在真的定下术语或决定时才懒建它们。

## 文件结构

multi-context 仓库（根目录存在 `GLOSSARY-MAP.md`）：

```
/
├── GLOSSARY-MAP.md                    ← 索引：指向下面每一份 GLOSSARY.md
├── docs/adr/                          ← 系统级决定
└── <子项目>/
    ├── GLOSSARY.md
    └── docs/adr/                      ← 这个 context 自己的决定
```

## 用词表里的词汇

输出里出现领域概念时（issue 标题、重构提案、假设、测试名），用 `GLOSSARY.md` 里定义的那个词，不要漂移到词表明确回避的同义词。

需要的概念词表里还没有，这本身是个信号：要么你在发明这个项目不用的语言（那就重新想），要么这里确实有个洞（记下来交给 `/domain-modeling`）。

## 与 ADR 冲突时要明说

输出与既有 ADR 相悖时，明确点出来，不要悄悄盖过：

> _与 ADR-0007（事件溯源订单）冲突，但值得重开，因为……_

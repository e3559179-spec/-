# 经典原著伴读与理解追踪

主要用于马克思主义经典原著阅读，也可用于其他需要细读的理论经典。

你主导阅读，助手随时答疑；读完后逐段讲解，通过你的实际表达追踪理解变化，并积累复盘和总结材料。

## 当前阶段

第二阶段：已在基础入口、来源规则和记录模板之上，细化文本理解方法、随读答疑与读后逐段讲解。解释需要区分文本明示、助手重建和仍不确定之处；理解检查以原文为依据，允许有根据的不同读法。

当前保存流程由具备文件读写能力的助手执行。持久化辅助程序、完整的理解追踪流程和总结文档流程仍待后续迭代；方法规则不保证每次解释正确。

- [Skill 入口](skills/classic-reading-companion/SKILL.md)
- [原文来源与定位](skills/classic-reading-companion/references/source-rules.md)
- [怎样从原文形成解释](skills/classic-reading-companion/references/reading-method.md)
- [随读答疑与逐段讲解流程](skills/classic-reading-companion/references/reading-workflows.md)
- [记录格式与保存、续读规则](skills/classic-reading-companion/references/record-schema.md)

维护时可使用 [第二阶段情境检查](evaluations/stage-2-reading-cases.md)。其中区分静态规则审阅与实际模型运行，不把格式检查称为教学效果验证。

## 使用约定

将 `skills/classic-reading-companion/` 作为完整 Skill 目录交给支持该格式的运行环境加载。安装和调用方式取决于实际使用的平台；仅把仓库放在 GitHub 上不会自动启用 Skill。

开始时提供书名、正在读的原文或文件，以及已知版本信息。可以直接说：“这句话什么意思”“这一段读完了”“检查一下我的理解”“今天读到这里”“继续上次的位置”。

个人阅读数据默认保存在阅读工作目录的 `reading-data/<book-id>/`，与 Skill 安装目录分开。首次使用会告知实际绝对路径；跨对话或设备续读时，需要让运行环境能访问同一数据目录。不能读写文件的环境只能提供待手动保存的记录，不能保证自动续读。

本仓库只分发规则与空白模板，不自动上传个人阅读数据。`.gitignore` 忽略默认 `reading-data/` 目录；用户自定义路径时也应保持个人数据与分发文件分离。

## 后续顺序

1. 理解检查与追踪：细化反馈证据、问题分类和重新打开问题的条件。
2. 持久保存与续读：完善保存辅助工具、失败恢复和实际续读验证。
3. 章节复盘与全书总结：基于实际覆盖范围和学习记录生成 Markdown 文档。

第一版不以知识图谱或自动文献搜集为前提。

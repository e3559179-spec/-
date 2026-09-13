# 经典原著伴读与理解追踪

主要用于马克思主义经典原著阅读，也可用于其他需要细读的理论经典。

你主导阅读，助手随时答疑；读完后逐段讲解，通过你的实际表达追踪理解变化，并积累复盘和总结材料。

## 当前阶段

V1.1：在已完成的五阶段基础上，强化难点诊断、分层讲解、必要前置知识与重讲流程。用户仍不懂时检查上一版解释并改变讲法，保留已理解部分，帮助用户回到原文理解剩余关系。保存、续读和总结沿用现有工具与记录格式。

本轮为伴读规则更新，附 [V1.1 难点伴读验证案例](evaluations/v1.1-teaching-cases.md)。已完成静态规则与文件检查；真实原文的三至五处试读由用户验证，尚不能宣称讲解效果已提升。

第一版五项核心能力已形成完整流程：随读答疑、读后讲解、理解追踪、持久保存、复盘与总结。工具需要运行助手主动调用，不会在聊天结束后自行运行，也不自动同步设备。原文解释和文稿内容由助手依据材料撰写和核对；程序测试不证明教学评价或总结内容正确。

- [Skill 入口](skills/classic-reading-companion/SKILL.md)
- [原文来源与定位](skills/classic-reading-companion/references/source-rules.md)
- [怎样从原文形成解释](skills/classic-reading-companion/references/reading-method.md)
- [随读答疑与逐段讲解流程](skills/classic-reading-companion/references/reading-workflows.md)
- [理解检查与理解变化追踪](skills/classic-reading-companion/references/understanding-workflow.md)
- [记录格式与保存、续读规则](skills/classic-reading-companion/references/record-schema.md)
- [持久保存与续读工具](skills/classic-reading-companion/references/persistence-workflow.md)
- [章节复盘与全书总结](skills/classic-reading-companion/references/review-workflow.md)

维护时可使用 [第二阶段情境检查](evaluations/stage-2-reading-cases.md)、[第三阶段情境检查](evaluations/stage-3-understanding-cases.md) 和 [总结情境检查](evaluations/stage-5-review-cases.md)。其中区分静态规则审阅、程序测试和实际模型运行，不把格式检查称为教学效果验证。

## 复盘和总结

用户可以直接说“这一章读完了，做个复盘”或“这本书读完了，生成总结文档”。助手先固定实际记录依据，再核对原文、完成撰写和内容审阅，最后封存 Markdown 文稿。提纲和空白模板不作为完成的总结交付。

```sh
python skills/classic-reading-companion/scripts/review_document.py prepare --book-dir "reading-data/my-book-v1" --kind book
```

准备工具返回记录包及草稿路径；随后由助手撰写正文，并按 [总结流程](skills/classic-reading-companion/references/review-workflow.md) 调用 `finalize`，在该书 `reports/` 下保存独立版本的文稿、依据记录包和哈希清单。它不会替助手理解原著，不会自动判定正文正确，也不会把未完成的章节补写成已伴读。

报告生成不会改变阅读进度或理解状态，重复生成不覆盖旧文稿；撰写期间记录更新时须重新核对。记录包包含本书完整学习记录，不随正文自动公开到 GitHub。

## 保存和续读

需要 Python 3，无需额外安装依赖。默认数据位于阅读工作目录，与 Skill 安装目录分开；从仓库根目录可运行：

```sh
python skills/classic-reading-companion/scripts/reading_store.py init --book-dir "reading-data/my-book-v1" --title "实际书名"
python skills/classic-reading-companion/scripts/reading_store.py load --book-dir "reading-data/my-book-v1"
```

助手根据 `load` 返回的完整记录生成候选文件，用当前保存 ID 和状态令牌调用 `save`。详细命令与异常处理见 [操作说明](skills/classic-reading-companion/references/persistence-workflow.md)。不要直接改正式 JSON 镜像，也不要将整个 load 响应作为进度文件。

每次保存先写入完整快照，再更新当前版本指针，最后刷新两份常用 JSON。进程中断后可以从完整快照恢复。手工修改、旧会话或损坏记录不会被静默覆盖；需要先核对或显式恢复。快照不是防止磁盘损坏的外部备份，跨设备续读应取得完整数据目录。

## 记录校验

[校验工具](skills/classic-reading-companion/scripts/validate_tracking.py) 只依赖 Python 3 标准库，不修改输入文件。从仓库根目录运行：

```sh
python skills/classic-reading-companion/scripts/validate_tracking.py "reading-data/<book-id>/understanding.json"
python -m unittest discover -s tests -p "test_*.py" -v
```

将示例路径中的 `<book-id>` 替换为实际目录名。支持 `--json` 输出错误和提醒；返回码 0 表示所检查约束满足，1 表示约束失败，2 表示无法读取有效 JSON。它不是完整 JSON Schema 校验器，不能核验原文或用户表达真实性，也不能判断论证是否成立。旧格式信息不足时会提醒核对，不自动补写历史。

测试使用虚构记录和隔离临时目录，不读写个人阅读数据。累计 54 项程序测试通过，覆盖记录校验、持久保存与恢复、报告范围筛选、过期/被修改记录包拒绝、草稿与最终文稿区分，以及文稿保存不改变阅读状态。测试在 Windows 本地环境运行；没有进行真实原文伴读的端到端语义评估、断电或网盘并发测试。

## 使用约定

将 `skills/classic-reading-companion/` 作为完整 Skill 目录交给支持该格式的运行环境加载。安装和调用方式取决于实际使用的平台；仅把仓库放在 GitHub 上不会自动启用 Skill。

开始时提供书名、正在读的原文或文件，以及已知版本信息。可以直接说：“这句话什么意思”“这一段读完了”“检查一下我的理解”“今天读到这里”“继续上次的位置”。

个人阅读数据默认保存在阅读工作目录的 `reading-data/<book-id>/`，与 Skill 安装目录分开。首次使用会告知实际绝对路径；跨对话或设备续读时，需要让运行环境能访问同一完整数据目录。不能运行保存工具或不能写文件时，只能提供完整候选记录并说明未完成工具保存。

本仓库只分发规则与空白模板，不自动上传个人阅读数据。`.gitignore` 忽略默认 `reading-data/` 目录；用户自定义路径时也应保持个人数据与分发文件分离。

## 第一版之后

五个开发阶段已完成，V1.1 优先加强“读不懂时怎样继续帮助”。下一步用真实原文的三至五个难点检验解释、换讲法、纠偏及续读；记录每处已解决和仍未解决的具体关系，再根据实际问题迭代。本仓库中的完成状态不表示已经安装到任意运行环境。

第一版不以知识图谱或自动文献搜集为前提。

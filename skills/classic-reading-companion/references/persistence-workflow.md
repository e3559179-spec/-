# 持久保存与续读工具

初始化、保存、续读、导入旧记录或恢复损坏记录时使用。脚本 [reading_store.py](../scripts/reading_store.py) 依赖同目录的 [validate_tracking.py](../scripts/validate_tracking.py)，两者只使用 Python 3 标准库，无网络、定时任务或 GitHub 上传行为。

## 数据位置和当前版本

默认仍是 `<阅读工作目录>/reading-data/<book-id>/`；用户指定路径优先。目录名使用小写字母、数字与连字符，同书不同版本使用不同目录。首次告知实际绝对路径，并将此路径写入会话的续读交付信息。工具拒绝将数据放在 Skill 安装目录内。

目录内容：

```text
<book-id>/
  progress.json                 常用进度文件
  understanding.json            常用理解记录
  .current.json                 当前完整快照的指针
  .snapshots/<save-id>/          历次完整快照及 SHA-256 清单
  .repairs/<unique-id>/          修复前常用文件和指针的原始字节
  .store.lock                   进程协调文件，正常保留
```

**当前指针指向的有效快照是采用工具后的读取依据。** 两份顶层 JSON 是供查看的镜像，分别写入，不能当作一个整体原子事务。快照先写全并校验，随后用同目录文件替换原子更新指针，最后刷新镜像。更改后的 `save_id` 和时间由脚本生成，助手不自行猜测。

工具使用操作系统文件锁排斥同时运行的读写进程，并检查调用者上次读取的保存 ID 和文件状态令牌。进程退出后锁自动释放；不要因为 `.store.lock` 文件还在就删除它。所有写入会话应使用同一工具；手工编辑或不遵守锁的软件不受该锁协调。

本实现针对本地文件系统；本阶段只在 Windows 的测试环境运行。文件会刷新到存储，Windows 标准库没有同等的目录刷新接口，不能把进程中断测试描述为断电、磁盘损坏、网盘冲突或跨设备并发的保证。跨设备续读需要实际取得完整数据目录，不能只复制两个镜像而遗漏快照。

## 初始化与续读

以下示例从仓库根目录执行；安装后可用脚本绝对路径。将示例中的目录、ID、令牌替换为实际值，不把示例当真实阅读记录。

```sh
python skills/classic-reading-companion/scripts/reading_store.py init --book-dir "reading-data/my-book-v1" --title "实际书名"
python skills/classic-reading-companion/scripts/reading_store.py load --book-dir "reading-data/my-book-v1"
```

- `init` 只在空目录初始化，已有记录不会被覆盖。`--title` 可省略；提供时仅记录为用户提供且待核验，不声称已核实版本。其他书目、来源和阅读信息由助手根据实际材料补入候选再保存。
- `load` 返回完整的 `progress`、`understanding`、`state_token`、`storage`、`mirror_state`、路径和结构提醒；不会推进阅读、补造原文或自动更改理解状态。为协调进程可能创建锁文件，但不修改正文记录。
- 续读时先用完整记录确认书籍、版本、用户已读位置、助手已讲位置、检查偏好和待处理问题。简短告诉用户恢复到哪里；未要求继续讲解时不抢先讲下一段。
- 工具不核验原文文件是否仍可用、网页是否变化或当前文件是否换了译本。继续解释前仍需访问实际原文并核对来源与定位片段；记录存在不等于正文可访问。
- 目录缺失或读取失败时如实说明。换工作目录且不知道旧路径时，请用户给出路径，不扫描整个设备寻找记录，也不从聊天记忆生成“上次进度”。

## 形成候选并保存

每轮产生有效记录变更后保存；用户说“今天读到这里”时还要更新简短续读摘要，含本次用户确认范围、实际讲解范围、关键疑问、待处理事项及恢复提示。摘要由实际阅读过程生成，工具不会替用户编写理解。

1. `load` 取得完整两份记录、当前 `save_id` 和 `state_token`。若 `storage` 是 `legacy`，先按下节导入；镜像不一致时先处理修复或冲突。
2. 深复制返回的两个记录对象，依据当前对话修改。保存为该书目录内独立的候选文件，例如 `progress.proposed.json`、`understanding.proposed.json`。不要把整个 load 响应写成一份进度文件，也不要直接编辑正式镜像、快照或指针。
3. 保留已有未知字段及历史。新问题追加；旧解释和理解变化追加；已完成检查不覆写旧回答和评分，纠错按理解追踪规则新增评价及依据。待回答检查可填写实际回答。进度或状态变化依照记录格式留下证据。
4. 运行保存命令，两个候选保持本次读取时的保存元数据，由脚本生成新一批元数据：

```sh
python skills/classic-reading-companion/scripts/reading_store.py save --book-dir "reading-data/my-book-v1" --progress-input "reading-data/my-book-v1/progress.proposed.json" --understanding-input "reading-data/my-book-v1/understanding.proposed.json" --expected-save-id "从load取得的save_id" --expected-token "从load取得的state_token"
```

脚本核对两份文件、版本、书籍、理解记录约束和当前来源/问题引用，阻止旧会话覆盖及常见的历史删除。旧版本的完整数据也保存在快照中。它不验证用户原话真伪、原文解释或历史依据是否充分，这仍由助手审阅。

只有退出码为 0、`ok` 为 true 且 `mirror_state` 为 `consistent` 时，才报告本次保存完整成功。工具返回的内容已经过回读，可简短告知绝对路径，不向用户倾倒保存 ID 和整份 JSON。

## 失败与恢复

所有命令用 JSON 返回结果；成功退出码为 0，业务拒绝或文件/JSON 错误为 1，命令行参数用法错误由 argparse 返回 2。失败不等于从未写入：可能已完成快照及指针提交，只差镜像刷新。保留候选，先 `load` 或 `history` 查明实际状态，不盲目重复保存。

| 状态 | 下一步 |
| --- | --- |
| `busy` | 另一个进程持锁。稍后重新读取，不删除锁文件，不循环刷屏。 |
| 保存 ID / 令牌变化 | 重新读取当前记录，保留本会话候选，合并有依据的新增内容后重新保存；不沿用旧元数据强写。 |
| `mirror_state: interrupted` | 当前完整快照可读，镜像仅缺失或仍是前一版本。可使用当前令牌执行 `repair` 完成镜像刷新，不改变已提交内容。 |
| `mirror_state: conflict` | 至少一个镜像出现无法归为当前/前一快照的内容。先读取并呈现相关差异，保留候选；用户明确要以快照为准时修复，要保留手工修改时先提取其变更。无法判断意图时让用户选择，不自动丢弃修改。 |
| 当前指针缺失/损坏，或当前快照损坏 | 用 `history` 列出可校验的快照；根据明确恢复指示选择 `restore`。没有充分依据时不自动选时间最新的一份。 |

```sh
python skills/classic-reading-companion/scripts/reading_store.py repair --book-dir "reading-data/my-book-v1" --expected-token "从load取得的state_token"
python skills/classic-reading-companion/scripts/reading_store.py history --book-dir "reading-data/my-book-v1"
python skills/classic-reading-companion/scripts/reading_store.py restore --book-dir "reading-data/my-book-v1" --snapshot "选定的快照ID" --expected-token "从history取得的state_token" --reason "有依据的恢复原因"
```

`repair` 先保存当前镜像原始字节，再用当前快照修复镜像；不改变当前保存 ID。`restore` 保留现场，将选定快照复制为一个新的保存版本，并在进度历史记录来源及原因；`previous_save_id` 指向被恢复的快照。这是显式恢复分支，不代表中间的学习从未发生。所有旧快照保留，不自动清理。

`history` 中“valid”只表示快照结构和哈希有效，**不证明它曾经成为当前已提交版本**：指针更新前中断也可能留下完整候选快照。当前指针、前后版本关系、实际内容及用户意图共同决定恢复选择。全部快照不可用时，保留 `.repairs` 原始字节和候选，说明需要手动检查，不能宣布已恢复。

## 旧记录与没有 Python 的环境

只有两份有效 JSON、没有快照目录和指针的版本 1 数据可直接 `load`，返回 `storage: legacy`。取得状态令牌后执行：

```sh
python skills/classic-reading-companion/scripts/reading_store.py import-legacy --book-dir "reading-data/my-book-v1" --expected-token "从load取得的state_token"
```

导入会归档原始字节，保留 JSON 字段值及保存 ID，建立快照与指针，不补造新学习事实。若导入曾中断而已有快照目录，则先检查 `history`；不要伪装成从未导入再覆盖。旧 `save_id` 需为字母或数字开头、后接字母/数字/下划线/连字符、总长不超过 128 的标识；不符合时保留原件，明确提出兼容迁移方案，不悄悄改 ID。

没有 Python 或缺少文件写入能力时，交付两份完整候选及路径、依据版本和续读摘要，说明尚未由工具持久保存。不得手工绕过已有快照目录的版本控制，也不能称聊天记忆为保存。仅阅读已有记录时可用可用文件工具检查指针与快照；无法核验时说明限制，不假装恢复成功。

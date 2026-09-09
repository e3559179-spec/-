# 记录格式、保存和续读

## 数据目录与模板

默认使用 `<阅读工作目录>/reading-data/<book-id>/`，用户指定可用路径时遵循该设置。首次初始化告知实际绝对路径。数据目录必须在 Skill 安装目录之外；若当前目录就是安装目录且没有可确定的阅读工作目录，询问数据保存位置。没有读写工具时按失败流程交付记录，不承诺自动保存。

`book_id` 是第一次初始化时分配的稳定目录标识，可用简短书名拼音加唯一后缀；只用字母、数字和连字符，不含路径分隔符。每本书的每个版本独立记录，同名目录不能直接覆盖。实际书目信息保存在 `book`，不要把 ID 当作版本证据。

从两个 assets 模板初始化 `progress.json` 和 `understanding.json`。模板只表达空状态，`records: []` 表示没有问题，不能创建虚构示例充数。不要把实际阅读文件写回分发仓库；仓库忽略默认 `reading-data/`，自定义目录也不自动提交。

## 通用约定

- 使用 UTF-8 JSON。未知值为 `null`，无条目为 `[]`；不使用“已理解”等词代替缺失证据。时间使用带时区的 ISO 8601，实际获取时间，不虚构时间戳。
- `schema_version` 当前为整数 `1`。遇到不支持的版本时保留原文件，说明需要兼容处理，不直接覆盖。
- 两份文件的 `book_id`、`schema_version`、`save_id`、`previous_save_id` 必须一致。每次保存使用新的唯一 `save_id`，并将旧 ID 写入 `previous_save_id`。它们用于识别跨文件未完成的保存，不是理解证据。
- 既有记录 ID 稳定；同一知识点的追问追加到该记录，独立知识点另建条目。不因位置相近就合并不同问题，不覆盖用户原话和旧解释。
- 引用用户表达时尽量保留原句；摘要与原话分字段。对话没有稳定链接时使用本地事件 ID，不编造消息 URL。

### 位置对象

以下为空结构说明，实例中不必保存完全空的位置对象，位置未知用 `null`：

```json
{
  "source_id": null,
  "chapter": null,
  "section": null,
  "printed_page": null,
  "pdf_page_index": null,
  "paragraph_id": null,
  "anchor_text": null
}
```

`pdf_page_index` 为正整数，其余非空字段为字符串。范围对象为 `{"start_location": null, "end_location": null}`，填入位置对象；单段可只填起点。工作段落编号及页码语义见 [原文规则](source-rules.md)。

## progress.json

| 字段 | 含义与更新依据 |
| --- | --- |
| `book` | 书名、作者、译者、版本、出版信息；`metadata_evidence` 的每项含 `field`、`value`、`basis`、`verification_status`，用于区别用户提供和已核验信息；`unverified_fields` 列尚未确认的字段名。 |
| `sources` | 每项含稳定 `id`、`kind`（`file` / `url` / `user_text`）、`locator`、`verification_status`、`verified_scope`、`verified_at`、`limitations`。`locator` 是真实路径、URL 或可确认的会话来源说明，范围以文字或范围对象记录。 |
| `reading_goal` | 默认主要目标为理解原著，可选专题来自用户表达。 |
| `current_source_id` | 当前使用的来源 ID，非空时必须能在 `sources` 中找到。 |
| `current_requested_range` | 当前用户要求答疑或讲解的范围，不代表已读或已讲完。 |
| `user_confirmed_read_position` | 用户明确表示读到的位置；提问和助手讲解不自动推进该字段。 |
| `last_explained_position` | 最近实际讲解完成的位置，与已读位置分开。 |
| `next_position` | 根据原文实际结构确认的下一位置；未知则为空，不猜页码。 |
| `coverage` | 逐次覆盖项：`range`、`user_declared_read`、`assistant_explained`、`understanding_record_ids`、`basis`、`updated_at`。两项布尔值只表示有无对应证据，不是掌握评价。保留跳读或缺失范围，不从最远位置反推中间全部读过。 |
| `recent_session_summary` | 简短续读摘要：本次用户确认范围、讲解范围、重点记录 ID、未解决 ID、恢复提示。只记录实际发生的事。 |
| `pending_actions` | 每项含 `id`、`record_id`（可空）、`action`、`status`（`待处理` / `已完成` / `已取消`）、`basis`。 |
| `progress_history` | 每项含 `at`、`field`、`before`、`after`、`basis`；保留进度更正和回退的依据。 |
| `updated_at` | 最近成功写入批次使用的实际时间。 |

用户说“整本读完了”可以形成相应声明覆盖记录，但不能为没有伴读的章节填上讲解或理解检查结果。

## understanding.json

每条 `records` 记录使用下面的字段。空结构仅用于说明，只有真实问题出现时才创建条目：

```json
{
  "id": null,
  "location": null,
  "question_verbatim": null,
  "question_types": [],
  "classification_basis": null,
  "understanding_at_time": null,
  "explanations": [],
  "understanding_changes": [],
  "checks": [],
  "current_status": "待解决",
  "check_applicability": "待判断",
  "response_status": "待回应",
  "follow_up_actions": [],
  "history": [],
  "created_at": null,
  "updated_at": null
}
```

- `question_verbatim` 保留首次问题原话。无显式问句但用户要求记录某点时，保留其原话。
- `question_types` 可多选：`概念不清`、`论证断点`、`背景不足`、`理解偏差`、`延伸探究`、`解释争议`。证据不足留空。分类依据放在 `classification_basis`；判为理解偏差须有用户实际表达及原文依据。
- `understanding_at_time` 是用户实际说过的当时理解，未表达留空。
- `explanations` 每项含 `id`、`at`、`text`、`evidence`、`uncertainties`。`evidence` 每项含 `location`、`quote`（无直接引文时为空）、`paraphrase`、`source_locator`、`verification_status`。外部背景需有自己的真实来源，不能借用原文位置作证。
- `understanding_changes` 每项含 `at`、`user_verbatim`、`assistant_assessment`、`evidence`。用户的变化与助手的评价分开；不要将助手讲解抄作用户的理解。
- `checks` 每项含 `id`、`asked_at`、`question`、`user_answer`、`answered_at`、`feedback`、`evidence`、`result`。`result` 可为 `待回答`、`通过`、`需修正`、`已跳过`、`无法判定`。没有实际回答时，`user_answer` 为 `null`，不能判通过。
- `follow_up_actions` 使用进度中的行动结构，可指向重读、补背景或文本比较；不自动执行用户未要求的延伸研究。
- `history` 追加事件：`id`、`at`、`kind`、`user_verbatim`、`before`、`after`、`basis`。追问、分类更正、状态变化和重新打开问题均保留，不只留最终结论。

### 状态与回应分开

`current_status` 可为 `待解决`、`已解释待检验`、`已通过理解检查`、`仍有争议`；当理解检查不适用时允许为 `null`，用回应状态表达进展。

`check_applicability` 可为 `适用`、`不适用`、`待判断`。`response_status` 可为 `待回应`、`已回应`、`需继续讨论`。回应完成与理解通过是两回事。

1. 新出现的未解知识点：待解决。给出相关解释后最多进入已解释待检验；若用户明确仍不懂，维持或恢复待解决。
2. 已通过理解检查：必须有同一知识点的实际回答、通过反馈和原文依据。一次正确回答只支持该检查覆盖范围，不保证长期掌握。
3. 用户仅说“好的”、未再追问、跳过或停止检查：不进入已通过理解检查；跳过不记录为理解失败。
4. 延伸探究、价值质疑或无需测验的讨论：可设检查不适用、理解状态为空，另用回应状态表示进展。有文本解释争议时可保留仍有争议，不暗示用户能力不足。
5. 新表达暴露遗漏，或旧解释被纠正：重新评估相关知识点、更新状态并保留历史；没有新证据时不任意撤销旧检查结果。

## 保存流程

产生问题、解释、理解反馈或进度变化后，在本轮结束前及时保存；会话结束时额外更新续读摘要，不依赖结束口令才首次保存。

1. 读取现有两份文件，核对版本、书籍 ID、保存批次及实际存储路径；文件损坏或批次不一致时先进入恢复流程。保留无法识别的既有字段，不做无依据迁移。
2. 在内存中形成更新，保留历史。生成同一新 `save_id`、相同 `previous_save_id` 和时间戳。
3. 将两份候选 JSON 写到同一数据目录下的临时文件，解析并验证字段及跨文件引用；已有一致文件先备份为一对，备份名包含旧保存 ID。首次初始化没有备份。
4. 替换前重读正式文件，确认保存 ID 仍等于本次读取值；若发生变化，重新读取并重新计算，不能覆盖另一个会话刚写入的记录。本阶段不支持多会话同时写同一本书，发现并发变化时停下当前写入并说明。
5. 使用可用的文件工具逐个替换正式文件；支持单文件原子替换时优先使用。两文件替换并非整体原子操作，不能声称完全事务化。
6. 重读两份正式文件，确认 JSON 可解析、保存 ID 一致、关键变更及历史均已保留，检查 ID 引用可解析。全部通过后才报告已保存和实际路径。

读写能力不可用、任一步失败或进程中断时，不报告成功。保留临时候选和备份，不盲目重试覆盖；说明失败位置，并提供已形成的两份完整更新 JSON，供用户手动保存。文件过长时可交付实际生成的完整文件，不能声称省略内容也可恢复。

## 恢复与续读

先使用当前明确的数据目录；换工作目录且不知道路径时，请用户提供旧路径或记录，不从聊天记忆猜测，也不扫描整个设备。

- 两份文件保存 ID 一致且有效：核对书籍与版本，从续读摘要恢复。原文不可访问时说明需要原文，记录本身不证明正文仍可读。
- ID 不一致、只剩一份或 JSON 损坏：报告保存不完整，检查同目录内的候选和成对备份。能找到有效完整配对时展示可恢复的时间和差异；有多个候选且无法判断哪个包含用户最新变化时询问选择，不擅自用旧数据覆盖新数据。
- 完全没有记录：说明未找到；根据用户提供的当前位置重新建立，不能写成已恢复历史。
- 续读摘要不能替代完整记录。总结前读取问题、解释依据、变化历史和覆盖范围；没有检查记录的章节必须明确注明。

目前流程依赖运行助手的文件工具执行。模板与规则不等于自动运行的保存程序；后续保存辅助工具需要另行实现和验证。

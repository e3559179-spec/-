"""Read-only structural checks for understanding.json; no semantic grading.

Uses only the Python standard library. It never changes reading records.
"""

import argparse
import json
from pathlib import Path


STATUSES = {"待解决", "已解释待检验", "已通过理解检查", "仍有争议", None}
RESULTS = {"待回答", "通过", "需修正", "已跳过", "无法判定"}
VALIDITIES = {"有效", "待复核", "已撤回"}
SUPPORTS = {"无本轮定向提示", "定向提示后", "示范答案后", "不明"}


def has_text(value):
    return isinstance(value, str) and bool(value.strip())


def has_location(value):
    if not isinstance(value, dict):
        return False
    # A source ID alone identifies a source, not the passage within it.
    if any(has_text(value.get(k)) for k in (
        "chapter", "section", "printed_page", "paragraph_id", "anchor_text"
    )):
        return True
    page = value.get("pdf_page_index")
    return type(page) is int and page > 0


def has_evidence(value):
    if not isinstance(value, list):
        return False
    return any(
        isinstance(item, dict)
        and (has_location(item.get("location"))
             or has_text(item.get("source_locator")))
        and (has_text(item.get("quote")) or has_text(item.get("paraphrase")))
        for item in value
    )


def validate(data):
    """Return errors and compatibility warnings, without mutating data."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return {"errors": ["root: 必须是 JSON 对象"], "warnings": []}
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        errors.append("schema_version: 仅支持整数 1")
    records = data.get("records")
    if not isinstance(records, list):
        errors.append("records: 必须是数组")
        return {"errors": errors, "warnings": warnings}
    if records and not has_text(data.get("book_id")):
        errors.append("book_id: 有实际记录时必须标识书籍")

    record_ids, global_check_ids = set(), set()
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix}: 必须是对象")
            continue
        record_id = record.get("id")
        if not has_text(record_id) or record_id in record_ids:
            errors.append(f"{prefix}.id: 必须是非空且唯一的字符串")
        else:
            record_ids.add(record_id)
        status = record.get("current_status")
        if not (status is None or isinstance(status, str)) or status not in STATUSES:
            errors.append(f"{prefix}.current_status: 不支持的状态")
        applicability = record.get("check_applicability", "待判断")
        if applicability not in ("适用", "不适用", "待判断"):
            errors.append(f"{prefix}.check_applicability: 不支持的值")
        if status == "已通过理解检查" and applicability == "不适用":
            errors.append(f"{prefix}: 不适用检查与已通过状态矛盾")
        if status is None and applicability != "不适用":
            errors.append(f"{prefix}: 空理解状态仅用于不适用检查")
        if not has_text(record.get("knowledge_point")):
            warnings.append(f"{prefix}: 未明确 knowledge_point，请按实际材料补充范围")

        checks = record.get("checks")
        if not isinstance(checks, list):
            errors.append(f"{prefix}.checks: 必须是数组")
            continue
        check_ids, eligible = set(), set()
        for check_index, check in enumerate(checks):
            cp = f"{prefix}.checks[{check_index}]"
            if not isinstance(check, dict):
                errors.append(f"{cp}: 必须是对象")
                continue
            check_id = check.get("id")
            id_valid = has_text(check_id) and check_id not in global_check_ids
            if not id_valid:
                errors.append(f"{cp}.id: 必须是非空且全文件唯一的字符串")
            validity = check.get("validity", "有效")
            if not isinstance(validity, str) or validity not in VALIDITIES:
                errors.append(f"{cp}.validity: 不支持的值")
            result = check.get("result")
            if not isinstance(result, str) or result not in RESULTS:
                errors.append(f"{cp}.result: 不支持的结果")
            kind = check.get("kind")
            if kind is not None and kind not in ("提问检查", "表达评估"):
                errors.append(f"{cp}.kind: 不支持的类型")
            support = check.get("support", "不明")
            if not isinstance(support, str) or support not in SUPPORTS:
                errors.append(f"{cp}.support: 不支持的支持条件")
            if kind is None or not has_text(check.get("target")) or "support" not in check:
                warnings.append(f"{cp}: 旧格式缺少类型、目标或支持条件；不得补造")

            # Keep withdrawn/under-review historical mistakes; do not require
            # deleting them to make the current file structurally usable.
            issues = errors if validity == "有效" else warnings
            if kind == "提问检查" and not has_text(check.get("question")):
                issues.append(f"{cp}: 提问检查缺少实际题目")
            if kind == "表达评估" and not has_text(check.get("user_answer")):
                issues.append(f"{cp}: 表达评估缺少用户实际表达")
            if result == "待回答" and has_text(check.get("user_answer")):
                issues.append(f"{cp}: 待回答检查却已有回答，需核对结果")
            proof = (has_text(check.get("user_answer"))
                     and has_text(check.get("feedback"))
                     and has_evidence(check.get("evidence")))
            if result in ("通过", "需修正") and not proof:
                issues.append(f"{cp}: 通过或需修正须有实际表达、反馈和可定位的文本依据")
            if result == "通过" and support == "示范答案后":
                warnings.append(f"{cp}: 示范答案后的通过须人工确认不是仅复述答案")
            if (id_valid and result == "通过" and validity == "有效" and proof):
                eligible.add(check_id)

            previous_id = check.get("supersedes_check_id")
            if previous_id is not None:
                if not has_text(previous_id) or previous_id not in check_ids:
                    errors.append(f"{cp}.supersedes_check_id: 必须指向本条记录更早的检查")
            if has_text(check_id):
                global_check_ids.add(check_id)
                check_ids.add(check_id)

        refs = record.get("status_check_ids")
        if "status_check_ids" in record:
            if not isinstance(refs, list) or not all(has_text(ref) for ref in refs):
                errors.append(f"{prefix}.status_check_ids: 必须是检查 ID 数组")
            elif len(set(refs)) != len(refs):
                errors.append(f"{prefix}.status_check_ids: 不能有重复 ID")
            elif status == "已通过理解检查":
                if not refs or any(ref not in eligible for ref in refs):
                    errors.append(f"{prefix}: 当前通过必须关联本知识点的有效通过证据")
            elif refs:
                errors.append(f"{prefix}: 非通过状态不保留当前通过关联，旧关联应保存在历史")
        elif status == "已通过理解检查":
            if eligible:
                warnings.append(f"{prefix}: 旧格式没有 status_check_ids，须人工核对当前通过依据")
            else:
                errors.append(f"{prefix}: 当前通过没有可用的有效通过证据")
    return {"errors": errors, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()
    try:
        data = json.loads(args.path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        report = {"errors": [f"无法读取有效 JSON: {exc}"], "warnings": []}
        code = 2
    else:
        report = validate(data)
        code = 1 if report["errors"] else 0
    if args.json_output:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print("结构检查失败" if code else "所检查的结构约束满足；不代表语义判断正确")
        for level in ("errors", "warnings"):
            for message in report[level]:
                print(f"{level}: {message}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

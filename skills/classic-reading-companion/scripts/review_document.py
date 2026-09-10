"""Prepare evidence and seal authored Markdown reviews; never infer book meaning.

The assistant writes and reviews the prose. This tool freezes its record basis,
checks staleness, and saves versioned artifacts without updating reading state.
"""

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import uuid

import reading_store as store


MARKER = "<!-- DRAFT:REVIEW -->"


def chapter_of(location):
    return location.get("chapter") if isinstance(location, dict) else None


def selection(progress, understanding, kind, chapter):
    store.require(kind in ("book", "chapter"), "kind 必须为 book 或 chapter")
    store.require(kind != "chapter" or isinstance(chapter, str) and chapter.strip(), "章节复盘需要明确章节名称")
    store.require(kind != "book" or chapter is None, "全书总结不接受章节过滤")
    included, ambiguous, excluded = [], [], []
    for record in understanding["records"]:
        label = chapter_of(record.get("location"))
        if kind == "book" or label == chapter:
            included.append(record["id"])
        elif not label:
            ambiguous.append(record["id"])
        else:
            excluded.append(record["id"])
    included_coverage, ambiguous_coverage = [], []
    for index, item in enumerate(progress["coverage"]):
        if kind == "book":
            included_coverage.append(index)
            continue
        value = item.get("range") if isinstance(item, dict) else None
        if not isinstance(value, dict):
            ambiguous_coverage.append(index)
            continue
        start = chapter_of(value.get("start_location"))
        end_location = value.get("end_location")
        end = chapter_of(end_location)
        if start == chapter and (end_location is None or end == chapter):
            included_coverage.append(index)
        elif not start or (end_location is not None and not end) or start != (end or start):
            # No table of contents: cannot determine whether an interval includes
            # the requested chapter. Preserve it for manual scope review.
            ambiguous_coverage.append(index)
    return {"record_ids": included, "ambiguous_record_ids": ambiguous,
            "excluded_record_ids": excluded, "coverage_indices": included_coverage,
            "ambiguous_coverage_indices": ambiguous_coverage,
            "note": "仅按已有章节标记选取，不推断整章已读、已讲或掌握；未定位材料需人工核对"}


def make_packet(state, kind, chapter):
    p, u = state["pair"]
    return {"packet_version": 1, "kind": kind, "chapter": chapter,
            "book_id": p["book_id"], "basis_save_id": p["save_id"],
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "basis_hashes": {name: store.digest(store.encode(value)) for name, value in zip(store.NAMES, (p, u))},
            "selection": selection(p, u, kind, chapter),
            "warnings": state["warnings"], "progress": p, "understanding": u}


def reports_path(root):
    return store.plain(root / "reports")


def prepare(directory, kind, chapter=None):
    root = store.book_path(directory)
    with store.locked(root):
        state = store.inspect_locked(root)
        store.require(state["storage"] == "snapshots" and state["mirror_state"] == "consistent",
                      "先完成旧记录导入或镜像修复，再准备报告", "conflict")
        packet = make_packet(state, kind, chapter)
        folder = reports_path(root) / ("draft-" + uuid.uuid4().hex)
        folder.mkdir(parents=True)
        template = store.SKILL / "assets" / ("book-review.template.md" if kind == "book" else "chapter-review.template.md")
        title = state["pair"][0]["book"].get("title") or "书名待核实"
        title = str(title).replace("\r", " ").replace("\n", " ")
        if chapter:
            title += "｜" + chapter.replace("\r", " ").replace("\n", " ")
        draft = template.read_text(encoding="utf-8").replace("{{title}}", title)
        store.write_sync(folder / "evidence.json", store.encode(packet))
        store.write_sync(folder / "draft.md", draft.encode("utf-8"))
        store.require(store.parse((folder / "evidence.json").read_bytes()) == packet, "记录包回读失败")
        return {"status": "draft", "basis_save_id": packet["basis_save_id"],
                "packet_path": str(folder / "evidence.json"), "draft_path": str(folder / "draft.md"),
                "selection": packet["selection"],
                "next_step": "核对原文与记录，实际撰写并审阅 Markdown；此草稿不能当作最终总结"}


def finalize(directory, packet_path, content_path):
    root = store.book_path(directory)
    # Both inputs must be different from the output. Final folders use fresh IDs.
    packet = store.parse(Path(packet_path).read_bytes())
    body = Path(content_path).read_text(encoding="utf-8-sig")
    store.require(body.strip() and MARKER not in body, "报告为空或仍带草稿标记；先实际撰写并审阅")
    store.require(isinstance(packet, dict) and type(packet.get("packet_version")) is int
                  and packet["packet_version"] == 1, "不支持的记录包格式")
    with store.locked(root):
        state = store.inspect_locked(root)
        store.require(state["storage"] == "snapshots" and state["mirror_state"] == "consistent",
                      "当前记录有未处理的存储状态", "conflict")
        expected = make_packet(state, packet.get("kind"), packet.get("chapter"))
        store.require(packet.get("book_id") == root.name and packet.get("basis_save_id") == expected["basis_save_id"],
                      "记录包不属于当前书籍或记录已更新；请重新准备并核对文稿", "conflict")
        for key in ("progress", "understanding", "basis_hashes", "selection"):
            store.require(packet.get(key) == expected[key], f"记录包的 {key} 被修改或不一致")
        report_id = uuid.uuid4().hex
        folder = reports_path(root) / report_id
        folder.mkdir(parents=True)
        raw = body.encode("utf-8")
        store.write_sync(folder / "review.md", raw)
        store.write_sync(folder / "evidence.json", store.encode(packet))
        manifest = {"report_id": report_id, "kind": packet["kind"], "chapter": packet["chapter"],
                    "book_id": root.name, "basis_save_id": packet["basis_save_id"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "hashes": {"review.md": store.digest(raw), "evidence.json": store.digest(store.encode(packet))},
                    "content_review": "由撰写助手核对；工具不验证原文解释或文稿语义"}
        for name, expected_hash in manifest["hashes"].items():
            store.require(store.digest((folder / name).read_bytes()) == expected_hash, f"报告回读失败: {name}")
        # Completion marker is written last. A partial folder is not a final report.
        store.write_sync(folder / "manifest.json", store.encode(manifest))
        store.require(store.parse((folder / "manifest.json").read_bytes()) == manifest, "报告清单回读失败")
        return {"status": "written", "report_id": report_id, "basis_save_id": packet["basis_save_id"],
                "report_path": str(folder / "review.md"), "manifest_path": str(folder / "manifest.json"),
                "note": "已保存文稿与依据；未改变阅读进度或理解状态，工具未进行语义验证"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "finalize"))
    parser.add_argument("--book-dir", required=True)
    parser.add_argument("--kind", choices=("book", "chapter"))
    parser.add_argument("--chapter")
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--content", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            store.require(args.kind is not None, "prepare 需要 kind")
            result = prepare(args.book_dir, args.kind, args.chapter)
        else:
            store.require(args.packet and args.content, "finalize 需要 packet 和 content")
            result = finalize(args.book_dir, args.packet, args.content)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except (store.StoreError, OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc),
                          "next_step": "保留文稿；核对记录或输出目录，不宣称文档已完成保存"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Local versioned reading records. Python standard library; no network access.

The atomic HEAD pointer commits an immutable snapshot. The two top-level JSON
files are compatibility mirrors, not a two-file atomic transaction.
"""

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from validate_tracking import validate as validate_tracking


NAMES = ("progress.json", "understanding.json")
SKILL = Path(__file__).resolve().parents[1]
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class StoreError(Exception):
    def __init__(self, message, code="invalid"):
        super().__init__(message)
        self.code = code


def require(condition, message, code="invalid"):
    if not condition:
        raise StoreError(message, code)


def identifier(value):
    return isinstance(value, str) and SAFE_ID.fullmatch(value) is not None


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"JSON 含重复键: {key}")
            result[key] = value
        return result

    def bad_constant(value):
        raise StoreError(f"JSON 不允许 {value}")

    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                      parse_constant=bad_constant)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(path):
    require(not path.is_symlink() and not (hasattr(path, "is_junction") and path.is_junction()),
            f"管理路径不能是链接或目录联接: {path}")
    return path


def book_path(value, create=False):
    path = Path(value).expanduser().resolve()
    require(path != SKILL and SKILL not in path.parents, "阅读数据必须在 Skill 安装目录之外")
    require(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", path.name) is not None,
            "book-id 目录名须为小写字母、数字及连字符")
    require(path.name.upper() not in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)],
                                      *[f"LPT{i}" for i in range(1, 10)]}, "保留的系统目录名")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    require(path.is_dir(), f"未找到阅读目录: {path}", "not_found")
    return path


@contextmanager
def locked(root):
    # OS locks are released if the process dies; the lock file remains in place.
    path = plain(root / ".store.lock")
    handle = open(path, "a+b")
    acquired = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise StoreError("另一个进程正在操作本书，请稍后重新读取", "busy") from exc
        acquired = True
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def read_optional(path):
    plain(path)
    return path.read_bytes() if path.exists() else None


def state_token(root):
    values = {name: (digest(raw) if raw is not None else None)
              for name in (*NAMES, ".current.json")
              for raw in [read_optional(root / name)]}
    return digest(encode(values))


def validate_pair(root, progress, understanding):
    require(isinstance(progress, dict) and isinstance(understanding, dict), "两份记录须为对象")
    for key in ("schema_version", "book_id", "save_id", "previous_save_id"):
        require(key in progress and key in understanding and progress[key] == understanding[key],
                f"两份记录的 {key} 不一致或缺失")
    require(type(progress["schema_version"]) is int and progress["schema_version"] == 1,
            "不支持的 schema_version")
    require(progress["book_id"] == root.name, "book_id 与目录不一致")
    require(identifier(progress["save_id"]), "缺少有效 save_id")
    require(progress["previous_save_id"] is None or identifier(progress["previous_save_id"]),
            "无效 previous_save_id")
    report = validate_tracking(understanding)
    require(not report["errors"], "理解记录约束失败: " + "; ".join(report["errors"]))
    for record in understanding["records"]:
        for key in ("explanations", "understanding_changes", "checks", "history", "follow_up_actions"):
            if key in record:
                require(isinstance(record[key], list) and all(isinstance(item, dict) for item in record[key]),
                        f"{record['id']}.{key} 必须是对象数组")
    for key in ("book", "reading_goal", "recent_session_summary"):
        require(isinstance(progress.get(key), dict), f"progress.{key} 必须是对象")
    for key in ("sources", "coverage", "pending_actions", "progress_history"):
        require(isinstance(progress.get(key), list), f"progress.{key} 必须是数组")
    sources = progress["sources"]
    require(all(isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"] for s in sources),
            "来源必须有非空字符串 ID")
    source_ids = [s["id"] for s in sources]
    require(len(source_ids) == len(set(source_ids)), "来源 ID 重复")
    record_ids = {r["id"] for r in understanding["records"]}

    def refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("source_id", "current_source_id") and item is not None:
                    require(isinstance(item, str) and item in source_ids, f"未知来源 ID: {item}")
                if key == "record_id" and item is not None:
                    require(isinstance(item, str) and item in record_ids, f"未知问题 ID: {item}")
                if key in ("understanding_record_ids", "key_record_ids", "unresolved_record_ids"):
                    require(isinstance(item, list) and all(isinstance(i, str) and i in record_ids for i in item),
                            f"{key} 含未知问题引用")
                # History is evidence of earlier states, not current foreign keys.
                if key not in ("history", "progress_history"):
                    refs(item)
        elif isinstance(value, list):
            for item in value:
                refs(item)
    refs(progress)
    refs(understanding)
    return report["warnings"]


def snapshot_dir(root, save_id):
    require(identifier(save_id), "无效快照 ID")
    return plain(plain(root / ".snapshots") / save_id)


def read_snapshot(root, save_id):
    directory = snapshot_dir(root, save_id)
    manifest = parse(plain(directory / "manifest.json").read_bytes())
    require(isinstance(manifest, dict) and manifest.get("save_id") == save_id, "快照清单 ID 不符")
    require(isinstance(manifest.get("hashes"), dict), "快照清单缺少哈希")
    raws = [plain(directory / name).read_bytes() for name in NAMES]
    for name, raw in zip(NAMES, raws):
        require(manifest["hashes"].get(name) == digest(raw), f"快照内容校验失败: {save_id}/{name}")
    pair = [parse(raw) for raw in raws]
    warnings = validate_pair(root, *pair)
    require(pair[0]["save_id"] == save_id, "快照正文 ID 不符")
    return pair, raws, warnings


def write_sync(path, raw):
    plain(path)
    with open(path, "xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def sync_directory(path):
    # Windows has no portable directory fsync in Python's standard library.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write(path, raw):
    plain(path)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    write_sync(temp, raw)
    os.replace(temp, path)
    sync_directory(path.parent)


def make_snapshot(root, pair):
    save_id = pair[0]["save_id"]
    directory = snapshot_dir(root, save_id)
    if directory.exists():
        existing, _, _ = read_snapshot(root, save_id)
        require(existing == list(pair), "已有快照内容不同，拒绝覆盖")
        return
    directory.mkdir(parents=True)
    raws = [encode(value) for value in pair]
    for name, raw in zip(NAMES, raws):
        write_sync(directory / name, raw)
    write_sync(directory / "manifest.json", encode({
        "save_id": save_id, "hashes": {name: digest(raw) for name, raw in zip(NAMES, raws)}
    }))
    sync_directory(directory)
    sync_directory(directory.parent)
    read_snapshot(root, save_id)


def head_id(root):
    raw = read_optional(root / ".current.json")
    if raw is None:
        return None
    value = parse(raw)
    require(isinstance(value, dict) and identifier(value.get("save_id")), "当前版本指针损坏", "recovery_required")
    return value["save_id"]


def inspect_locked(root):
    save_id = head_id(root)
    if save_id is None:
        require(not (root / ".snapshots").exists(), "缺少当前指针；请列出快照后恢复", "recovery_required")
        raws = [plain(root / name).read_bytes() for name in NAMES]
        pair = [parse(raw) for raw in raws]
        warnings = validate_pair(root, *pair)
        return {"storage": "legacy", "mirror_state": "consistent", "pair": pair,
                "warnings": warnings, "state_token": state_token(root)}
    pair, raws, warnings = read_snapshot(root, save_id)
    actual = [read_optional(root / name) for name in NAMES]
    mirror = "consistent" if actual == raws else "conflict"
    if mirror != "consistent":
        previous = pair[0]["previous_save_id"]
        old_raws = [None, None]
        if previous:
            try:
                _, old_raws, _ = read_snapshot(root, previous)
            except (StoreError, OSError, ValueError, UnicodeError):
                pass
        if all(raw is None or raw in (raws[i], old_raws[i]) for i, raw in enumerate(actual)):
            mirror = "interrupted"
        warnings = [*warnings, "常用 JSON 与当前快照不一致；先修复或核对手工修改，不能直接保存"]
    return {"storage": "snapshots", "mirror_state": mirror, "pair": pair,
            "warnings": warnings, "state_token": state_token(root)}


def describe(root, state):
    return {"data_dir": str(root), "storage": state["storage"],
            "mirror_state": state["mirror_state"], "state_token": state["state_token"],
            "warnings": state["warnings"], "progress": state["pair"][0],
            "understanding": state["pair"][1]}


def load(directory):
    root = book_path(directory)
    with locked(root):
        return describe(root, inspect_locked(root))


def publish(root, pair):
    validate_pair(root, *pair)
    make_snapshot(root, pair)
    # Commit point. Any later failure is recoverable from this complete snapshot.
    atomic_write(root / ".current.json", encode({"save_id": pair[0]["save_id"]}))
    for name, value in zip(NAMES, pair):
        atomic_write(root / name, encode(value))
    state = inspect_locked(root)
    require(state["mirror_state"] == "consistent", "镜像写入后核验失败", "recovery_required")
    return describe(root, state)


def stamp(pair, previous):
    pair = deepcopy(pair)
    save_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    for value in pair:
        value.update(save_id=save_id, previous_save_id=previous, updated_at=now)
    return pair


def initialize(directory, title=None):
    root = book_path(directory, create=True)
    with locked(root):
        require(not any(p.name != ".store.lock" for p in root.iterdir()), "目录不为空，拒绝重新初始化", "conflict")
        pair = [parse((SKILL / "assets" / name.replace(".json", ".template.json")).read_bytes()) for name in NAMES]
        for value in pair:
            value["book_id"] = root.name
        if title is not None:
            pair[0]["book"]["title"] = title
            pair[0]["book"]["metadata_evidence"].append({"field": "title", "value": title,
                "basis": "初始化时用户提供", "verification_status": "待核实"})
        return publish(root, stamp(pair, None))


def preserve_history(old, new):
    # Snapshots retain the full previous data, including unknown extension fields.
    # Also prevent accidental deletion from current records; correction is explicit.
    for before, after in zip(old, new):
        require(set(before).issubset(after), "候选遗漏已有顶层字段；请从完整 load 结果修改")
    old_records = {r["id"]: r for r in old[1]["records"]}
    new_records = {r["id"]: r for r in new[1]["records"]}
    require(old_records.keys() <= new_records.keys(), "候选删除了既有问题；请保留历史")
    for record_id, before in old_records.items():
        after = new_records[record_id]
        for field in ("explanations", "understanding_changes", "checks", "history"):
            previous = before.get(field, [])
            current = after.get(field, [])
            require(isinstance(current, list) and len(current) >= len(previous), f"{record_id}.{field} 历史被缩短")
            if field in ("history", "understanding_changes", "explanations"):
                require(current[:len(previous)] == previous, f"{record_id}.{field} 须追加，不能覆写历史")
            else:
                for prior, now in zip(previous, current):
                    require(isinstance(now, dict) and now.get("id") == prior.get("id"), "旧检查被删除或换序")
                    for key in ("question", "asked_at", "kind", "target"):
                        if prior.get(key) is not None:
                            require(now.get(key) == prior[key], "旧检查的题目或目标不可覆写")
                    # A pending answer may be completed. Once evaluated, its
                    # original answer/grade stays; only validity can be revised.
                    if prior.get("result") != "待回答":
                        require({k: v for k, v in prior.items() if k != "validity"} ==
                                {k: now.get(k) for k in prior if k != "validity"},
                                "既有检查内容被覆写；请新增评价并关联旧检查")
                    if prior.get("validity", "有效") != now.get("validity", "有效"):
                        require(len(after.get("history", [])) > len(before.get("history", [])),
                                "检查有效性变化须追加说明历史")
        if before.get("question_verbatim") is not None:
            require(after.get("question_verbatim") == before["question_verbatim"], "首次用户问题不可覆写")
        if before.get("understanding_at_time") is not None:
            require(after.get("understanding_at_time") == before["understanding_at_time"], "首次理解不可覆写")
        if after.get("current_status") != before.get("current_status"):
            require(len(after.get("history", [])) > len(before.get("history", [])), "状态变更须追加依据历史")
    history = old[0].get("progress_history", [])
    require(new[0]["progress_history"][:len(history)] == history, "进度历史须追加保留")


def save(directory, progress, understanding, expected_save_id, expected_token):
    root = book_path(directory)
    with locked(root):
        state = inspect_locked(root)
        require(state["storage"] == "snapshots", "旧记录先执行 import-legacy", "legacy")
        require(state["mirror_state"] == "consistent", "镜像不一致，先核对并修复", "conflict")
        require(state["state_token"] == expected_token and state["pair"][0]["save_id"] == expected_save_id,
                "读取后记录已变化，请重新 load 后合并本次更新", "conflict")
        pair = [deepcopy(progress), deepcopy(understanding)]
        validate_pair(root, *pair)
        require(all(p["save_id"] == expected_save_id for p in pair), "候选不是从当前保存版本生成", "conflict")
        preserve_history(state["pair"], pair)
        return publish(root, stamp(pair, expected_save_id))


def history(directory):
    root = book_path(directory)
    with locked(root):
        items = []
        snapshots = plain(root / ".snapshots")
        if snapshots.exists():
            for folder in sorted(snapshots.iterdir()):
                try:
                    pair, _, warnings = read_snapshot(root, folder.name)
                    items.append({"save_id": folder.name, "valid": True,
                                  "previous_save_id": pair[0]["previous_save_id"],
                                  "updated_at": pair[0].get("updated_at"), "warnings": warnings})
                except (StoreError, OSError, ValueError, UnicodeError) as exc:
                    items.append({"save_id": folder.name, "valid": False, "error": str(exc)})
        try:
            current = head_id(root)
            head_error = None
        except (StoreError, OSError, ValueError, UnicodeError) as exc:
            current, head_error = None, str(exc)
        return {"data_dir": str(root), "current_save_id": current, "head_error": head_error,
                "state_token": state_token(root), "snapshots": items}


def archive_mirrors(root):
    directory = plain(root / ".repairs") / uuid.uuid4().hex
    directory.mkdir(parents=True)
    for name in (*NAMES, ".current.json"):
        raw = read_optional(root / name)
        if raw is not None:
            write_sync(directory / (name + ".raw"), raw)
    return str(directory)


def repair(directory, expected_token):
    root = book_path(directory)
    with locked(root):
        state = inspect_locked(root)
        require(state["storage"] == "snapshots", "旧记录先导入")
        require(state["state_token"] == expected_token, "文件已变化，请重新 load", "conflict")
        if state["mirror_state"] == "consistent":
            return describe(root, state)
        archived = archive_mirrors(root)
        _, raws, _ = read_snapshot(root, state["pair"][0]["save_id"])
        for name, raw in zip(NAMES, raws):
            atomic_write(root / name, raw)
        result = describe(root, inspect_locked(root))
        require(result["mirror_state"] == "consistent", "修复后核验失败", "recovery_required")
        result["archived_files"] = archived
        return result


def restore(directory, save_id, expected_token, reason):
    require(isinstance(reason, str) and reason.strip(), "恢复须记录原因")
    root = book_path(directory)
    with locked(root):
        require(state_token(root) == expected_token, "文件已变化，请重新 history", "conflict")
        pair, _, _ = read_snapshot(root, save_id)
        archived = archive_mirrors(root)
        pair = stamp(pair, save_id)
        pair[0]["progress_history"].append({"at": pair[0]["updated_at"], "field": "storage_recovery",
            "before": {"archived_files": archived}, "after": {"restored_from": save_id}, "basis": reason})
        result = publish(root, pair)
        result["archived_files"] = archived
        return result


def import_legacy(directory, expected_token):
    root = book_path(directory)
    with locked(root):
        require(state_token(root) == expected_token, "文件已变化，请重新读取", "conflict")
        require(head_id(root) is None and not (root / ".snapshots").exists(), "只接受未采用快照的旧目录")
        pair = [parse(plain(root / name).read_bytes()) for name in NAMES]
        validate_pair(root, *pair)
        archive_mirrors(root)
        return publish(root, pair)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "load", "save", "history", "repair", "restore", "import-legacy"))
    parser.add_argument("--book-dir", required=True)
    parser.add_argument("--title")
    parser.add_argument("--progress-input", type=Path)
    parser.add_argument("--understanding-input", type=Path)
    parser.add_argument("--expected-save-id")
    parser.add_argument("--expected-token")
    parser.add_argument("--snapshot")
    parser.add_argument("--reason")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(args.book_dir, args.title)
        elif args.command == "load":
            result = load(args.book_dir)
        elif args.command == "history":
            result = history(args.book_dir)
        elif args.command == "save":
            require(args.progress_input and args.understanding_input and args.expected_save_id and args.expected_token,
                    "save 需要两份候选路径、expected-save-id 和 expected-token")
            result = save(args.book_dir, parse(args.progress_input.read_bytes()),
                          parse(args.understanding_input.read_bytes()), args.expected_save_id, args.expected_token)
        elif args.command == "restore":
            require(args.snapshot and args.expected_token and args.reason, "restore 需要 snapshot、expected-token 和 reason")
            result = restore(args.book_dir, args.snapshot, args.expected_token, args.reason)
        else:
            require(args.expected_token, "需要 expected-token")
            operation = repair if args.command == "repair" else import_legacy
            result = operation(args.book_dir, args.expected_token)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, allow_nan=False))
        return 0
    except (StoreError, OSError, ValueError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, StoreError) else "io_or_json_error"
        print(json.dumps({"ok": False, "code": code, "error": str(exc),
                          "next_step": "保留候选文件；load 或 history 核对实际状态，不宣称保存成功"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""使用目录描述符及原子不覆盖提交生成本地 STRM。"""

import os
import secrets
import stat

from .rules import absolute_path


class StrmConflictError(ValueError):
    """目标已存在但不是内容一致的普通 STRM 文件。"""


def _existing(parent: int, name: str, content: bytes) -> bool:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise StrmConflictError("已有 STRM 无法安全打开，拒绝覆盖") from error
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise StrmConflictError("STRM 目标不是普通文件，拒绝覆盖")
    with os.fdopen(descriptor, "rb") as stream:
        if stream.read(len(content) + 1) != content:
            raise StrmConflictError("已有 STRM 内容不同，拒绝覆盖")
    return True


def write_strm(record: dict) -> None:
    """逐级拒绝符号链接；相同内容幂等，冲突不覆盖，失败不改动媒体文件。"""
    root = absolute_path(record["strm_root"])
    target = absolute_path(record["target"])
    if not target.is_relative_to(root) or target == root or target.suffix != ".strm":
        raise ValueError("STRM 输出越过配置根目录或不是 .strm 文件")
    content = str(absolute_path(record["content"])).encode("utf-8")
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        for part in target.parent.parts[1:]:
            try:
                os.mkdir(part, mode=0o755, dir_fd=parent)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        if _existing(parent, target.name, content):
            return
        temporary = f".rapid115-{secrets.token_hex(16)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            if not _existing(parent, target.name, content):
                raise FileNotFoundError("并发写入的 STRM 已消失，需要重新执行") from None
        os.fsync(parent)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        os.close(parent)

"""集中适配 MP 目录管理；当前 SDK 尚未导出目录查询能力。"""

from pathlib import Path


def local_library_roots() -> set[str]:
    """仅取宿主配置的本地整理目标根，不使用下载目录或远端媒体库。"""
    from app.application.directory import DirectoryHelper

    return {str(Path(item.library_path)) for item in DirectoryHelper().get_local_library_dirs()
            if item.library_path}


def validate_library_roots(config: dict, roots: set[str]) -> None:
    """目录移除或改名后拒绝旧映射，避免默默改投其他目标；历史队列保留原快照。"""
    for mapping in config["mappings"]:
        if mapping["library_root"] not in roots:
            raise ValueError(f"整理目录不在MP目录管理的本地媒体库中，请重新选择：{mapping['library_root']}")

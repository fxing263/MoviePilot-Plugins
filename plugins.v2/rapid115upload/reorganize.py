"""仅插件历史页编辑路径，在宿主准入事务内冻结完整计划，执行仍归 MP。"""
from collections.abc import Collection
from contextvars import ContextVar
from dataclasses import replace
from functools import wraps
import inspect
from pathlib import Path
import threading

from fastapi import Body, Depends, Request
from app.schemas.response import Response
from .directories import local_library_roots

_INSTALL_LOCK = threading.RLock()


class PathEditScope:
    """请求私有预览计划，不建立跨请求的来源覆盖表。"""
    def __init__(self) -> None:
        self.collect = True
        self.plans = {}
        self.identities = {}
        self.owned_targets = {}
        self.roots = set()
        # 回调随请求绑定当前插件版本；热更新不替换在途请求的实现。
        self.capture = _capture_checkpoint
        self.freeze = _freeze_pending
        self.bind = _bind_admission


def _identity(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def validate_target(source: str, target: str, roots: Collection[str],
                    allowed_existing: Collection[str] = ()) -> str:
    """拒绝库根外、符号链接、改后缀和占用目标，避免覆盖无关文件。"""
    if not isinstance(target, str) or not target or any(ord(char) < 32 for char in target) or '\\' in target:
        raise ValueError('整理目标路径不能为空')
    path = Path(target)
    if not path.is_absolute() or '..' in path.parts or target.endswith('/'):
        raise ValueError('整理目标必须是无上级跳转的完整绝对文件路径')
    if not any(path != Path(root) and path.is_relative_to(Path(root)) for root in roots):
        raise ValueError('整理目标必须位于 MP 目录管理的本地媒体库内')
    for candidate in (path, *path.parents):
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise ValueError('整理目标的父路径不是目录')
        if candidate.is_symlink():
            raise ValueError('整理目标不能经过符号链接')
    if path.suffix.lower() != Path(source).suffix.lower():
        raise ValueError('修改路径不能改变文件扩展名')
    if str(path) == str(Path(source)):
        raise ValueError('整理目标不能与源文件相同')
    if path.exists() and (not path.is_file() or str(path) not in allowed_existing):
        raise ValueError(f'目标已经存在，不能覆盖：{path}')
    return str(path)


def _capture_checkpoint(scope, checkpoint):
    source = checkpoint.planning_input.source_fileitem
    if (source.get('storage') != 'local' or source.get('type') == 'dir'
            or checkpoint.target_storage != 'local' or len(checkpoint.items) != 1
            or checkpoint.skip_reason or checkpoint.rejection_error
            or checkpoint.legacy_transfer_providers):
        raise ValueError('路径编辑仅支持本地单文件的宿主整理计划')
    key = str(source['path'])
    if key in scope.plans:
        raise ValueError('预览包含重复源文件，不能安全修改目标')
    scope.plans[key] = checkpoint
    scope.identities[key] = _identity(key)


def _freeze_pending(scope, pending, arguments):
    """仅在新建行的原 UoW 内写计划，提交后卸载插件也可恢复。"""
    from app.application.transfer.workflow import TransferPlanningInput
    if pending is None:
        return pending
    source = arguments['src_path']
    checkpoint = scope.plans.get(source)
    if pending.task_id != arguments['task_id']:
        frozen = getattr(pending, 'checkpoint_payload', None) or {}
        if checkpoint is None or frozen.get('final_target_path') != checkpoint.final_target_path:
            raise ValueError('已有未完成整理任务，不能修改其目标路径')
        return pending
    if checkpoint is None or arguments['storage'] != 'local':
        raise ValueError('实际整理来源与确认预览不一致，请重新预览')
    if _identity(source) != scope.identities[source]:
        raise ValueError('源文件在预览后发生变化，请重新预览')
    validate_target(source, checkpoint.final_target_path, scope.roots, scope.owned_targets.get(source, set()))
    planning_input = TransferPlanningInput.from_payload(arguments['planning_input'])
    checkpoint = replace(checkpoint, planning_input=planning_input, preview=False)
    pending.state = 'planned'
    pending.planned_at = arguments['now_time']
    pending.checkpoint_version = checkpoint.schema_version
    pending.checkpoint_payload = checkpoint.to_payload()
    return pending


def _bind_admission(task, admission):
    if admission.checkpoint is None:
        raise ValueError('自定义路径未冻结，拒绝执行')
    task.bind_plan_checkpoint(admission.checkpoint)


def install_path_adapter() -> ContextVar:
    """仅显式端点上下文适配私有契约，未知版本拒绝而不退回默认路径。"""
    from app.chain.transfer.execution import TransferExecutionOwner
    from app.chain.transfer.plan import TransferPlanningOwner
    from app.db.oper.transferpending import TransferPendingOper
    from app.db.models.transferpending import TransferPending
    plan_name = '_TransferChain__plan_host_transfer'
    admit_name = '_TransferChain__admit_transfer'
    with _INSTALL_LOCK:
        previous = getattr(TransferPendingOper.stage_admit, '_rapid115_path_context', None)
        if previous is not None:
            return previous
        plan = getattr(TransferPlanningOwner, plan_name, None)
        admit = getattr(TransferExecutionOwner, admit_name, None)
        stage = TransferPendingOper.stage_admit
        if (not callable(plan) or not callable(admit)
                or not all(hasattr(TransferPending, name) for name in ('checkpoint_version', 'checkpoint_payload', 'planned_at'))
                or not {'task_id', 'planning_input', 'input_fingerprint'} <= set(inspect.signature(stage).parameters)
                or 'planning_input' not in inspect.signature(plan).parameters):
            raise ValueError('当前 MP 版本不支持安全冻结自定义整理路径')
        context = ContextVar('rapid115_path_edit', default=None)

        @wraps(plan)
        def plan_wrapper(owner, task, **kwargs):
            checkpoint = plan(owner, task, **kwargs)
            scope = context.get()
            if scope is not None and scope.collect:
                scope.capture(scope, checkpoint)
            return checkpoint

        @wraps(stage)
        def stage_wrapper(owner, **kwargs):
            pending = stage(owner, **kwargs)
            scope = context.get()
            if scope is not None and not scope.collect:
                return scope.freeze(scope, pending, kwargs)
            return pending

        @wraps(admit)
        def admit_wrapper(owner, task):
            admission = admit(owner, task)
            scope = context.get()
            if scope is not None and not scope.collect:
                scope.bind(task, admission)
            return admission

        stage_wrapper._rapid115_path_context = context
        setattr(TransferPlanningOwner, plan_name, plan_wrapper)
        setattr(TransferExecutionOwner, admit_name, admit_wrapper)
        TransferPendingOper.stage_admit = stage_wrapper
        return context


def _prepare(scope, request, overrides, history_query):
    """先确认历史来源、完整预览和冲突，再允许 MP 清理旧历史。"""
    from app.api.endpoints.transfer import _route_manual_transfer
    if not request.logid and not request.logids:
        raise ValueError('路径编辑仅用于媒体整理记录中的重新整理')
    scope.roots = local_library_roots()
    for history_id in request.logids or [request.logid]:
        history = history_query.get(history_id)
        if history is None:
            raise ValueError('整理记录已改变，请刷新后重试')
        destination = history.dest_fileitem
        original = history.src_fileitem
        if hasattr(destination, 'model_dump'):
            destination = destination.model_dump()
        if hasattr(original, 'model_dump'):
            original = original.model_dump()
        if history.status and 'move' in str(history.mode):
            original = destination
        if isinstance(destination, dict) and destination.get('storage') == 'local' and isinstance(original, dict):
            scope.owned_targets.setdefault(original['path'], set()).add(str(Path(destination['path'])))
    preview = _route_manual_transfer(request.model_copy(deep=True, update={'preview': True}),
                                     background=False, history_query=history_query)
    if not preview.success or not scope.plans:
        raise ValueError('整理预览未全部成功，请修正后重新预览')
    if not isinstance(overrides, list) or not overrides:
        raise ValueError('缺少修改后的目标路径')
    seen = set()
    for override in overrides:
        if not isinstance(override, dict) or set(override) != {'source', 'target'}:
            raise ValueError('目标路径修改参数无效')
        source = override['source']
        if not isinstance(source, str) or source not in scope.plans or source in seen:
            raise ValueError('修改来源与整理预览不一致或重复')
        seen.add(source)
        checkpoint = scope.plans[source]
        target = validate_target(source, override['target'], scope.roots, scope.owned_targets.get(source, set()))
        scope.plans[source] = replace(checkpoint, final_target_path=target, overwrite_mode="never",
                                      root_target_path=max((root for root in scope.roots if Path(target).is_relative_to(root)), key=len),
                                      items=(replace(checkpoint.items[0], target_path=target),))
    targets = set()
    for source, checkpoint in scope.plans.items():
        forbidden = set().union(*(paths for other, paths in scope.owned_targets.items() if other != source))
        if checkpoint.final_target_path in forbidden or checkpoint.final_target_path in scope.plans:
            raise ValueError('目标不能占用其他整理记录的源文件或旧目标路径')
        target = validate_target(source, checkpoint.final_target_path, scope.roots, scope.owned_targets.get(source, set()))
        if target in targets:
            raise ValueError('多个源文件不能整理到相同目标')
        targets.add(target)
    return preview


def _history_query(request: Request):
    """私有历史接口按请求加载，旧版宿主仍可注册和使用其他插件功能。"""
    try:
        from app.api.context import get_host_runtime
        from app.api.dependencies.history import get_transfer_history_lookup_service
    except (ImportError, AttributeError):
        return None
    return get_transfer_history_lookup_service(runtime=get_host_runtime(request))


def _host_capabilities():
    """缺少兼容契约时只关闭路径编辑，避免整个插件注册失败。"""
    try:
        from app.api.endpoints.transfer import _route_manual_transfer
        from app.schemas.transfer import ManualTransferItem
        context = install_path_adapter()
    except (ImportError, AttributeError) as error:
        raise ValueError('当前 MP 版本不支持安全冻结自定义整理路径') from error
    return _route_manual_transfer, ManualTransferItem, context


def reorganize(payload: dict = Body(...), background: bool = False,
               history_query: object = Depends(_history_query)) -> Response:
    """只读重规划后冻结指定目标，历史、整理事件及 115 入队沿用宿主实际结果。"""
    context = None
    token = None
    try:
        if history_query is None:
            raise ValueError('当前 MP 版本不支持安全冻结自定义整理路径')
        route, request_type, context = _host_capabilities()
        request = request_type.model_validate(payload.get('request'))
        scope = PathEditScope()
        token = context.set(scope)
        preview = _prepare(scope, request, payload.get('overrides'), history_query)
        if request.preview:
            for item in preview.data['items']:
                checkpoint = scope.plans.get(item.get('source'))
                if checkpoint:
                    item['target'] = checkpoint.final_target_path
                    item['target_dir'] = str(Path(checkpoint.final_target_path).parent)
            return preview
        scope.collect = False
        return route(request, background=background, history_query=history_query)
    except (ValueError, TypeError, OSError) as error:
        return Response(success=False, message=str(error))
    finally:
        if context is not None and token is not None:
            context.reset(token)

"""Safe, stage-aware errors for browser collection and input preparation.

Playwright errors may include request URLs, credentials and response payloads.
Only finite diagnostic categories and curated business errors cross this boundary.
"""

import re

from fengshen_bill import BillCollectionError, safe_operation_failure


PHASE_LABELS = {
    "browser_launch": "启动 Edge 浏览器",
    "session_restore": "恢复风神登录会话",
    "page_create": "创建风神采集页面",
    "window_conceal": "将 Edge 切换到后台",
    "navigation": "打开风神业务页面",
    "auth_check": "检查风神登录状态",
    "collect": "采集风神资料",
    "input_validation": "校验采集资料",
    "unknown": "准备风神采集",
}

DATASET_LABELS = {
    "agency_daily": "配送费和违规扣款",
    "rider_monthly": "风神骑手月度 UB 账单",
    "issue_orders": "运单及问题单",
    "receive_account": "骑手风神绑定",
    "rider_detail": "骑手数据明细",
    "rider_info": "骑手信息导出",
}

PHASE_HINTS = {
    "browser_launch": "无法启动 Edge 浏览器，请检查 Edge 和 Playwright 采集依赖",
    "session_restore": "无法恢复本机风神会话，请重新登录后重试",
    "page_create": "无法创建风神采集页面，请重新启动任务",
    "window_conceal": "无法将 Edge 切换到后台，请检查浏览器",
    "navigation": "无法打开风神业务页面，请检查本机网络后重试",
    "auth_check": "风神登录检查未完成，请检查官方登录页及账号权限后重试",
    "collect": "风神资料采集未完成，请检查网络和页面配置后重试",
    "input_validation": "采集资料校验未完成，请检查本次文件是否完整、可读取",
    "unknown": "风神采集准备未完成，请检查采集依赖及运行状态",
}

REASON_HINTS = {
    "browser_unavailable": "未找到可用的 Edge 浏览器或采集依赖，请检查安装后重试",
    "dependency_missing": "缺少采集依赖，请检查 Playwright 安装",
    "target_closed": "浏览器或采集页面已关闭，请重新启动任务",
    "certificate_error": "风神页面的 HTTPS 证书校验失败，请检查公司网络、证书和代理配置",
    "name_resolution_failed": "无法解析风神域名，请检查本机网络和 DNS 配置",
    "connection_error": "连接风神页面失败，请检查本机网络和代理配置",
    "navigation_interrupted": "页面跳转被中断，请重新启动任务并检查登录页面",
    "context_destroyed": "页面正在跳转或刷新，操作上下文已失效，请重试",
    "timeout_response": "等待风神接口响应超时，请检查网络和平台状态",
    "timeout_download": "等待风神文件下载超时，请检查网络和平台导出状态",
    "timeout_locator": "等待页面控件超时，请检查登录状态和页面配置",
    "timeout_other": "浏览器操作超时，请检查网络和页面状态",
    "permission_denied": "读取或保存资料被拒绝，请检查运行账户的目录权限",
}

# Business errors are normally fixed messages defined by the application. Refuse
# obvious sensitive payloads even if a future caller incorrectly wraps one in a
# BillCollectionError; the original error must never be appended to a hint.
_SENSITIVE_MESSAGE = re.compile(
    r"https?://|wss?://|\bBearer\s+|"
    r"\b(?:access[_-]?token|refresh[_-]?token|token|cookie|authorization|password|secret|"
    r"sms[_-]?code)\s*[=:]|"
    r"(?:手机号|手机号码|验证码|身份证(?:号)?)\s*[=:]\s*\S+|"
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\d)",
    re.IGNORECASE,
)


class CollectionFailure(BillCollectionError):
    """A public error message plus diagnostics containing no raw exception text."""

    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.message = message
        self.diagnostics = diagnostics


def failure_reason(exc, diagnostics=None):
    """Classify only known error markers, without returning exception text."""
    diagnostics = diagnostics if diagnostics is not None else safe_operation_failure(exc)
    text = str(exc)
    if diagnostics["target_closed"] or type(exc).__name__ == "TargetClosedError":
        return "target_closed"
    if "net::ERR_CERT" in text:
        return "certificate_error"
    if "net::ERR_NAME_NOT_RESOLVED" in text:
        return "name_resolution_failed"
    if any(marker in text for marker in (
        "net::ERR_CONNECTION", "net::ERR_NETWORK_CHANGED", "net::ERR_INTERNET_DISCONNECTED",
        "net::ERR_TIMED_OUT", "net::ERR_TUNNEL_CONNECTION_FAILED",
    )):
        return "connection_error"
    if diagnostics["navigation_interrupted"]:
        return "navigation_interrupted"
    if any(marker in text for marker in (
        "Execution context was destroyed", "Frame was detached", "Cannot find context with specified id",
    )):
        return "context_destroyed"
    if type(exc).__name__ == "TimeoutError":
        return "timeout_" + (diagnostics["timeout_kind"] or "other")
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "dependency_missing"
    if any(marker in text for marker in (
        "Executable doesn't exist", "Chromium distribution 'msedge' is not found",
    )):
        return "browser_unavailable"
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, BillCollectionError):
        return "business_error"
    return "operation_failed"


def collection_failure(exc, phase, dataset=""):
    """Wrap an error in safe user guidance and stage-specific diagnostics.

    ``phase`` and ``dataset`` are allowlisted so caller-supplied values cannot
    accidentally insert sensitive data into diagnostics or the public message.
    Existing CollectionFailure objects are returned unchanged, retaining the
    deepest operation's stage and the original exception type.
    """
    if isinstance(exc, CollectionFailure):
        return exc
    phase = phase if phase in PHASE_LABELS else "unknown"
    dataset = dataset if dataset in DATASET_LABELS else ""
    diagnostics = safe_operation_failure(exc)
    reason = failure_reason(exc, diagnostics)
    diagnostics.update(phase=phase, dataset=dataset, reason_code=reason)
    business_message = str(exc)
    if isinstance(exc, BillCollectionError) and business_message.strip() and not _SENSITIVE_MESSAGE.search(business_message):
        message = business_message
    elif reason in REASON_HINTS:
        scope = PHASE_LABELS[phase]
        if dataset:
            scope += "（" + DATASET_LABELS[dataset] + "）"
        message = scope + "失败：" + REASON_HINTS[reason] + "；核算已停止"
    else:
        message = PHASE_HINTS[phase] + "；核算已停止"
    return CollectionFailure(message, diagnostics)

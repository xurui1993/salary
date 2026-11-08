"""Keep generic legacy file APIs outside the authenticated download namespace."""

import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote

from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
_READ_PATHS = {"/api/files", "/api/files_tree", "/api/config_excel_data", "/api/dialog/smart_source",
               "/api/open/config", "/api/open/explorer", "/api/parttime/fengshen/plan", "/api/rider_sources/plan"}
_PATH_KEY = re.compile(r"^(path|.*path|.*dir|.*directory|paths)$", re.I)


class LegacyDownloadBoundary:
    def __init__(self, app, root=ROOT):
        self.app = app
        self.root = Path(root).resolve()

    def protected_roots(self):
        # This host-only registry includes archives from previous configurations.
        # Missing or corrupt state is rejected, never interpreted as no archives.
        value = json.loads((self.root / "backend/.local_downloads/protected_roots.json").read_text(encoding="utf-8"))
        roots = value.get("roots")
        if not isinstance(roots, list) or any(not isinstance(item, str) or not Path(item).is_absolute() for item in roots):
            raise ValueError("Invalid download directory registry")
        return [self.root / "backend/.local_downloads", self.root / "backend/.local_auth", self.root / ".local_auth",
                self.root / "outputs/fengshen_downloads", *(Path(item).resolve() for item in roots)]

    def allowed_path(self, value, *, write=False, recursive=False):
        try:
            candidate = Path(value)
            target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
            personal_root = os.environ.get('PERSONAL_INSTANCE_ROOT')
            if personal_root and not target.is_relative_to(Path(personal_root).resolve()):
                return False
            for folder in self.protected_roots():
                folder = folder.resolve()
                if target.is_relative_to(folder) or (recursive and folder.is_relative_to(target)):
                    return False
            if recursive and target.is_dir():
                folders = [Path(folder).resolve() for folder in self.protected_roots()]
                seen = set()
                remaining = [target]
                count = 0
                while remaining:
                    current = remaining.pop()
                    resolved = current.resolve()
                    count += 1
                    if count > 50_000 or resolved in seen or any(resolved.is_relative_to(folder) for folder in folders):
                        return False
                    seen.add(resolved)
                    if current.is_dir():
                        remaining.extend(current.iterdir())
            if write and target.is_relative_to(self.root):
                return any(target.is_relative_to((self.root / name).resolve()) for name in
                           ("data", "uploads", "outputs", "system_templates"))
            return True
        except (OSError, ValueError, RuntimeError, TypeError):
            return False

    def body_allowed(self, value, route, key=""):
        if isinstance(value, str) and value and _PATH_KEY.fullmatch(key):
            return self.allowed_path(value, write=route not in _READ_PATHS, recursive=route != "/api/files" and key.lower() != "basepath")
        if isinstance(value, list):
            return all(self.body_allowed(item, route, key) for item in value)
        if isinstance(value, dict):
            return all(self.body_allowed(child, route, name) for name, child in value.items())
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        route = scope.get("path", "")
        if any(route == prefix or route.startswith(prefix + "/") for prefix in
               ("/api/fengshen-downloads", "/api/parttime/fengshen/auth")):
            return await self.app(scope, receive, send)
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        query = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="replace"))
        owner = unquote(headers.get("x-workspace-id") or query.get("workspace_id", [""])[0])
        denied = re.sub(r"[^a-z0-9_-]", "", owner.casefold()).startswith("account_")
        denied = denied or not self.body_allowed(query, route)
        messages = []
        if headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json":
            size = 0
            while True:
                message = await receive()
                messages.append(message)
                if message["type"] != "http.request":
                    break
                size += len(message.get("body", b""))
                if size > 16 * 1024 * 1024:
                    return await JSONResponse({"detail": "请求体过大"}, status_code=413)(scope, receive, send)
                if not message.get("more_body", False):
                    break
            try:
                value = json.loads(b"".join(message.get("body", b"") for message in messages))
                denied = denied or not self.body_allowed(value, route)
            except (ValueError, UnicodeError):
                pass  # Preserve the endpoint's normal malformed-JSON response.
        if denied:
            return await JSONResponse({"detail": "下载中心资料及账号状态须通过下载中心授权入口访问"}, status_code=403)(scope, receive, send)
        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()
        return await self.app(scope, replay, send)

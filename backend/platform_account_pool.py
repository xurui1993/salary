"""Multi-account local session pool for each business platform.

Preserves multiple encrypted session snapshots per (workspace/shared, source)
so users can keep multiple platform accounts logged in simultaneously and
switch the active account in one click without re-scanning QR codes or
re-entering credentials.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import shutil
from typing import Any

from fastapi import HTTPException
import binding_source_auth as sources


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _managed_files(source: str, primary_files: list[Path]) -> list[Path]:
    files = list(primary_files)
    if source in ('baize', 'benlai'):
        try:
            cred = sources.credentials_path(source)
            if cred not in files:
                files.append(cred)
        except Exception:
            pass
    return files


def pool_dir(source: str, primary_files: list[Path]) -> Path:
    base_parent = primary_files[0].parent
    return base_parent / '.account_pool' / source


def _manifest_path(source: str, primary_files: list[Path]) -> Path:
    return pool_dir(source, primary_files) / 'manifest.json'


def load_manifest(source: str, primary_files: list[Path]) -> dict[str, Any]:
    path = _manifest_path(source, primary_files)
    if not path.exists():
        return {'active_slot_id': None, 'pending_new_slot': False, 'accounts': []}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            return {'active_slot_id': None, 'pending_new_slot': False, 'accounts': []}
        accounts = raw.get('accounts')
        return {
            'active_slot_id': raw.get('active_slot_id') if isinstance(raw.get('active_slot_id'), str) else None,
            'pending_new_slot': bool(raw.get('pending_new_slot')),
            'accounts': [row for row in accounts if isinstance(row, dict) and isinstance(row.get('slot_id'), str)]
            if isinstance(accounts, list)
            else [],
        }
    except Exception:
        return {'active_slot_id': None, 'pending_new_slot': False, 'accounts': []}


def save_manifest(source: str, primary_files: list[Path], manifest: dict[str, Any]) -> None:
    path = _manifest_path(source, primary_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _copy_active_to_slot(source: str, primary_files: list[Path], slot_id: str) -> None:
    sdir = pool_dir(source, primary_files) / slot_id
    sdir.mkdir(parents=True, exist_ok=True)
    for src in _managed_files(source, primary_files):
        dst = sdir / src.name
        if src.exists() and not src.is_symlink():
            dst.write_bytes(src.read_bytes())
        elif dst.exists():
            dst.unlink(missing_ok=True)


def _slot_has_primary_files(source: str, primary_files: list[Path], slot_id: str) -> bool:
    sdir = pool_dir(source, primary_files) / slot_id
    if not sdir.exists():
        return False
    return any((sdir / p.name).exists() for p in primary_files)


def sync_pool_with_status(
    source: str,
    primary_files: list[Path],
    status_dict: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Synchronize current on-disk session with the multi-account pool and return
    (accounts_view, active_slot_id, pending_new_slot).
    """
    manifest = load_manifest(source, primary_files)
    accounts: list[dict[str, Any]] = manifest['accounts']
    active_slot_id: str | None = manifest.get('active_slot_id')
    pending_new_slot: bool = bool(manifest.get('pending_new_slot'))

    saved_on_disk = bool(status_dict.get('saved'))
    busy = bool(status_dict.get('busy')) or status_dict.get('state') in (
        'starting',
        'waiting_login',
        'refreshing',
        'sending',
        'verifying',
        'checking',
    )
    fingerprint = str(status_dict.get('session_version') or '')
    account_label = str(
        status_dict.get('account_label') or status_dict.get('credential_account') or ''
    ).strip()
    organization = str(status_dict.get('organization') or '').strip()
    state = str(status_dict.get('state') or ('saved' if saved_on_disk else 'signed_out'))
    credential_saved = bool(status_dict.get('credential_saved'))

    changed = False

    if saved_on_disk and not busy:
        target_slot: dict[str, Any] | None = None

        if pending_new_slot:
            # Match by identical fingerprint or identical non-empty account_label first
            for item in accounts:
                if fingerprint and item.get('session_version') == fingerprint:
                    target_slot = item
                    break
                if account_label and item.get('account_label') == account_label:
                    target_slot = item
                    break
            if target_slot is None:
                new_id = 'acct_' + secrets.token_hex(4)
                target_slot = {
                    'slot_id': new_id,
                    'account_label': account_label,
                    'alias': '',
                    'organization': organization,
                    'account_type': '',
                    'region_text': '',
                    'state': state,
                    'session_version': fingerprint,
                    'credential_saved': credential_saved,
                    'created_at': _now_iso(),
                    'updated_at': _now_iso(),
                }
                accounts.append(target_slot)
            active_slot_id = target_slot['slot_id']
            pending_new_slot = False
            changed = True
        else:
            if active_slot_id:
                target_slot = next((item for item in accounts if item.get('slot_id') == active_slot_id), None)

            # If active_slot already had a different non-empty account_label, preserve it and open/match another slot
            if (
                target_slot is not None
                and account_label
                and target_slot.get('account_label')
                and target_slot.get('account_label') != account_label
            ):
                matched = next(
                    (item for item in accounts if item.get('account_label') == account_label),
                    None,
                )
                if matched is not None:
                    target_slot = matched
                else:
                    new_id = 'acct_' + secrets.token_hex(4)
                    target_slot = {
                        'slot_id': new_id,
                        'account_label': account_label,
                        'alias': '',
                        'organization': organization,
                        'account_type': '',
                        'region_text': '',
                        'state': state,
                        'session_version': fingerprint,
                        'credential_saved': credential_saved,
                        'created_at': _now_iso(),
                        'updated_at': _now_iso(),
                    }
                    accounts.append(target_slot)
                active_slot_id = target_slot['slot_id']
                changed = True

            if target_slot is None:
                # Match by fingerprint or account_label, or create the initial slot
                for item in accounts:
                    if fingerprint and item.get('session_version') == fingerprint:
                        target_slot = item
                        break
                    if account_label and item.get('account_label') == account_label:
                        target_slot = item
                        break
                if target_slot is None:
                    new_id = 'acct_' + secrets.token_hex(4)
                    target_slot = {
                        'slot_id': new_id,
                        'account_label': account_label,
                        'alias': '',
                        'organization': organization,
                        'account_type': '',
                        'region_text': '',
                        'state': state,
                        'session_version': fingerprint,
                        'credential_saved': credential_saved,
                        'created_at': _now_iso(),
                        'updated_at': _now_iso(),
                    }
                    accounts.append(target_slot)
                active_slot_id = target_slot['slot_id']
                changed = True

        # Sync metadata and file snapshot into target_slot
        need_file_copy = (
            target_slot.get('session_version') != fingerprint
            or not _slot_has_primary_files(source, primary_files, target_slot['slot_id'])
        )
        if account_label and target_slot.get('account_label') != account_label:
            target_slot['account_label'] = account_label
            changed = True
        if organization and target_slot.get('organization') != organization:
            target_slot['organization'] = organization
            changed = True
        if state and target_slot.get('state') != state:
            target_slot['state'] = state
            changed = True
        if fingerprint and target_slot.get('session_version') != fingerprint:
            target_slot['session_version'] = fingerprint
            changed = True
        if target_slot.get('credential_saved') != credential_saved:
            target_slot['credential_saved'] = credential_saved
            changed = True

        if need_file_copy:
            try:
                _copy_active_to_slot(source, primary_files, target_slot['slot_id'])
                target_slot['updated_at'] = _now_iso()
                changed = True
            except OSError:
                pass

    # Filter out any broken slots whose snapshot files no longer exist (unless currently active on disk)
    valid_accounts: list[dict[str, Any]] = []
    for item in accounts:
        sid = item['slot_id']
        if (sid == active_slot_id and saved_on_disk) or _slot_has_primary_files(source, primary_files, sid):
            valid_accounts.append(item)
        else:
            changed = True

    if active_slot_id and not any(item['slot_id'] == active_slot_id for item in valid_accounts):
        active_slot_id = valid_accounts[0]['slot_id'] if (valid_accounts and saved_on_disk) else None
        changed = True

    if changed:
        manifest['accounts'] = valid_accounts
        manifest['active_slot_id'] = active_slot_id
        manifest['pending_new_slot'] = pending_new_slot
        try:
            save_manifest(source, primary_files, manifest)
        except OSError:
            pass

    view_accounts: list[dict[str, Any]] = []
    for idx, item in enumerate(valid_accounts, start=1):
        sid = item['slot_id']
        is_active = bool(saved_on_disk and sid == active_slot_id and not pending_new_slot)
        label = str(item.get('account_label') or '').strip()
        alias = str(item.get('alias') or '').strip()
        view_accounts.append({
            'slot_id': sid,
            'account_label': label or alias or f'已登录账户 #{idx}',
            'alias': alias,
            'organization': str(item.get('organization') or '').strip(),
            'account_type': str(item.get('account_type') or '').strip(),
            'region_text': str(item.get('region_text') or '').strip(),
            'state': str(item.get('state') or 'saved'),
            'is_active': is_active,
            'credential_saved': bool(item.get('credential_saved')),
            'session_version': str(item.get('session_version') or ''),
            'updated_at': str(item.get('updated_at') or ''),
        })

    return view_accounts, (active_slot_id if saved_on_disk and not pending_new_slot else None), pending_new_slot


def enrich_active_slot_identity(
    source: str,
    primary_files: list[Path],
    *,
    account_label: str = '',
    organization: str = '',
    account_type: str = '',
    region_text: str = '',
) -> None:
    manifest = load_manifest(source, primary_files)
    active_slot_id = manifest.get('active_slot_id')
    if not active_slot_id:
        return
    slot = next((item for item in manifest['accounts'] if item.get('slot_id') == active_slot_id), None)
    if slot is None:
        return
    changed = False
    if account_label and slot.get('account_label') != account_label:
        slot['account_label'] = account_label
        changed = True
    if organization and slot.get('organization') != organization:
        slot['organization'] = organization
        changed = True
    if account_type and account_type != 'unknown' and slot.get('account_type') != account_type:
        slot['account_type'] = account_type
        changed = True
    if region_text and slot.get('region_text') != region_text:
        slot['region_text'] = region_text
        changed = True
    if changed:
        slot['updated_at'] = _now_iso()
        try:
            save_manifest(source, primary_files, manifest)
        except OSError:
            pass


def prepare_add_account(
    source: str,
    primary_files: list[Path],
    current_status: dict[str, Any],
) -> None:
    """Snapshot the current active session into the pool and clear the active
    session files so the user can log into an additional account without
    losing existing logged-in accounts.
    """
    sync_pool_with_status(source, primary_files, current_status)
    manifest = load_manifest(source, primary_files)
    active_slot_id = manifest.get('active_slot_id')
    if active_slot_id and any(p.exists() for p in primary_files):
        _copy_active_to_slot(source, primary_files, active_slot_id)

    for path in _managed_files(source, primary_files):
        path.unlink(missing_ok=True)

    manifest['pending_new_slot'] = True
    manifest['active_slot_id'] = None
    save_manifest(source, primary_files, manifest)


def activate_slot(
    source: str,
    primary_files: list[Path],
    slot_id: str,
    current_status: dict[str, Any],
) -> dict[str, Any]:
    """Switch the active platform session to `slot_id` by restoring its
    encrypted session files into the primary working path.
    """
    if current_status.get('saved'):
        sync_pool_with_status(source, primary_files, current_status)
    manifest = load_manifest(source, primary_files)
    current_active = manifest.get('active_slot_id')
    if current_active and current_active != slot_id and any(p.exists() for p in primary_files):
        _copy_active_to_slot(source, primary_files, current_active)

    slot = next((item for item in manifest['accounts'] if item.get('slot_id') == slot_id), None)
    if slot is None:
        raise HTTPException(404, '所选平台账户不存在或已移除')

    sdir = pool_dir(source, primary_files) / slot_id
    if not _slot_has_primary_files(source, primary_files, slot_id):
        raise HTTPException(409, '该账户本地会话已失效，请重新登录')

    for dst in _managed_files(source, primary_files):
        src = sdir / dst.name
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        else:
            dst.unlink(missing_ok=True)

    manifest['active_slot_id'] = slot_id
    manifest['pending_new_slot'] = False
    slot['updated_at'] = _now_iso()
    save_manifest(source, primary_files, manifest)
    return dict(slot)


def update_slot_alias(
    source: str,
    primary_files: list[Path],
    slot_id: str,
    alias: str,
) -> dict[str, Any]:
    manifest = load_manifest(source, primary_files)
    slot = next((item for item in manifest['accounts'] if item.get('slot_id') == slot_id), None)
    if slot is None:
        raise HTTPException(404, '所选平台账户不存在或已移除')
    clean_alias = re.sub(r'[\x00-\x1f\x7f]', '', str(alias or '').strip())[:40]
    slot['alias'] = clean_alias
    slot['updated_at'] = _now_iso()
    save_manifest(source, primary_files, manifest)
    return dict(slot)


def remove_slot(
    source: str,
    primary_files: list[Path],
    slot_id: str,
) -> tuple[bool, str | None]:
    """Remove `slot_id` from the pool. Returns (was_active, next_slot_id)."""
    manifest = load_manifest(source, primary_files)
    before_len = len(manifest['accounts'])
    manifest['accounts'] = [item for item in manifest['accounts'] if item.get('slot_id') != slot_id]
    if len(manifest['accounts']) == before_len:
        raise HTTPException(404, '所选平台账户不存在或已移除')

    sdir = pool_dir(source, primary_files) / slot_id
    shutil.rmtree(sdir, ignore_errors=True)

    was_active = manifest.get('active_slot_id') == slot_id
    next_slot_id: str | None = None
    if was_active:
        next_slot_id = manifest['accounts'][0]['slot_id'] if manifest['accounts'] else None
        manifest['active_slot_id'] = next_slot_id
        manifest['pending_new_slot'] = False

    save_manifest(source, primary_files, manifest)
    return was_active, next_slot_id


def remove_active_slot_on_disconnect(source: str, primary_files: list[Path]) -> None:
    """Called when the active session is explicitly logged out / disconnected."""
    manifest = load_manifest(source, primary_files)
    active_id = manifest.get('active_slot_id')
    if not active_id:
        return
    manifest['accounts'] = [item for item in manifest['accounts'] if item.get('slot_id') != active_id]
    sdir = pool_dir(source, primary_files) / active_id
    shutil.rmtree(sdir, ignore_errors=True)
    manifest['active_slot_id'] = None
    manifest['pending_new_slot'] = False
    try:
        save_manifest(source, primary_files, manifest)
    except OSError:
        pass

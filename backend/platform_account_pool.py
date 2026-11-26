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
import threading
from typing import Any

from fastapi import HTTPException
import binding_source_auth as sources

_POOL_LOCKS_GUARD = threading.Lock()
_POOL_LOCKS: dict[str, threading.RLock] = {}


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


def _pool_lock(source: str, primary_files: list[Path]) -> threading.RLock:
    key = str(pool_dir(source, primary_files).resolve())
    with _POOL_LOCKS_GUARD:
        lock = _POOL_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _POOL_LOCKS[key] = lock
        return lock


def _manifest_path(source: str, primary_files: list[Path]) -> Path:
    return pool_dir(source, primary_files) / 'manifest.json'


def _norm_text(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip())


def _is_masked_or_phone(value: str) -> bool:
    text = _norm_text(value)
    return bool(re.fullmatch(r'1\d{2}\*{2,6}\d{2,4}', text) or re.fullmatch(r'1\d{10}', text))


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
            tmp = dst.with_suffix(dst.suffix + '.part')
            tmp.write_bytes(src.read_bytes())
            tmp.replace(dst)
        elif dst.exists():
            dst.unlink(missing_ok=True)


def _slot_has_primary_files(source: str, primary_files: list[Path], slot_id: str) -> bool:
    sdir = pool_dir(source, primary_files) / slot_id
    if not sdir.exists():
        return False
    return any((sdir / p.name).exists() for p in primary_files)


def _same_account_identity(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True when two pool slots represent the exact same platform account."""
    fp_a = _norm_text(a.get('session_version'))
    fp_b = _norm_text(b.get('session_version'))
    if fp_a and fp_b and fp_a == fp_b:
        return True

    org_a = _norm_text(a.get('organization'))
    org_b = _norm_text(b.get('organization'))
    if org_a and org_b and org_a != org_b:
        return False

    label_a = _norm_text(a.get('account_label'))
    label_b = _norm_text(b.get('account_label'))
    if label_a and label_b and label_a == label_b:
        return True

    cred_a = _norm_text(a.get('credential_account'))
    cred_b = _norm_text(b.get('credential_account'))
    if cred_a and cred_b and cred_a == cred_b:
        if not label_a or not label_b or label_a == label_b or _is_masked_or_phone(label_a) or _is_masked_or_phone(label_b):
            return True
    if cred_a and label_b and cred_a == label_b:
        return True
    if cred_b and label_a and cred_b == label_a:
        return True

    return False


def _merge_slot_metadata(keeper: dict[str, Any], donor: dict[str, Any]) -> bool:
    """Merge non-empty metadata fields from `donor` into `keeper` without losing richer labels."""
    changed = False
    for field in ('alias', 'organization', 'account_type', 'region_text', 'credential_account'):
        keeper_val = _norm_text(keeper.get(field))
        donor_val = _norm_text(donor.get(field))
        if not keeper_val and donor_val and not (field == 'account_type' and donor_val == 'unknown'):
            keeper[field] = donor_val
            changed = True

    keeper_label = _norm_text(keeper.get('account_label'))
    donor_label = _norm_text(donor.get('account_label'))
    if donor_label and (not keeper_label or (_is_masked_or_phone(keeper_label) and not _is_masked_or_phone(donor_label))):
        keeper['account_label'] = donor_label
        changed = True

    if not keeper.get('credential_saved') and donor.get('credential_saved'):
        keeper['credential_saved'] = True
        changed = True

    if keeper.get('state') != 'ready' and donor.get('state') == 'ready':
        keeper['state'] = 'ready'
        changed = True

    return changed


def _deduplicate_accounts(
    source: str,
    primary_files: list[Path],
    accounts: list[dict[str, Any]],
    active_slot_id: str | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Collapse duplicate slots sharing the same session fingerprint or account identity.

    Always preserves the active slot (if present among duplicates), merges non-empty
    alias/organization metadata from duplicates, and removes duplicate snapshot folders.
    """
    if len(accounts) <= 1:
        return accounts, active_slot_id, False

    deduped: list[dict[str, Any]] = []
    removed_ids: list[str] = []
    changed = False

    # Process the active slot first so it naturally becomes the keeper if duplicated.
    ordered = sorted(
        accounts,
        key=lambda item: (
            0 if item.get('slot_id') == active_slot_id else 1,
            0 if _norm_text(item.get('alias')) else 1,
            '' if not item.get('updated_at') else str(item.get('updated_at')),
        ),
    )
    # Keep newest updated_at among non-active slots when no alias breaks the tie
    active_items = [item for item in accounts if item.get('slot_id') == active_slot_id]
    other_items = [item for item in accounts if item.get('slot_id') != active_slot_id]
    other_items.sort(
        key=lambda item: (
            1 if _norm_text(item.get('alias')) else 0,
            str(item.get('updated_at') or ''),
        ),
        reverse=True,
    )
    ordered = active_items + other_items

    for candidate in ordered:
        keeper = next((existing for existing in deduped if _same_account_identity(existing, candidate)), None)
        if keeper is None:
            deduped.append(candidate)
        else:
            changed = True
            _merge_slot_metadata(keeper, candidate)
            if candidate.get('slot_id') == active_slot_id:
                active_slot_id = keeper['slot_id']
            # Ensure keeper has primary files if only candidate had them on disk
            keeper_id = keeper['slot_id']
            cand_id = candidate['slot_id']
            if not _slot_has_primary_files(source, primary_files, keeper_id) and _slot_has_primary_files(source, primary_files, cand_id):
                src_dir = pool_dir(source, primary_files) / cand_id
                dst_dir = pool_dir(source, primary_files) / keeper_id
                try:
                    shutil.rmtree(dst_dir, ignore_errors=True)
                    shutil.copytree(src_dir, dst_dir)
                except OSError:
                    pass
            removed_ids.append(cand_id)

    for rid in removed_ids:
        shutil.rmtree(pool_dir(source, primary_files) / rid, ignore_errors=True)

    # Restore stable visual ordering: original order of kept slot_ids
    kept_set = {item['slot_id'] for item in deduped}
    by_id = {item['slot_id']: item for item in deduped}
    stable = [by_id[item['slot_id']] for item in accounts if item['slot_id'] in kept_set]
    return stable, active_slot_id, changed


def _find_matching_slot(
    accounts: list[dict[str, Any]],
    *,
    fingerprint: str,
    explicit_label: str,
    cred_account: str,
    organization: str,
) -> dict[str, Any] | None:
    if fingerprint:
        by_fp = next((item for item in accounts if item.get('session_version') == fingerprint), None)
        if by_fp is not None:
            return by_fp

    probe_stub = {
        'session_version': fingerprint,
        'account_label': explicit_label,
        'credential_account': cred_account,
        'organization': organization,
    }
    for item in accounts:
        if _same_account_identity(item, probe_stub):
            return item
    return None


def _new_slot(
    *,
    account_label: str,
    credential_account: str,
    organization: str,
    state: str,
    fingerprint: str,
    credential_saved: bool,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        'slot_id': 'acct_' + secrets.token_hex(4),
        'account_label': account_label,
        'credential_account': credential_account,
        'alias': '',
        'organization': organization,
        'account_type': '',
        'region_text': '',
        'state': state,
        'session_version': fingerprint,
        'credential_saved': credential_saved,
        'created_at': now,
        'updated_at': now,
    }


def sync_pool_with_status(
    source: str,
    primary_files: list[Path],
    status_dict: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Synchronize current on-disk session with the multi-account pool and return
    (accounts_view, active_slot_id, pending_new_slot).
    """
    with _pool_lock(source, primary_files):
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
        fingerprint = _norm_text(status_dict.get('session_version'))
        explicit_label = _norm_text(status_dict.get('account_label'))
        cred_account = _norm_text(status_dict.get('credential_account'))
        organization = _norm_text(status_dict.get('organization'))
        state = str(status_dict.get('state') or ('saved' if saved_on_disk else 'signed_out'))
        credential_saved = bool(status_dict.get('credential_saved'))

        changed = False

        if saved_on_disk and not busy:
            target_slot: dict[str, Any] | None = None

            if pending_new_slot:
                # Match existing slot first so re-logging into an already-present account
                # updates it in place rather than duplicating it.
                target_slot = _find_matching_slot(
                    accounts,
                    fingerprint=fingerprint,
                    explicit_label=explicit_label,
                    cred_account=cred_account,
                    organization=organization,
                )
                if target_slot is None:
                    target_slot = _new_slot(
                        account_label=explicit_label or cred_account,
                        credential_account=cred_account,
                        organization=organization,
                        state=state,
                        fingerprint=fingerprint,
                        credential_saved=credential_saved,
                    )
                    accounts.append(target_slot)
                active_slot_id = target_slot['slot_id']
                pending_new_slot = False
                changed = True
            else:
                if active_slot_id:
                    target_slot = next((item for item in accounts if item.get('slot_id') == active_slot_id), None)

                # IMPORTANT: Never auto-spawn a duplicate slot during a routine status poll
                # when `active_slot_id` already exists! Identity enrichment or masked
                # `credential_account` updates belong on the active slot in place.
                if target_slot is None:
                    target_slot = _find_matching_slot(
                        accounts,
                        fingerprint=fingerprint,
                        explicit_label=explicit_label,
                        cred_account=cred_account,
                        organization=organization,
                    )
                    if target_slot is None:
                        target_slot = _new_slot(
                            account_label=explicit_label or cred_account,
                            credential_account=cred_account,
                            organization=organization,
                            state=state,
                            fingerprint=fingerprint,
                            credential_saved=credential_saved,
                        )
                        accounts.append(target_slot)
                    active_slot_id = target_slot['slot_id']
                    changed = True

            # Sync metadata and file snapshot into target_slot without downgrading a rich
            # display label (e.g. "姚奕韩") to a raw masked credential account (e.g. "138****1234").
            need_file_copy = (
                target_slot.get('session_version') != fingerprint
                or not _slot_has_primary_files(source, primary_files, target_slot['slot_id'])
            )
            current_label = _norm_text(target_slot.get('account_label'))
            if explicit_label and current_label != explicit_label:
                if not (_is_masked_or_phone(explicit_label) and current_label and not _is_masked_or_phone(current_label)):
                    target_slot['account_label'] = explicit_label
                    changed = True
            elif not current_label and cred_account:
                target_slot['account_label'] = cred_account
                changed = True

            if cred_account and _norm_text(target_slot.get('credential_account')) != cred_account:
                target_slot['credential_account'] = cred_account
                changed = True
            if organization and _norm_text(target_slot.get('organization')) != organization:
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

        # Filter out broken slots whose snapshot files no longer exist (unless currently active on disk)
        valid_accounts: list[dict[str, Any]] = []
        for item in accounts:
            sid = item['slot_id']
            if (sid == active_slot_id and saved_on_disk) or _slot_has_primary_files(source, primary_files, sid):
                valid_accounts.append(item)
            else:
                changed = True

        # Automatically deduplicate any duplicate slots (including historical duplicates on disk)
        valid_accounts, active_slot_id, dedup_changed = _deduplicate_accounts(
            source, primary_files, valid_accounts, active_slot_id
        )
        if dedup_changed:
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
            label = _norm_text(item.get('account_label'))
            cred_fallback = _norm_text(item.get('credential_account'))
            alias = _norm_text(item.get('alias'))
            view_accounts.append({
                'slot_id': sid,
                'account_label': label or cred_fallback or alias or f'已登录账户 #{idx}',
                'alias': alias,
                'organization': _norm_text(item.get('organization')),
                'account_type': _norm_text(item.get('account_type')),
                'region_text': _norm_text(item.get('region_text')),
                'state': str(item.get('state') or 'saved'),
                'is_active': is_active,
                'credential_saved': bool(item.get('credential_saved')),
                'session_version': _norm_text(item.get('session_version')),
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
    expected_session_version: str = '',
) -> None:
    with _pool_lock(source, primary_files):
        manifest = load_manifest(source, primary_files)
        if manifest.get('pending_new_slot'):
            return
        active_slot_id = manifest.get('active_slot_id')
        if not active_slot_id:
            return
        slot = next((item for item in manifest['accounts'] if item.get('slot_id') == active_slot_id), None)
        if slot is None:
            return
        # Guard against stale in-flight HTTP identity calls overwriting a newly switched slot
        if expected_session_version and slot.get('session_version') and slot.get('session_version') != expected_session_version:
            return
        changed = False
        clean_label = _norm_text(account_label)
        clean_org = _norm_text(organization)
        clean_type = _norm_text(account_type)
        clean_region = _norm_text(region_text)
        if clean_label and _norm_text(slot.get('account_label')) != clean_label:
            slot['account_label'] = clean_label
            changed = True
        if clean_org and _norm_text(slot.get('organization')) != clean_org:
            slot['organization'] = clean_org
            changed = True
        if clean_type and clean_type != 'unknown' and _norm_text(slot.get('account_type')) != clean_type:
            slot['account_type'] = clean_type
            changed = True
        if clean_region and _norm_text(slot.get('region_text')) != clean_region:
            slot['region_text'] = clean_region
            changed = True

        # Deduplicate immediately in case this enriched identity matches an existing standby slot
        deduped, new_active_id, dedup_changed = _deduplicate_accounts(
            source, primary_files, manifest['accounts'], active_slot_id
        )
        if dedup_changed:
            manifest['accounts'] = deduped
            manifest['active_slot_id'] = new_active_id
            changed = True

        if changed:
            active_after = next((item for item in manifest['accounts'] if item.get('slot_id') == manifest.get('active_slot_id')), None)
            if active_after is not None:
                active_after['updated_at'] = _now_iso()
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
    with _pool_lock(source, primary_files):
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
    with _pool_lock(source, primary_files):
        if current_status.get('saved'):
            sync_pool_with_status(source, primary_files, current_status)
        manifest = load_manifest(source, primary_files)
        current_active = manifest.get('active_slot_id')

        slot = next((item for item in manifest['accounts'] if item.get('slot_id') == slot_id), None)
        if slot is None:
            raise HTTPException(404, '所选平台账户不存在或已移除')

        # Idempotent fast path: only skip restoring files when caller confirms the
        # on-disk bytes already match this exact slot's session_version.
        current_fp = _norm_text(current_status.get('session_version'))
        slot_fp = _norm_text(slot.get('session_version'))
        if (
            current_active == slot_id
            and not manifest.get('pending_new_slot')
            and current_status.get('saved')
            and current_fp
            and slot_fp
            and current_fp == slot_fp
            and any(p.exists() for p in primary_files)
        ):
            if not _slot_has_primary_files(source, primary_files, slot_id):
                _copy_active_to_slot(source, primary_files, slot_id)
            slot['updated_at'] = _now_iso()
            save_manifest(source, primary_files, manifest)
            return dict(slot)

        if current_active and current_active != slot_id and not manifest.get('pending_new_slot') and any(p.exists() for p in primary_files):
            _copy_active_to_slot(source, primary_files, current_active)

        sdir = pool_dir(source, primary_files) / slot_id
        if not _slot_has_primary_files(source, primary_files, slot_id):
            raise HTTPException(409, '该账户本地会话已失效，请重新登录')

        for dst in _managed_files(source, primary_files):
            src = sdir / dst.name
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(dst.suffix + '.switch.part')
                tmp.write_bytes(src.read_bytes())
                tmp.replace(dst)
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
    with _pool_lock(source, primary_files):
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
    with _pool_lock(source, primary_files):
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
    with _pool_lock(source, primary_files):
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

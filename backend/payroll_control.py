"""Cooperative payroll stops. Inputs and results are retained at every checkpoint."""
import threading
import time
import uuid
from parttime_source import SourceError

LOCK = threading.RLock()
EXECUTION_LOCK = threading.Lock()
RUNNING = {}
RUNTIME_ID = uuid.uuid4().hex


def reconcile(folder, state):
    """A worker cannot survive its server process. Retain its frozen evidence."""
    from payroll_inputs import save
    if state['status'] == 'preparing' and state.get('execution_runtime') != RUNTIME_ID:
        from download_jobs import get_manager, ACTIVE_STATUSES
        from payroll_inputs import collect_finished
        manager = get_manager()
        runs = [manager.get_run(state['download_owner'], key) for key in state.get('jobs', [])]
        if runs and all(run['status'] not in ACTIVE_STATUSES for run in runs):
            collect_finished(folder, state, manager)
        elif not runs:
            state['status'] = 'pending_download' if state.get('workflow') == 'two_step_v1' else 'awaiting_confirmation'
            save(folder, state)
    if state['status'] == 'stopping' and state.get('execution_runtime') != RUNTIME_ID:
        stop(folder.parent.name, state['id'], state.get('download_owner'))
        from payroll_inputs import load
        state.update(load(folder.parent.name, state['id'], state.get('download_owner'))[1])
    if state['status'] == 'calculating' and state.get('execution_runtime') != RUNTIME_ID:
        state.update(status='interrupted', pause_reason='服务中断，原资料和文件已保留；请核对原结果后重新上传申请表发起新批次')
        save(folder, state)
    return state


class PayrollStopped(BaseException):
    pass


def acquire(folder):
    key = str(folder.resolve())
    with LOCK:
        if key in RUNNING:
            raise SourceError('本批次仍在执行或停止中，请等待状态更新')
        event = threading.Event()
        RUNNING[key] = event
        return event


def release(folder, event):
    with LOCK:
        if RUNNING.get(str(folder.resolve())) is event:
            del RUNNING[str(folder.resolve())]


def checkpoint(event):
    if event is not None and event.is_set():
        raise PayrollStopped()


def stop(wid, key, owner):
    from payroll_inputs import load, save, batch_lock, directory, public
    folder = directory(wid, key)
    with batch_lock(folder), LOCK:
        folder, state = load(wid, key, owner)
        if state['status'] in ('calculated', 'cancelled'):
            return public(state)
        event = RUNNING.get(str(folder.resolve()))
        if event:
            event.set()
        state['stop_requested'] = True
        state['execution_runtime'] = RUNTIME_ID
        state['status'] = 'stopping'
        save(folder, state)
    from download_jobs import get_manager, ACTIVE_STATUSES
    manager = get_manager()
    for job in state.get('jobs', []):
        run = manager.get_run(state['download_owner'], job)
        if run['status'] in ACTIVE_STATUSES:
            manager.cancel(state['download_owner'], job)
    if not event:
        def acknowledge():
            while any(manager.get_run(state['download_owner'], job)['status'] in ACTIVE_STATUSES for job in state.get('jobs', [])):
                time.sleep(0.5)
            with batch_lock(folder):
                current_folder, current = load(wid, key, owner)
                if current['status'] == 'stopping':
                    current['status'] = 'cancelled'
                    save(current_folder, current)
        if all(manager.get_run(state['download_owner'], job)['status'] not in ACTIVE_STATUSES for job in state.get('jobs', [])):
            acknowledge()
            folder, state = load(wid, key, owner)
        else:
            threading.Thread(target=acknowledge, daemon=True, name='payroll-stop-'+key[:8]).start()
    return public(state)

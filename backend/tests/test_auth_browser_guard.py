import contextlib
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import auth_browser_guard as guard_module
from auth_browser_guard import BrowserGuard
import binding_source_auth as source
import platform_auth_control as control
from fastapi import HTTPException


class BrowserGuardTests(unittest.TestCase):
    def instance(self):
        values=[]
        guard=BrowserGuard(SimpleNamespace(),threading.Event(),values.append,timeout=.01)
        self.addCleanup(guard.finish)
        return guard,values

    def test_normal_finish_does_not_terminate_any_process(self):
        guard,values=self.instance()
        with patch.object(guard,'terminate_owned') as terminate:
            guard.closing();guard.finish();guard.thread.join(1)
        terminate.assert_not_called()
        self.assertEqual(values[-1]['release_state'],'released')

    def test_cancel_timeout_releases_only_owned_attempt(self):
        guard,values=self.instance()
        with patch.object(guard,'terminate_owned',return_value=True) as terminate:
            guard.cancelled.set();guard.thread.join(2)
        terminate.assert_called_once()
        self.assertEqual(values[-1]['release_state'],'terminated')
        self.assertTrue(guard.timed_out)

    def test_unverified_ownership_never_terminates_process(self):
        guard,values=self.instance()
        with patch.object(guard_module.psutil,'Process') as process:
            guard.closing();guard.thread.join(2)
        process.assert_not_called()
        self.assertEqual(values[-1]['release_state'],'unconfirmed')

    def test_pid_reuse_is_rejected(self):
        guard,_=self.instance();guard.owner=(123,1)
        process=Mock();process.create_time.return_value=2
        with patch.object(guard_module.psutil,'Process',return_value=process):
            self.assertFalse(guard.terminate_owned())
        process.children.assert_not_called();process.terminate.assert_not_called()

    def test_only_captured_child_tree_is_terminated_and_reused_child_is_skipped(self):
        guard,_=self.instance();guard.owner=(123,1)
        driver=Mock();driver.pid=123;driver.create_time.return_value=1
        child=Mock();child.pid=124;child.create_time.side_effect=[1,2]
        driver.children.return_value=[child]
        with patch.object(guard_module.psutil,'Process',return_value=driver),patch.object(guard,'_is_driver',return_value=True),patch.object(guard_module.psutil,'wait_procs',return_value=([],[])):
            self.assertTrue(guard.terminate_owned())
        driver.children.assert_called_once_with(recursive=True)
        driver.terminate.assert_called_once();child.terminate.assert_not_called()

    def test_changed_driver_command_prevents_termination(self):
        guard,_=self.instance();guard.owner=(123,1)
        process=Mock();process.create_time.return_value=1
        with patch.object(guard_module.psutil,'Process',return_value=process),patch.object(guard,'_is_driver',return_value=False):
            self.assertFalse(guard.terminate_owned())
        process.children.assert_not_called()

    def test_finished_state_does_not_allow_new_auth_while_worker_is_alive(self):
        auth=source.SourceAuth();auth.states['baize']={'state':'saved'}
        auth.workers['baize']=SimpleNamespace(is_alive=lambda:True)
        with tempfile.TemporaryDirectory() as directory,patch.object(source,'ROOT',Path(directory)),patch('threading.Thread') as thread:
            state=auth.start('baize')
        thread.assert_not_called();self.assertTrue(state['busy'])

    def test_disconnect_blocked_until_worker_released_even_if_state_is_ready(self):
        auth=source.SourceAuth();auth.states['baize']={'state':'ready'}
        auth.workers['baize']=SimpleNamespace(is_alive=lambda:True)
        with tempfile.TemporaryDirectory() as directory,patch.object(source,'ROOT',Path(directory)),patch.object(source,'AUTH',auth),patch.object(control,'idle_guard',contextlib.nullcontext):
            with self.assertRaises(HTTPException) as caught:control.disconnect('baize',control.version('baize'))
        self.assertEqual(caught.exception.status_code,409)

    def test_wind_cancel_keeps_busy_until_operation_released(self):
        from fengshen_auth import AuthBroker, SessionVault
        with tempfile.TemporaryDirectory() as directory:
            broker=AuthBroker(SessionVault(Path(directory)/'synthetic.dpapi'))
            event=threading.Event()
            with broker.operation('synthetic',event):
                broker.update('login_required','synthetic')
                broker.submit('synthetic',broker.status('synthetic')['challenge_id'],'cancel')
                broker.release_update({'release_state':'timeout','release_message':'synthetic'})
                status=broker.status('synthetic')
                self.assertTrue(status['busy']);self.assertTrue(status['cancelling'])
                self.assertEqual(status['release_state'],'timeout')
            self.assertFalse(broker.status('synthetic')['busy'])


if __name__=='__main__':unittest.main()

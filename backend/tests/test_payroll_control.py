import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import payroll_control as control
import payroll_inputs as inputs
import tasks


class PayrollControlTests(unittest.TestCase):
    def test_dead_server_calculation_is_interrupted_and_preserves_frozen_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);evidence=folder/'evidence.txt';evidence.write_text('kept')
            state={'status':'calculating','execution_runtime':'old-process','deductions':{'version':'fixed','frozen':True}}
            control.reconcile(folder,state)
            self.assertEqual(state['status'],'interrupted');self.assertTrue(state['deductions']['frozen'])
            self.assertEqual(evidence.read_text(),'kept')

    def test_duplicate_execution_rejected_until_acknowledged(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            event=control.acquire(folder)
            try:
                event.set()
                with self.assertRaisesRegex(inputs.SourceError,'停止中'):control.acquire(folder)
            finally:control.release(folder,event)
            second=control.acquire(folder);control.release(folder,second)

    def test_worker_finishes_before_stop_ack_and_never_emits_success(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'template.xlsx').write_bytes(b'synthetic')
            cancelled=threading.Event();entered=threading.Event();release=threading.Event();exited=threading.Event()
            def engine(*args,**kwargs):
                entered.set()
                try:
                    if not release.wait(5):raise RuntimeError('test worker timeout')
                    args[5](.5,'checkpoint')
                    args[6]('success',str(folder))
                finally:exited.set()
            events=[]
            async def collect():
                async for event in tasks.run_main_calculation_gen('测试城','半月结',str(folder),'',{},taskQueue=['template.xlsx'],prepared_plan={'city':'测试城','template':'template.xlsx'},cancelled=cancelled):events.append(event)
            async def scenario():
                task=asyncio.create_task(collect())
                self.assertTrue(await asyncio.to_thread(entered.wait,5))
                cancelled.set();await asyncio.sleep(.05)
                self.assertFalse(task.done(),'cannot report stopped while the worker is still writing')
                release.set()
                with self.assertRaises(control.PayrollStopped):await asyncio.wait_for(task,5)
                self.assertTrue(exited.is_set())
            with patch('processor.process_rider_data',engine):asyncio.run(scenario())
            self.assertFalse(any('"status": "success"' in event for event in events))

    def test_stop_preserves_inputs_and_waits_for_child_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);key='a'*32;folder=inputs.directory('shared',key,root);folder.mkdir(parents=True)
            evidence=folder/'original.xlsx';evidence.write_bytes(b'keep me')
            state={'id':key,'mode':'fengshen','status':'preparing','download_owner':'owner','plan':{},'items':{},'jobs':['child']}
            inputs.save(folder,state)
            event=control.acquire(folder);manager=SimpleNamespace(get_run=lambda *_:{'status':'running'},cancel=lambda *_:None)
            try:
                with patch.object(inputs,'ROOT',root),patch('download_jobs.get_manager',return_value=manager):
                    result=control.stop('shared',key,'owner')
                self.assertEqual(result['status'],'stopping');self.assertTrue(event.is_set())
                self.assertEqual(evidence.read_bytes(),b'keep me')
                self.assertEqual(inputs.load('shared',key,'owner',root)[1]['status'],'stopping')
            finally:control.release(folder,event)


if __name__=='__main__':unittest.main()

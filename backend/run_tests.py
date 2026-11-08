"""Offline regression entrypoint. No private profiles or official login needed."""
import argparse
from contextlib import contextmanager
import ipaddress
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent


def local_host(host):
    if host is None or host in ('localhost','localhost.',b'localhost'):
        return True
    try:
        if isinstance(host,bytes):host=host.decode('ascii')
        return ipaddress.ip_address(host).is_loopback
    except (ValueError,UnicodeError):
        return False


@contextmanager
def offline_network(denied):
    original_connect=socket.socket.connect
    original_connect_ex=socket.socket.connect_ex
    original_lookup=socket.getaddrinfo
    def guard(address):
        if isinstance(address,tuple) and not local_host(address[0]):
            denied.append(str(address[0]))
            raise RuntimeError('Offline tests cannot access external network; mock the platform explicitly')
    def connect(sock,address):
        guard(address);return original_connect(sock,address)
    def connect_ex(sock,address):
        guard(address);return original_connect_ex(sock,address)
    def lookup(host,*args,**kwargs):
        if not local_host(host):
            denied.append(str(host))
            raise RuntimeError('Offline tests cannot resolve external hosts')
        return original_lookup(host,*args,**kwargs)
    with patch.object(socket.socket,'connect',connect),patch.object(socket.socket,'connect_ex',connect_ex),patch.object(socket,'getaddrinfo',lookup):
        yield


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--pattern',default='test*.py')
    parser.add_argument('--verbose',action='store_true')
    args=parser.parse_args()
    sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
    denied=[]
    with offline_network(denied):
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=args.pattern)
        if suite.countTestCases()==0:raise RuntimeError('No tests discovered')
        result=unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    report={'mode':'offline','tests':result.testsRun,'failures':[str(t) for t,_ in result.failures],
            'errors':[str(t) for t,_ in result.errors],'skipped':[{'test':str(t),'reason':why} for t,why in result.skipped],
            'external_network_attempts':sorted(set(denied)),
            'passed':result.wasSuccessful() and not denied,
            'live_acceptance':{'status':'not_run','reason':'Separate official-platform evidence and operator scope required; offline success is not live acceptance'}}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0 if report['passed'] else 1


if __name__=='__main__':sys.exit(main())

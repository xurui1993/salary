"""Read-only live prerequisite check; never opens a browser or submits exports."""
import argparse
import json
from pathlib import Path
import sys


def inspect(root):
    from fengshen_bill import validate_profile
    from fengshen_orders import validate_order_profile
    checks=[]
    for name,validator in [('fengshen_bill.profile.json',validate_profile),
                           ('fengshen_rider_bill.profile.json',validate_profile),
                           ('fengshen_orders.profile.json',validate_order_profile)]:
        p=Path(root)/name
        if not p.is_file():checks.append({'configuration':name,'status':'missing'});continue
        try:
            profile=json.loads(p.read_text('utf-8'))
            if profile.get('test_only'):raise ValueError('test fixture is not a live profile')
            validator(profile)
            checks.append({'configuration':name,'status':'verified_configuration_present'})
        except Exception:
            checks.append({'configuration':name,'status':'invalid_or_unverified'})
    ready=all(c['status']=='verified_configuration_present' for c in checks)
    return {'mode':'live_prerequisite_check','status':'prerequisites_present' if ready else 'blocked',
            'checks':checks,'login_checked':False,'exports_submitted':0,'live_tests_run':0,
            'acceptance':'not_run','note':'Configuration presence does not verify login, scope, platform behavior, or business outputs.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path);args=parser.parse_args()
    result=inspect(Path(__file__).resolve().parent)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0 if result['status']=='prerequisites_present' else 2)

"""Verified official current-merchant download contracts (no network at import)."""
INVITATIONS='invitation_records'
ATTENDANCE='attendance_detail'
KINDS=frozenset({INVITATIONS,ATTENDANCE})
MERCHANT='当前商家'
LABELS={INVITATIONS:'邀请记录（全量）',ATTENDANCE:'骑手出勤明细'}
INVITE_AUTH='https://zapdos.ele.me/api/pizza/whoami/aeolus'
INVITE_ROOT='https://zapdos.ele.me/api/pizza/lpd_prism.crowd_activityprod/manage/fs/invite/'
INVITE_TEAMS=INVITE_ROOT+'queryTeams'
INVITE_QUERY=INVITE_ROOT+'queryInviteInstance'
GRAY_URL='https://httpizza.ele.me/xtop/xtop.fs.special.schedule.grayList/1.0'
ATTENDANCE_EXPORT='https://httpizza.ele.me/xtop/xtop.fs.special.examine.exportStatisticsDetail/1.0'

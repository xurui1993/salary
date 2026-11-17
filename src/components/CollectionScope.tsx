import React from 'react';

export function CollectionScope({ platform }: { platform?: string }) {
  const archive = platform === 'xiaoxiang';
  const payout = platform === 'payout';
  const baize = platform === 'baize';
  const benlai = platform === 'benlai';
  return <div className="wb-collection-scope" aria-label="采集范围">
    <strong>{archive ? '灯塔骑手档案' : payout ? '发薪平台资料' : baize ? '商翼员工资料' : benlai ? '本来人力灵工资料' : '蓝橙资料'}</strong>
    <span>{payout ? '全站全城 · 按所选平台独立原表' : baize ? '全部可导出员工 · 一份原表' : benlai ? '全部可导出灵工 · 一份原表' : archive ? '当前可导出档案' : '全部授权城市 · 每类一份原表'}</span>
    <details><summary>范围说明</summary><p>按当前账号权限获取平台可导出的资料，不按业务日期筛选。数据范围及更新时间以平台返回结果为准。</p></details>
  </div>;
}

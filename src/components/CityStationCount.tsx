import React from 'react';
import {stationCountText,type StationDirectory} from '../lib/useStationDirectory';
export function CityStationCount({directory,city}:{directory:StationDirectory|null;city:string}){
  const text = stationCountText(directory,city);
  if (!text || text === '待同步') return null;
  return <small className="wb-city-station-count" title="当前账号后台可见站点数量，按站点编号去重">{text}</small>;
}

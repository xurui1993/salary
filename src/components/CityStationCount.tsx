import React from 'react';
import {stationCountText,type StationDirectory} from '../lib/useStationDirectory';
export function CityStationCount({directory,city}:{directory:StationDirectory|null;city:string}){
  return <small className="wb-city-station-count" title="当前账号后台可见站点数量，按站点编号去重">{stationCountText(directory,city)}</small>;
}

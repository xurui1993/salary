export interface StationFilterInput {
  id: string;
  name: string;
  city?: string;
  [key: string]: unknown;
}

export type StationFilterChoice<T extends StationFilterInput = StationFilterInput> = T & {
  ambiguous: boolean;
  label: string;
};

export function stationFilterChoices<T extends StationFilterInput>(
  stations: T[],
  city?: string,
): StationFilterChoice<T>[] {
  const rows = stations.filter(station => !city || station.city === city);
  return rows.map(station => ({
    ...station,
    ambiguous: rows.filter(other => other.name === station.name).length > 1,
    label: `${station.name} · ${station.city} · 编号 ${station.id}`,
  }));
}

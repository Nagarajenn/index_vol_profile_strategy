import { apiClient } from "../client";
import type { VolumeIntelligenceDTO } from "../../types/volumeIntelligence";

export async function fetchVolumeIntelligence(symbol: string): Promise<VolumeIntelligenceDTO> {
  const { data } = await apiClient.get<VolumeIntelligenceDTO>(`/volume-intelligence/${symbol}`);
  return data;
}

import { apiClient } from "../client";
import type { VolumeProfileIntelligenceDTO } from "../../types/volumeProfile";

export async function fetchVolumeProfileIntelligence(symbol: string): Promise<VolumeProfileIntelligenceDTO> {
  const { data } = await apiClient.get<VolumeProfileIntelligenceDTO>(`/volume-profile/${symbol}/intelligence`);
  return data;
}

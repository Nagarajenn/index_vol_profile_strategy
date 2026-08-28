import { apiClient } from "../client";
import type {
  CasCohortAnalysisResponseDTO,
  CasIntelligenceResponseDTO,
  CasWindowedDetailResponseDTO,
  MtiResearchResponseDTO,
} from "../../types/marketTransition";

export async function fetchMarketTransitionResearch(symbol: string): Promise<MtiResearchResponseDTO> {
  const { data } = await apiClient.get<MtiResearchResponseDTO>(`/market-transition/${symbol}/research`);
  return data;
}

export async function fetchCasIntelligence(symbol: string): Promise<CasIntelligenceResponseDTO> {
  const { data } = await apiClient.get<CasIntelligenceResponseDTO>(`/market-transition/${symbol}/cas-intelligence`);
  return data;
}

export async function fetchCasWindowedDetail(symbol: string, sessionDate: string): Promise<CasWindowedDetailResponseDTO> {
  const { data } = await apiClient.get<CasWindowedDetailResponseDTO>(
    `/market-transition/${symbol}/cas-intelligence/${sessionDate}/windowed-detail`
  );
  return data;
}

export async function fetchCasCohortAnalysis(symbol: string): Promise<CasCohortAnalysisResponseDTO> {
  const { data } = await apiClient.get<CasCohortAnalysisResponseDTO>(`/market-transition/${symbol}/cas-cohort-analysis`);
  return data;
}

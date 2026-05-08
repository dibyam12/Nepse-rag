/**
 * TanStack Query hooks for NEPSE API data fetching.
 */
import { useQuery } from '@tanstack/react-query';
import api from '../api/client';

/**
 * Fetch all active stock symbols.
 * Cached for 24 hours (matches backend cache TTL).
 */
export function useSymbols() {
  return useQuery({
    queryKey: ['symbols'],
    queryFn: () => api.get('/symbols/').then((res) => res.data),
    staleTime: 24 * 60 * 60 * 1000,   // 24 hours
    gcTime: 24 * 60 * 60 * 1000,
  });
}

/**
 * Fetch stock detail (OHLCV + indicators) for a symbol.
 * Cached for 15 minutes (matches backend indicator cache TTL).
 */
export function useStockDetail(symbol) {
  return useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => api.get(`/stock/${symbol}/`).then((res) => res.data),
    enabled: !!symbol,
    staleTime: 15 * 60 * 1000,   // 15 minutes
    gcTime: 30 * 60 * 1000,
  });
}

/**
 * Fetch all sectors with stock lists.
 * Cached for 24 hours.
 */
export function useSectors() {
  return useQuery({
    queryKey: ['sectors'],
    queryFn: () => api.get('/sectors/').then((res) => res.data),
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });
}

/**
 * Fetch system health check.
 * Refreshes every 30 seconds.
 */
export function useHealthCheck() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.get('/health/').then((res) => res.data),
    staleTime: 30 * 1000,
    refetchInterval: 30 * 1000,
  });
}

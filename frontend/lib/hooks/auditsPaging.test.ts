/**
 * The audit list is paged.
 *
 * It used to take the server default of 50 with no way to ask for more, so an
 * agency past its first fifty audits had older runs no screen could reach - and
 * the filters and search operated on that window silently, so "failed" could
 * render as "no failures".
 *
 * The behaviour worth pinning is the stop condition: a short page is the last
 * page, and asking for the next one would be a wasted round trip on EVERY poll
 * while a job is in flight.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

import { AUDITS_PAGE, useAudits } from "@/lib/hooks/audits";

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return React.createElement(QueryClientProvider, { client }, children);
}

const page = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ id: `a-${i}`, status: "done" }));

describe("useAudits paging", () => {
  beforeEach(() => get.mockReset());

  it("asks for the server maximum rather than the default 50", async () => {
    get.mockResolvedValueOnce(page(3));
    const { result } = renderHook(() => useAudits(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledWith(`/audits?limit=${AUDITS_PAGE}&offset=0`);
  });

  it("stops on a short page instead of fetching an empty one", async () => {
    get.mockResolvedValueOnce(page(3));
    const { result } = renderHook(() => useAudits(4), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("keeps going while every page comes back full", async () => {
    get
      .mockResolvedValueOnce(page(AUDITS_PAGE))
      .mockResolvedValueOnce(page(AUDITS_PAGE))
      .mockResolvedValueOnce(page(7));
    const { result } = renderHook(() => useAudits(5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(3);
    expect(result.current.data).toHaveLength(AUDITS_PAGE * 2 + 7);
  });

  it("offsets each page by the page size", async () => {
    get.mockResolvedValueOnce(page(AUDITS_PAGE)).mockResolvedValueOnce(page(1));
    const { result } = renderHook(() => useAudits(2), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenNthCalledWith(2, `/audits?limit=${AUDITS_PAGE}&offset=${AUDITS_PAGE}`);
  });

  it("treats a request for zero or fewer pages as one page", async () => {
    get.mockResolvedValueOnce(page(2));
    const { result } = renderHook(() => useAudits(0), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(get).toHaveBeenCalledTimes(1);
  });
});

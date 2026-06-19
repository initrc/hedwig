"use client";

import { useMemo, useState, type ReactNode } from "react";
import useSWR from "swr";
import { LoaderCircle, RefreshCw, Search } from "lucide-react";

import { DigestCard } from "@/components/digest-card";
import { DigestDetailSheet } from "@/components/digest-detail-sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetcher, type Digest, type DigestTopic } from "@/lib/api";

export function DigestCardList() {
  const { data, error, isLoading, mutate } = useSWR<Digest[]>(
    "/digests",
    fetcher,
  );

  const [filter, setFilter] = useState("");
  const [selectedTopic, setSelectedTopic] = useState<DigestTopic | null>(null);

  const filteredDigests = useMemo(() => {
    const digests = data ?? [];
    const query = filter.trim().toLowerCase();
    if (!query) return digests;
    return digests
      .map((digest) => ({
        ...digest,
        topics: digest.topics.filter((topic) =>
          topic.label.toLowerCase().includes(query),
        ),
      }))
      .filter((digest) => digest.topics.length > 0);
  }, [data, filter]);

  const visibleTopicCount = filteredDigests.reduce(
    (count, digest) => count + digest.topics.length,
    0,
  );
  const hasDigests = (data?.length ?? 0) > 0;
  const hasFilter = filter.trim().length > 0;

  return (
    <section className="w-full max-w-6xl space-y-4">
      <header className="space-y-1.5">
        <h1 className="font-heading text-lg font-medium">Digest history</h1>
        <p className="text-xs text-muted-foreground">
          Every saved digest, grouped by day. Click a card to open the details.
        </p>
      </header>

      <FilterBar
        filter={filter}
        onFilterChange={setFilter}
        onRefresh={() => mutate()}
        isRefreshing={isLoading}
      />

      <ListState
        isLoading={isLoading}
        error={error}
        hasDigests={hasDigests}
        visibleTopicCount={visibleTopicCount}
        hasFilter={hasFilter}
      >
        <div className="space-y-8">
          {filteredDigests.map((digest) => (
            <section key={digest.date} className="space-y-3">
              <h2 className="font-heading text-base font-medium">
                {digest.date}
              </h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {digest.topics.map((topic) => (
                  <DigestCard
                    key={`${digest.date}-${topic.label}`}
                    topic={topic}
                    onSelect={setSelectedTopic}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      </ListState>

      <DigestDetailSheet
        topic={selectedTopic}
        onOpenChange={(open) => {
          if (!open) setSelectedTopic(null);
        }}
      />
    </section>
  );
}

function FilterBar({
  filter,
  onFilterChange,
  onRefresh,
  isRefreshing,
}: {
  filter: string;
  onFilterChange: (value: string) => void;
  onRefresh: () => void;
  isRefreshing: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          value={filter}
          onChange={(event) => onFilterChange(event.target.value)}
          placeholder="Filter by topic label..."
          className="pl-7"
          aria-label="Filter topics by label"
        />
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={onRefresh}
        disabled={isRefreshing}
      >
        <RefreshCw className={isRefreshing ? "animate-spin" : undefined} />
        Refresh
      </Button>
    </div>
  );
}

function ListState({
  isLoading,
  error,
  hasDigests,
  visibleTopicCount,
  hasFilter,
  children,
}: {
  isLoading: boolean;
  error: Error | undefined;
  hasDigests: boolean;
  visibleTopicCount: number;
  hasFilter: boolean;
  children: ReactNode;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" />
        Loading digests...
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-12 text-sm text-destructive">
        Could not load digests. Check that the backend is running and try
        Refresh.
      </div>
    );
  }

  if (!hasDigests) {
    return (
      <div className="py-12 text-sm text-muted-foreground">
        No digests yet. Generate one and click Refresh.
      </div>
    );
  }

  if (visibleTopicCount === 0) {
    return (
      <div className="py-12 text-sm text-muted-foreground">
        {hasFilter
          ? "No topics match this filter."
          : "No topics to display."}
      </div>
    );
  }

  return <>{children}</>;
}

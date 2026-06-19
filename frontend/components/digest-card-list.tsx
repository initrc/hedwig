"use client";

import { useMemo, useState, type ReactNode } from "react";
import useSWR from "swr";
import { LoaderCircle, Search } from "lucide-react";

import { DigestCard } from "@/components/digest-card";
import { DigestDetailSheet } from "@/components/digest-detail-sheet";
import { ThemeToggle } from "@/components/theme-toggle";
import { Input } from "@/components/ui/input";
import { fetcher, type Digest, type DigestTopic, type Status } from "@/lib/api";

export function DigestCardList() {
  const { data, error, isLoading } = useSWR<Digest[]>("/digests", fetcher);

  const {
    data: status,
    error: statusError,
    isLoading: statusLoading,
  } = useSWR<Status>("/status", fetcher, {
    // Re-poll every 30s while a digest is running; stop once idle. The digest
    // runs once a day, so there is no reason to keep polling after it finishes
    // — the next day is a new session.
    refreshInterval: (latest) =>
      latest && latest.state === "running" ? 30_000 : 0,
    // Refocusing the tab must not restart polling once idle.
    revalidateOnFocus: false,
  });

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
        <div className="flex items-center justify-between">
          <h1 className="font-heading text-lg font-medium">Hedwig</h1>
          <ThemeToggle />
        </div>
        <div className="flex items-baseline justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            AI-powered newsletter intelligence
          </p>
          <p className="text-xs text-muted-foreground">
            <StatusText
              status={status}
              isLoading={statusLoading}
              error={statusError}
            />
          </p>
        </div>
      </header>

      <FilterBar filter={filter} onFilterChange={setFilter} />

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

function StatusText({
  status,
  isLoading,
  error,
}: {
  status: Status | undefined;
  isLoading: boolean;
  error: Error | undefined;
}) {
  if (isLoading) return "Checking digest status...";
  if (error || !status) return "Could not reach the backend.";
  if (status.state === "running") {
    return `Generating digest from ${status.email_count} email${
      status.email_count === 1 ? "" : "s"
    }…`;
  }
  if (status.last_digest_at) {
    const when = new Date(status.last_digest_at).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    return `Last digest ${when}`;
  }
  return "No digests yet.";
}

function FilterBar({
  filter,
  onFilterChange,
}: {
  filter: string;
  onFilterChange: (value: string) => void;
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
        Could not load digests. Check that the backend is running and reload the
        page.
      </div>
    );
  }

  if (!hasDigests) {
    return (
      <div className="py-12 text-sm text-muted-foreground">
        No digests yet. The backend will generate one shortly.
      </div>
    );
  }

  if (visibleTopicCount === 0) {
    return (
      <div className="py-12 text-sm text-muted-foreground">
        {hasFilter ? "No topics match this filter." : "No topics to display."}
      </div>
    );
  }

  return <>{children}</>;
}

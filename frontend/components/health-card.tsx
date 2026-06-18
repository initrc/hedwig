"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fetcher, type Health } from "@/lib/api";

export function HealthCard() {
  const { data, error, isLoading } = useSWR<Health>("/health", fetcher);

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Hedwig</CardTitle>
        <CardDescription>A newsletter digest agent</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <StatusBadge isLoading={isLoading} error={error} data={data} />
      </CardContent>
    </Card>
  );
}

function StatusBadge({
  isLoading,
  error,
  data,
}: {
  isLoading: boolean;
  error: Error | undefined;
  data: Health | undefined;
}) {
  const prefix = "Backend service: ";
  if (isLoading)
    return <Badge variant="secondary">{prefix + "checking"}</Badge>;
  if (error)
    return <Badge variant="destructive">{prefix + "unavailable"}</Badge>;
  if (data) return <Badge variant="default">{prefix + "ok"}</Badge>;
  return null;
}

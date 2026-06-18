"use client";

import * as React from "react";
import Image from "next/image";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { DigestTopic } from "@/lib/api";

const SOURCE_BADGE_LIMIT = 3;

export function DigestCard({
  topic,
  onSelect,
  className,
}: {
  topic: DigestTopic;
  onSelect: (topic: DigestTopic) => void;
  className?: string;
}) {
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(topic);
    }
  };

  const visibleSources = topic.sources.slice(0, SOURCE_BADGE_LIMIT);
  const remainingSources = topic.sources.length - visibleSources.length;

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={() => onSelect(topic)}
      onKeyDown={handleKeyDown}
      aria-label={`Open details for ${topic.label}`}
      className={cn(
        "cursor-pointer pt-0! transition-colors hover:ring-foreground/30 focus-visible:ring-2 focus-visible:ring-ring/50",
        className,
      )}
    >
      <TopicImage image={topic.image} label={topic.label} />
      <CardHeader className="pt-(--card-spacing)">
        <CardTitle className="line-clamp-2">{topic.label}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="line-clamp-3 text-muted-foreground">{topic.summary}</p>
        {topic.sources.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {visibleSources.map((source) => (
              <Badge key={source.id} variant="secondary">
                {source.source}
              </Badge>
            ))}
            {remainingSources > 0 && (
              <Badge variant="outline">+{remainingSources}</Badge>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TopicImage({
  image,
  label,
}: {
  image: DigestTopic["image"];
  label: string;
}) {
  if (!image) {
    return (
      <div
        className="aspect-video w-full bg-muted"
        aria-hidden="true"
        data-slot="card-image-placeholder"
      />
    );
  }

  return (
    <div className="relative aspect-video w-full overflow-hidden bg-muted">
      <Image
        src={image.url}
        alt={image.alt || label}
        fill
        sizes="(min-width: 1024px) 33vw, (min-width: 640px) 50vw, 100vw"
        className="object-cover"
      />
    </div>
  );
}

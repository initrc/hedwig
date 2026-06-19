"use client";

import * as React from "react";
import { useEffect, useState } from "react";
import { ExternalLink, LoaderCircle, Send } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { askChat, type AugmentedAnswer, type DigestTopic } from "@/lib/api";

export function DigestDetailSheet({
  topic,
  onOpenChange,
}: {
  topic: DigestTopic | null;
  onOpenChange: (open: boolean) => void;
}) {
  // Keep the last non-null topic around so the panel's content stays visible
  // during the close animation instead of flashing empty. Adjusting state
  // during render (rather than in an effect) avoids a cascading re-render.
  const [displayedTopic, setDisplayedTopic] = useState<DigestTopic | null>(
    topic,
  );
  if (topic && topic !== displayedTopic) {
    setDisplayedTopic(topic);
  }

  return (
    <Sheet open={topic !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{displayedTopic?.label}</SheetTitle>
          <SheetDescription>
            Topic summary, source citations, and scoped chat.
          </SheetDescription>
        </SheetHeader>

        {displayedTopic && (
          <div className="flex flex-1 flex-col overflow-hidden">
            <TopicBody topic={displayedTopic} />
            <TopicChat topicLabel={displayedTopic.label} />
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function TopicBody({ topic }: { topic: DigestTopic }) {
  return (
    <div className="flex-1 overflow-y-auto px-4 pb-4">
      <h2 className="mb-1 text-xs font-medium text-muted-foreground">
        Summary
      </h2>
      <p className="text-foreground">{topic.summary}</p>

      <h2 className="mt-4 mb-2 text-xs font-medium text-muted-foreground">
        Sources
      </h2>
      {topic.sources.length === 0 ? (
        <p className="text-muted-foreground">No sources for this topic.</p>
      ) : (
        <ul className="space-y-2">
          {topic.sources.map((source) => (
            <li key={source.id} className="space-y-1">
              <div className="flex items-center gap-2">
                <Badge variant="secondary">{source.source}</Badge>
                <span className="line-clamp-1 text-foreground">
                  {source.subject}
                </span>
              </div>
              {source.original_url ? (
                <a
                  href={source.original_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-primary underline-offset-4 hover:underline"
                >
                  View original
                  <ExternalLink className="size-3" />
                </a>
              ) : (
                <span className="text-xs text-muted-foreground">
                  Original link unavailable.
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

type ChatMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; answer: AugmentedAnswer };

function TopicChat({ topicLabel }: { topicLabel: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopedTopicLabel, setScopedTopicLabel] = useState(topicLabel);

  // The chat is scoped to the current topic. Reset the conversation whenever
  // the topic changes so stale messages from another topic don't bleed in.
  // Adjusting state during render (rather than in an effect) avoids a
  // cascading re-render and the flash of stale content.
  if (topicLabel !== scopedTopicLabel) {
    setScopedTopicLabel(topicLabel);
    setMessages([]);
    setInput("");
    setError(null);
  }

  const scrollRef = React.useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, isSending]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const query = input.trim();
    if (!query || isSending) return;
    setInput("");
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: query }]);
    setIsSending(true);
    try {
      const answer = await askChat(query, topicLabel);
      setMessages((prev) => [...prev, { role: "assistant", answer }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat request failed.");
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="border-t p-4">
      <div
        ref={scrollRef}
        className="mb-2 max-h-48 overflow-y-auto space-y-2"
        aria-live="polite"
      >
        {messages.length === 0 && !isSending && (
          <p className="text-xs text-muted-foreground">
            Ask a question about this topic. Answers draw only from its
            sources.
          </p>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <div key={index} className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">You: </span>
              {message.text}
            </div>
          ) : (
            <AssistantMessage key={index} answer={message.answer} />
          ),
        )}
        {isSending && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <LoaderCircle className="size-3 animate-spin" />
            Searching sources...
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      <form onSubmit={send} className="flex items-center gap-2">
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about this topic..."
          aria-label="Ask a question about this topic"
          disabled={isSending}
        />
        <Button
          type="submit"
          size="icon"
          disabled={isSending || input.trim().length === 0}
          aria-label="Send question"
        >
          <Send />
        </Button>
      </form>
    </div>
  );
}

function AssistantMessage({ answer }: { answer: AugmentedAnswer }) {
  return (
    <div className="space-y-1 text-xs">
      <p className="text-foreground">
        <span className="font-medium">Hedwig: </span>
        {answer.answer}
      </p>
      {answer.confident && answer.sources.length > 0 && (
        <p className="text-muted-foreground">
          From {answer.sources.length}{" "}
          {answer.sources.length === 1 ? "source" : "sources"}.
        </p>
      )}
    </div>
  );
}

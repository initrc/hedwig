"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { DigestTopic } from "@/lib/api";

export function DigestDetailSheet({
  topic,
  onOpenChange,
}: {
  topic: DigestTopic | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={topic !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{topic?.label}</SheetTitle>
          <SheetDescription>
            Topic details, sources, and scoped chat will appear here.
          </SheetDescription>
        </SheetHeader>
      </SheetContent>
    </Sheet>
  );
}

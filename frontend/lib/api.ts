const API_BASE_URL = process.env.API_BASE_URL ?? "/api";

export const fetcher = (path: string, init?: RequestInit) =>
  fetch(`${API_BASE_URL}${path}`, init).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  });

// POST a JSON body and parse the JSON response. Shared by endpoints that
// send a request body (e.g. /chat, /digest/run).
export const postJson = <T>(path: string, body: unknown) =>
  fetcher(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }) as Promise<T>;

export type Status =
  | { state: "running"; email_count: number }
  | { state: "idle"; last_digest_at: string | null };

export type CandidateImage = {
  url: string;
  alt: string;
  width?: number | null;
  height?: number | null;
};

export type DigestSource = {
  id: string;
  source: string;
  subject: string;
  original_url: string | null;
  clean_text: string;
};

export type DigestTopic = {
  label: string;
  summary: string;
  sources: DigestSource[];
  image: CandidateImage | null;
};

export type Digest = {
  date: string;
  topics: DigestTopic[];
};

export type AugmentedChunk = {
  digest_date: string;
  topic_label: string;
  source_id: string;
  source_subject: string;
  text: string;
  score: number;
};

export type AugmentedAnswer = {
  answer: string;
  sources: AugmentedChunk[];
  confident: boolean;
};

// The /chat endpoint takes a JSON-encoded string body (not a {query: ...}
// object), matching `query: Annotated[str, Body()]` on the backend.
export async function askChat(
  query: string,
  topicLabel?: string,
): Promise<AugmentedAnswer> {
  const params = topicLabel
    ? `?topic_label=${encodeURIComponent(topicLabel)}`
    : "";
  return postJson<AugmentedAnswer>(`/chat${params}`, query);
}

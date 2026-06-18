const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const fetcher = (path: string) =>
  fetch(`${API_BASE_URL}${path}`).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  });

export type Health = {
  status: string;
};

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

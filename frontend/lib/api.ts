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

export interface Job {
  id: string;
  filename: string;
  owner_id: string | null;
  source: "upload" | "youtube";
  source_url: string | null;
  status: "queued" | "downloading" | "processing" | "done" | "failed";
  progress: number;
  error: string | null;
  duration: number | null;
  transcriber: string | null;
  scorer: string | null;
  clip_count: number;
  post_count: number;
  auto_publish: boolean;
  created_at: string;
}

export interface Clip {
  id: string;
  index: number;
  start: number;
  end: number;
  duration: number;
  title: string;
  line: string;
  script: string;
  score: number;
  exported: boolean;
  export_name: string | null;
  publish: boolean;
}

export interface PlatformPost {
  id: string;
  clip_id: string;
  platform: string;
  status: "no_publicado" | "listo" | "publicado";
  url: string | null;
  views: number;
  likes: number;
  comments: number;
  earnings: number;
  currency: string;
  account: string | null;
  method: "manual" | "youtube_api";
  updated_at: string;
}

export type PostInput = Partial<
  Pick<
    PlatformPost,
    | "platform"
    | "status"
    | "url"
    | "views"
    | "likes"
    | "comments"
    | "earnings"
    | "currency"
    | "account"
    | "method"
  >
>;

export interface PlatformTotals {
  posts: number;
  views: number;
  likes: number;
  earnings: number;
}

export interface RecentPost {
  post_id: string;
  job_id: string;
  clip_id: string;
  title: string;
  platform: string;
  status: "no_publicado" | "listo" | "publicado";
  url: string | null;
  views: number;
  likes: number;
  earnings: number;
  currency: string;
}

export interface DashboardStats {
  jobs: number;
  clips: number;
  posts: number;
  publicados: number;
  total_views: number;
  total_likes: number;
  total_earnings: number;
  by_platform: Record<string, PlatformTotals>;
  recent_posts: RecentPost[];
  accounts: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface LinkedAccount {
  id: string;
  platform: string;
  name: string;
  handle: string;
  token: string | null;
  client_id: string | null;
  has_client_secret: boolean;
  redirect_uri: string | null;
  created_at: string;
}

export interface AccountInput {
  platform: string;
  name: string;
  handle: string;
  token: string | null;
  client_id?: string | null;
  client_secret?: string | null;
  redirect_uri?: string | null;
}

const TOKEN_KEY = "edgetape_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (body.detail) detail = body.detail;
    } catch {
      // ignorar cuerpos de error que no son JSON
    }
    if (resp.status === 401 && !path.startsWith("/api/auth")) {
      setToken(null);
      window.dispatchEvent(new CustomEvent("edgetape:unauthorized"));
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

// ── auth ───────────────────────────────────────────

export function register(email: string, password: string, name: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name }),
  }).then((resp) => {
    setToken(resp.access_token);
    return resp;
  });
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then((resp) => {
    setToken(resp.access_token);
    return resp;
  });
}

export function getMe(): Promise<User> {
  return request<User>("/api/auth/me");
}

// ── cuentas vinculadas ─────────────────────────────

export function getAccounts(): Promise<LinkedAccount[]> {
  return request<LinkedAccount[]>("/api/accounts");
}

export function createAccount(input: AccountInput): Promise<LinkedAccount> {
  return request<LinkedAccount>("/api/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateAccount(id: string, input: AccountInput): Promise<LinkedAccount> {
  return request<LinkedAccount>(`/api/accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function deleteAccount(id: string): Promise<void> {
  return request<void>(`/api/accounts/${id}`, { method: "DELETE" });
}

// ── jobs / clips ───────────────────────────────────

export function uploadFile(file: File): Promise<Job> {
  const form = new FormData();
  form.append("file", file);
  return request<Job>("/api/jobs", { method: "POST", body: form });
}

export function createYoutubeJob(url: string): Promise<Job> {
  return request<Job>("/api/jobs/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

export function getJob(id: string): Promise<Job> {
  return request<Job>(`/api/jobs/${id}`);
}

export function listJobs(): Promise<Job[]> {
  return request<Job[]>("/api/jobs");
}

export function getClips(jobId: string): Promise<Clip[]> {
  return request<Clip[]>(`/api/jobs/${jobId}/clips`);
}

export function setClipPublish(jobId: string, clipId: string, publish: boolean): Promise<Clip> {
  return request<Clip>(`/api/jobs/${jobId}/clips/${clipId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ publish }),
  });
}

export function patchJobSettings(jobId: string, autoPublish: boolean): Promise<Job> {
  return request<Job>(`/api/jobs/${jobId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auto_publish: autoPublish }),
  });
}

export function publishAll(
  jobId: string,
  platform: string,
  account: string | null,
): Promise<PlatformPost[]> {
  return request<PlatformPost[]>(`/api/jobs/${jobId}/publish-all`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, account }),
  });
}

export function exportClip(jobId: string, clipId: string): Promise<Clip> {
  return request<Clip>(`/api/jobs/${jobId}/clips/${clipId}/export`, { method: "POST" });
}

function withToken(url: string): string {
  const token = getToken();
  return token ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}` : url;
}

export function downloadUrl(jobId: string, clipId: string): string {
  return withToken(`/api/jobs/${jobId}/clips/${clipId}/download`);
}

export function previewUrl(jobId: string, clipId: string): string {
  return withToken(`/api/jobs/${jobId}/clips/${clipId}/preview`);
}

export function thumbUrl(jobId: string, clipId: string): string {
  return withToken(`/api/jobs/${jobId}/clips/${clipId}/thumb`);
}

// ── publicaciones ──────────────────────────────────

export function getPosts(jobId: string): Promise<PlatformPost[]> {
  return request<PlatformPost[]>(`/api/jobs/${jobId}/platforms`);
}

export function createPost(jobId: string, clipId: string, input: PostInput): Promise<PlatformPost> {
  return request<PlatformPost>(`/api/jobs/${jobId}/clips/${clipId}/platforms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updatePost(jobId: string, postId: string, input: PostInput): Promise<PlatformPost> {
  return request<PlatformPost>(`/api/jobs/${jobId}/platforms/${postId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function deletePost(jobId: string, postId: string): Promise<void> {
  return request<void>(`/api/jobs/${jobId}/platforms/${postId}`, { method: "DELETE" });
}

export function getYoutubeAuthUrl(accountId: string): Promise<{ auth_url: string; redirect_uri: string }> {
  return request<{ auth_url: string; redirect_uri: string }>(
    `/api/accounts/${accountId}/youtube/auth`,
  );
}

export function getDashboard(): Promise<DashboardStats> {
  return request<DashboardStats>("/api/dashboard");
}

export function pollJob(id: string, onUpdate: (job: Job) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const timer = window.setInterval(async () => {
      try {
        const job = await getJob(id);
        onUpdate(job);
        if (job.status === "done" || job.status === "failed") {
          window.clearInterval(timer);
          if (job.status === "failed") reject(new Error(job.error ?? "El procesamiento falló"));
          else resolve(job);
        }
      } catch (err) {
        window.clearInterval(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    }, 700);
  });
}

export const PLATFORM_LABELS: Record<string, string> = {
  youtube_shorts: "YouTube Shorts",
  tiktok: "TikTok",
  facebook_reels: "Facebook Reels",
  instagram_reels: "Instagram Reels",
  otros: "Otra plataforma",
};

export const POST_STATUS_LABELS: Record<string, string> = {
  no_publicado: "Sin publicar",
  listo: "Listo para subir",
  publicado: "Publicado",
};

export const POST_METHOD_LABELS: Record<string, string> = {
  manual: "subido a mano",
  youtube_api: "subido por la API",
};

export const ACCOUNT_PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  tiktok: "TikTok",
  facebook: "Facebook",
  instagram: "Instagram",
  otros: "Otra plataforma",
};

export function formatTimecode(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat("es", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency || "USD"}`;
  }
}

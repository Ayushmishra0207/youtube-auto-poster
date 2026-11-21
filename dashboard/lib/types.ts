export interface PipelineStatus {
  is_running: boolean;
  today_date: string;
  today_video_count: number;
  total_slots: number;
  next_scheduled_run: string;
  upload_window: string;
  last_log: string;
}

export interface VideoMeta {
  index: number;
  dir: string;
  date: string;
  title: string;
  title_english: string;
  description: string;
  tags: string[];
  thumbnail_text: string;
  slot: string;
  status: "ready" | "uploaded" | "rendering" | "generating" | "pending" | "failed";
  has_video: boolean;
  has_thumbnail: boolean;
  has_script: boolean;
  thumbnail_url: string;
  video_url: string;
  script_url: string;
  youtube_id: string;
  youtube_url: string;
  is_regenerating?: boolean;
}

export interface VideoScript {
  title: string;
  title_english: string;
  description: string;
  tags: string[];
  thumbnail_text: string;
  sections: {
    id: number;
    heading: string;
    narration: string;
    key_points: string[];
    image_search: string;
  }[];
}

export interface ShortMeta {
  index: number;
  dir: string;
  date: string;
  title: string;
  description: string;
  tags: string[];
  status: "ready" | "uploaded" | "generating" | "pending" | "failed";
  has_video: boolean;
  has_thumbnail: boolean;
  has_script: boolean;
  thumbnail_url: string;
  video_url: string;
  script_url: string;
  youtube_id: string;
  youtube_url: string;
  is_regenerating?: boolean;
}

export interface TopicsResponse {
  topics: string[];
  source: "override" | "auto";
}

export interface Settings {
  ANTHROPIC_API_KEY: string;
  PEXELS_API_KEY: string;
  KEEP_OUTPUT_DAYS: string;
  INSTAGRAM_APP_ID: string;
  INSTAGRAM_APP_SECRET: string;
  INSTAGRAM_ACCESS_TOKEN: string;
  INSTAGRAM_PAGE_ID: string;
  INSTAGRAM_BUSINESS_ACCOUNT_ID: string;
  R2_ACCOUNT_ID: string;
  R2_ACCESS_KEY_ID: string;
  R2_SECRET_ACCESS_KEY: string;
  R2_BUCKET_NAME: string;
  upload_slots: string[];
}

export interface InstagramPost {
  id: string;
  video_path: string;
  caption: string;
  publish_at_utc: string;
  status: "pending" | "posted" | "failed";
  error: string | null;
  instagram_media_id: string | null;
}

// ── Viral Clip Maker ──────────────────────────────────────────────────────────

export interface ClipMode {
  key: string;
  label: string;
  description: string;
  caption_style: string;
  min_len: number;
  max_len: number;
}

export interface ClipOptions {
  modes: ClipMode[];
  caption_styles: { key: string; label: string; highlight: string }[];
  lengths: { key: string; range: [number, number] | null }[];
  default_mode: string;
  music_available: boolean;
  music_track: string;
  available: boolean;
  unavailable_reason: string;
}

export interface ClipRequest {
  url: string;
  mode: string;
  num_clips: number;
  length: string;
  layout: "blur_fit" | "center_crop";
  caption_style: string;
  language: string;
  title_language: "hinglish" | "hindi" | "english";
  hook_text: boolean;
  watermark: string;
  audio_mode: "original" | "original_music" | "music_only";
  credit_source: boolean;
  use_ai: boolean;
  // "Split into parts" (series) mode
  job_type?: "viral" | "series";
  part_seconds?: number;
  range_start?: number;
  range_end?: number;
  series_title?: string;
  part_label?: string;
  source_file?: string;
}

export interface ClipResult {
  index: number;
  start: number;
  end: number;
  duration: number;
  hook_text: string;
  title: string;
  description: string;
  hashtags: string[];
  score: number;
  reason: string;
  picked_by: "ai" | "signals" | "series";
  part?: number;
  parts_total?: number;
  video_url: string;
  thumbnail_url: string;
  has_video: boolean;
  youtube_id: string;
  youtube_url: string;
}

export interface ClipJob {
  job_id: string;
  state: "queued" | "running" | "done" | "failed";
  stage: string;
  progress: number;
  message: string;
  error: string;
  created_at: number;
  request: ClipRequest;
  source: { title?: string; channel?: string; duration?: number; url?: string; thumbnail?: string };
  clips: ClipResult[];
  detected_language?: string;
}


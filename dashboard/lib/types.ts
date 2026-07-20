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

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
  status: "ready" | "rendering" | "generating" | "pending" | "failed";
  has_video: boolean;
  has_thumbnail: boolean;
  has_script: boolean;
  thumbnail_url: string;
  video_url: string;
  script_url: string;
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

export interface TopicsResponse {
  topics: string[];
  source: "override" | "auto";
}

export interface Settings {
  ANTHROPIC_API_KEY: string;
  PEXELS_API_KEY: string;
  KEEP_OUTPUT_DAYS: string;
  upload_slots: string[];
}

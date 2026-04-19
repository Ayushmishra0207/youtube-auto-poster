"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import OverviewPanel from "@/components/OverviewPanel";
import AnalyticsPanel from "@/components/AnalyticsPanel";
import TopicsPanel from "@/components/TopicsPanel";
import VideoGrid from "@/components/VideoGrid";
import LogViewer from "@/components/LogViewer";
import ScheduleTimeline from "@/components/ScheduleTimeline";
import SettingsPanel from "@/components/SettingsPanel";
import UploadPanel from "@/components/UploadPanel";

export type Tab = "overview" | "analytics" | "topics" | "videos" | "upload" | "logs" | "schedule" | "settings";

export default function Dashboard() {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar active={tab} onSelect={setTab} />

      <main className="flex-1 overflow-y-auto">
        <div className="max-w-7xl mx-auto px-6 py-8">
          {tab === "overview"   && <OverviewPanel />}
          {tab === "analytics"  && <AnalyticsPanel />}
          {tab === "topics"     && <TopicsPanel />}
          {tab === "videos"     && <VideoGrid />}
          {tab === "upload"     && <UploadPanel />}
          {tab === "logs"       && <LogViewer />}
          {tab === "schedule"   && <ScheduleTimeline />}
          {tab === "settings"   && <SettingsPanel />}
        </div>
      </main>
    </div>
  );
}

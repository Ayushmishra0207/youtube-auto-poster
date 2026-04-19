"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import MobileHeader from "@/components/MobileHeader";
import MobileNav from "@/components/MobileNav";
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
      {/* Sidebar — desktop only */}
      <div className="hidden md:block">
        <Sidebar active={tab} onSelect={setTab} />
      </div>

      <main className="flex-1 overflow-y-auto">
        {/* Mobile top header */}
        <MobileHeader />

        <div className="max-w-7xl mx-auto px-4 py-5 pb-24 md:px-6 md:py-8 md:pb-8">
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

      {/* Mobile bottom navigation */}
      <MobileNav active={tab} onSelect={setTab} />
    </div>
  );
}

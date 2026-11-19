"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import MobileHeader from "@/components/MobileHeader";
import MobileNav from "@/components/MobileNav";
import OverviewPanel from "@/components/OverviewPanel";
import AnalyticsPanel from "@/components/AnalyticsPanel";
import TopicsPanel from "@/components/TopicsPanel";
import VideoGrid from "@/components/VideoGrid";
import ShortsPanel from "@/components/ShortsPanel";
import InstagramPanel from "@/components/InstagramPanel";
import LogViewer from "@/components/LogViewer";
import ScheduleTimeline from "@/components/ScheduleTimeline";
import SettingsPanel from "@/components/SettingsPanel";
import UploadPanel from "@/components/UploadPanel";
import LoginScreen from "@/components/LoginScreen";
import ClipsPanel from "@/components/ClipsPanel";
import { api, AuthError, AUTH_EXPIRED_EVENT, clearToken, getToken } from "@/lib/api";

const TABS = ["overview", "analytics", "topics", "videos", "shorts", "clips", "instagram", "upload", "logs", "schedule", "settings"] as const;
export type Tab = (typeof TABS)[number];

export default function Dashboard() {
  const [tab, setTab]               = useState<Tab>("overview");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [loggedIn, setLoggedIn]       = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setAuthChecked(true);
      return;
    }
    api.me()
      .then(() => setLoggedIn(true))
      .catch((err) => {
        // Only a real 401 invalidates the token; a cold-start timeout or 5xx
        // shouldn't log out a user whose session is still valid.
        if (err instanceof AuthError) clearToken();
        else setLoggedIn(true);
      })
      .finally(() => setAuthChecked(true));
  }, []);

  // Any 401 mid-session (expired token, server session DB wiped by a redeploy) → back to login
  useEffect(() => {
    const onExpired = () => setLoggedIn(false);
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, []);

  // Deep links: /#clips opens the Clip Maker directly
  useEffect(() => {
    const fromHash = window.location.hash.slice(1);
    if ((TABS as readonly string[]).includes(fromHash)) setTab(fromHash as Tab);
  }, []);

  const selectTab = (t: Tab) => {
    setTab(t);
    setDrawerOpen(false); // close drawer when nav item tapped
    history.replaceState(null, "", `#${t}`);
  };

  if (!authChecked) return null;
  if (!loggedIn) return <LoginScreen onLoggedIn={() => setLoggedIn(true)} />;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Desktop sidebar (always visible ≥ md) ── */}
      <div className="hidden md:block shrink-0">
        <Sidebar active={tab} onSelect={selectTab} />
      </div>

      {/* ── Mobile drawer backdrop ── */}
      {drawerOpen && (
        <div
          className="fixed inset-0 z-40 md:hidden"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* ── Mobile drawer (slides in from left) ── */}
      <div
        className="fixed inset-y-0 left-0 z-50 md:hidden transition-transform duration-300 ease-in-out"
        style={{ transform: drawerOpen ? "translateX(0)" : "translateX(-100%)" }}
      >
        <Sidebar active={tab} onSelect={selectTab} onClose={() => setDrawerOpen(false)} />
      </div>

      {/* ── Main content ── */}
      <main className="flex-1 overflow-y-auto min-w-0">
        {/* Mobile sticky top bar with hamburger */}
        <MobileHeader onMenuClick={() => setDrawerOpen(true)} />

        <div className="max-w-7xl mx-auto px-4 py-5 pb-24 md:px-6 md:py-8 md:pb-8">
          {tab === "overview"   && <OverviewPanel />}
          {tab === "analytics"  && <AnalyticsPanel />}
          {tab === "topics"     && <TopicsPanel />}
          {tab === "videos"     && <VideoGrid />}
          {tab === "shorts"     && <ShortsPanel />}
          {tab === "clips"      && <ClipsPanel />}
          {tab === "instagram"  && <InstagramPanel />}
          {tab === "upload"     && <UploadPanel />}
          {tab === "logs"       && <LogViewer />}
          {tab === "schedule"   && <ScheduleTimeline />}
          {tab === "settings"   && <SettingsPanel />}
        </div>
      </main>

      {/* ── Mobile bottom navigation ── */}
      <MobileNav active={tab} onSelect={selectTab} />
    </div>
  );
}

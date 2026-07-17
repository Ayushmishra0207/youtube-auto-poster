"use client";

import { type Tab } from "@/app/page";
import {
  LayoutDashboard, BarChart2, Film, Upload,
  ListTodo, ScrollText, CalendarClock, Settings, Sparkles,
} from "lucide-react";

const NAV: { id: Tab; icon: React.ReactNode; label: string }[] = [
  { id: "overview",  icon: <LayoutDashboard size={19} />, label: "Home"     },
  { id: "analytics", icon: <BarChart2 size={19} />,       label: "Stats"    },
  { id: "videos",    icon: <Film size={19} />,            label: "Videos"   },
  { id: "shorts",    icon: <Sparkles size={19} />,        label: "Shorts"   },
  { id: "upload",    icon: <Upload size={19} />,          label: "Upload"   },
  { id: "topics",    icon: <ListTodo size={19} />,        label: "Topics"   },
  { id: "logs",      icon: <ScrollText size={19} />,      label: "Logs"     },
  { id: "schedule",  icon: <CalendarClock size={19} />,   label: "Schedule" },
  { id: "settings",  icon: <Settings size={19} />,        label: "Settings" },
];

export default function MobileNav({
  active,
  onSelect,
}: {
  active: Tab;
  onSelect: (t: Tab) => void;
}) {
  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-40 border-t"
      style={{
        background: "rgba(8,12,24,0.98)",
        borderColor: "var(--border)",
        backdropFilter: "blur(20px)",
      }}
    >
      <div className="flex overflow-x-auto scrollbar-hide">
        {NAV.map((item) => {
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              className="relative flex flex-col items-center gap-1 py-2.5 px-3 min-w-[64px] shrink-0 transition-all duration-150"
              style={{ color: isActive ? "#4FC3F7" : "#64748b" }}
            >
              {/* Active indicator line */}
              {isActive && (
                <div
                  className="absolute top-0 left-1/2 -translate-x-1/2 w-6 h-0.5 rounded-full"
                  style={{ background: "#4FC3F7", boxShadow: "0 0 6px rgba(79,195,247,0.8)" }}
                />
              )}
              <span style={{ opacity: isActive ? 1 : 0.55 }}>{item.icon}</span>
              <span className="text-[10px] font-medium whitespace-nowrap leading-none">
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}

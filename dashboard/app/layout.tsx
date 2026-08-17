import type { Metadata } from "next";
import "./globals.css";
import { AccountProvider } from "@/lib/accountContext";

export const metadata: Metadata = {
  title: "YouTube Auto-Poster",
  description: "Hindi YouTube pipeline dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-navy-950 text-slate-200 antialiased">
        {/* Ambient background blobs */}
        <div className="blob-1" aria-hidden />
        <div className="blob-2" aria-hidden />
        <div className="relative z-10">
          <AccountProvider>{children}</AccountProvider>
        </div>
      </body>
    </html>
  );
}

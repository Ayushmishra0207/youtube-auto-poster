"use client";

import { useState } from "react";
import { api, AuthError, setToken } from "@/lib/api";
import { Sparkles, Lock } from "lucide-react";

export default function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy]         = useState(false);
  const [error, setError]       = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setBusy(true);
    setError("");
    try {
      const res = await api.login(username.trim(), password);
      setToken(res.token);
      onLoggedIn();
    } catch (err) {
      // Only a 401 means wrong credentials — a timeout/5xx is the server waking up
      setError(err instanceof AuthError
        ? "Invalid username or password"
        : (err as Error)?.name === "AbortError" || err instanceof TypeError
          ? "Server is waking up or unreachable — wait a minute and try again"
          : (err as Error)?.message || "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form
        onSubmit={handleSubmit}
        className="glass rounded-2xl p-8 w-full max-w-sm space-y-5"
        style={{ border: "1px solid var(--border-strong)" }}
      >
        <div className="flex items-center gap-2 justify-center">
          <Sparkles size={20} style={{ color: "#4FC3F7" }} />
          <h1 className="text-lg font-bold text-white">YouTube Auto-Poster</h1>
        </div>
        <p className="text-xs text-center" style={{ color: "var(--muted)" }}>
          Sign in to your dashboard
        </p>

        <div className="space-y-3">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoFocus
            className="w-full px-3 py-2.5 rounded-lg text-sm bg-transparent outline-none"
            style={{ border: "1px solid var(--border)", color: "white" }}
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="Password"
            className="w-full px-3 py-2.5 rounded-lg text-sm bg-transparent outline-none"
            style={{ border: "1px solid var(--border)", color: "white" }}
          />
        </div>

        {error && <p className="text-xs text-center text-red-400">{error}</p>}

        <button
          type="submit"
          disabled={busy || !username.trim() || !password}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50"
          style={{
            background: "linear-gradient(135deg, rgba(79,195,247,0.2) 0%, rgba(124,58,237,0.2) 100%)",
            border: "1px solid var(--border-strong)",
            color: "#4FC3F7",
          }}
        >
          {busy ? (
            <div className="w-4 h-4 border border-cyan-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Lock size={14} />
          )}
          {busy ? "Signing in…" : "Sign In"}
        </button>
      </form>
    </div>
  );
}

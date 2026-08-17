"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface AccountRow {
  id: string;
  label: string;
  locale: string;
  enabled: boolean;
  created_at: string;
  token_exists: boolean;
}

export default function AccountsPanel() {
  const [accounts, setAccounts] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    api.listAccounts()
      .then((data) => setAccounts(data.accounts || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const toggle = async (id: string, enabled: boolean) => {
    await api.toggleAccount(id, enabled);
    load();
  };

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-2">YouTube Accounts</h1>
      <p className="text-sm text-slate-400 mb-6">
        Each account has its own content niche, schedule, and locale. To connect a new one, run
        from a terminal: <code>python setup_auth.py --account &lt;id&gt; --label "Channel Name" --locale hi</code>
      </p>
      {loading ? (
        <p>Loading...</p>
      ) : (
        <div className="flex flex-col gap-3">
          {accounts.map((a) => (
            <div key={a.id} className="flex items-center justify-between p-4 rounded-lg border border-slate-700">
              <div>
                <div className="font-medium">{a.label}</div>
                <div className="text-xs text-slate-400">
                  id: {a.id} · locale: {a.locale} · connected: {a.token_exists ? "yes" : "NO TOKEN FILE"}
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={a.enabled} onChange={(e) => toggle(a.id, e.target.checked)} />
                Enabled
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

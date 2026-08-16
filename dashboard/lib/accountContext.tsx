"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "./api";

interface AccountInfo {
  id: string;
  label: string;
  locale: string;
  enabled: boolean;
}

interface AccountContextValue {
  accountId: string;
  setAccountId: (id: string) => void;
  accounts: AccountInfo[];
}

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [accountId, setAccountIdState] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem("currentAccountId")) || "default"
  );

  useEffect(() => {
    api.listAccounts().then((data) => setAccounts(data.accounts || []));
  }, []);

  const setAccountId = (id: string) => {
    setAccountIdState(id);
    if (typeof window !== "undefined") localStorage.setItem("currentAccountId", id);
  };

  return (
    <AccountContext.Provider value={{ accountId, setAccountId, accounts }}>
      {children}
    </AccountContext.Provider>
  );
}

export function useAccount(): AccountContextValue {
  const ctx = useContext(AccountContext);
  if (!ctx) throw new Error("useAccount must be used within an AccountProvider");
  return ctx;
}

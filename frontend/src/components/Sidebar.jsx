import { LayoutDashboard, Users, Megaphone, ScrollText, Zap, Shield, LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { getSessionUser, logout } from "@/lib/auth";
import { LOGOUT } from "@/constants/testIds";
import { OpenAdsLogo } from "@/components/OpenAdsLogo";

const NAV = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "accounts", label: "Accounts", icon: Users },
  { key: "campaigns", label: "Campaigns", icon: Megaphone },
  { key: "proxies", label: "Proxies", icon: Shield },
  { key: "logs", label: "Activity Logs", icon: ScrollText },
  { key: "tester", label: "Session Tester", icon: Zap },
];

export const Sidebar = ({ active, onChange, accountCount, activeCampaigns }) => {
  const navigate = useNavigate();
  const adminUser = getSessionUser();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <aside
      data-testid="sidebar"
      className="w-64 flex-shrink-0 bg-[#090D16] border-r border-slate-800/80 p-5 flex-col justify-between hidden md:flex"
    >
      <div>
        <div className="px-1 mb-10">
          <OpenAdsLogo size="md" />
        </div>

        <nav className="space-y-1.5">
          {NAV.map((item) => {
            const Icon = item.icon;
            const isActive = active === item.key;
            return (
              <button
                key={item.key}
                data-testid={`nav-${item.key}`}
                onClick={() => onChange(item.key)}
                className={`group w-full flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? "bg-indigo-500/10 text-indigo-300 border border-indigo-500/25 shadow-[0_0_18px_rgba(99,102,241,0.12)]"
                    : "text-slate-400 hover:text-slate-100 hover:bg-slate-800/50 border border-transparent"
                }`}
              >
                <Icon className={`h-4.5 w-4.5 ${isActive ? "text-indigo-400" : ""}`} size={18} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span>Connected</span>
            <span className="font-mono text-slate-200">{accountCount} acct</span>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center gap-2">
              <span className="relative inline-flex h-2 w-2 rounded-full bg-indigo-500 animate-pulse" />
              Live campaigns
            </span>
            <span className="font-mono text-indigo-400">{activeCampaigns}</span>
          </div>
        </div>
        <button
          type="button"
          data-testid={LOGOUT.button}
          onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:text-red-300 hover:bg-red-500/10 border border-transparent hover:border-red-500/20 transition-all"
        >
          <LogOut size={16} />
          Sign Out
        </button>
        {adminUser && (
          <p className="text-[10px] text-slate-600 px-1 text-center font-mono truncate">
            {adminUser}
          </p>
        )}
        <p className="text-[10px] text-slate-600 px-1 leading-relaxed">
          Broadcasting via Telethon string sessions. Use responsibly & respect Telegram limits.
        </p>
      </div>
    </aside>
  );
};

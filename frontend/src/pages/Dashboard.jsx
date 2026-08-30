import { useCallback, useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import { StatsCards } from "../components/StatsCards";
import { AccountsManager } from "../components/AccountsManager";
import { CampaignCreator } from "../components/CampaignCreator";
import { CampaignList } from "../components/CampaignList";
import { ActivityLogs } from "../components/ActivityLogs";
import { SessionTester } from "../components/SessionTester";
import { ProxyManager } from "../components/ProxyManager";
import { api } from "../api";

const SECTION_TITLES = {
  overview: "Command Center",
  accounts: "Accounts",
  campaigns: "Campaigns",
  logs: "Logs",
  proxies: "Proxies",
  tester: "Tester",
};

export default function Dashboard() {
  const [section, setSection] = useState("overview");
  const [stats, setStats] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [logs, setLogs] = useState([]);
  const [accountGroups, setAccountGroups] = useState([]);
  const [proxies, setProxies] = useState([]);
  const [coverage, setCoverage] = useState(null);
  const [mobileNav, setMobileNav] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [s, a, c, l, ag, px, cov] = await Promise.all([
        api.stats(),
        api.listAccounts(),
        api.listCampaigns(),
        api.logs(),
        api.accountGroups(),
        api.listProxies(),
        api.proxyCoverage(),
      ]);
      setStats(s);
      setAccounts(a);
      setCampaigns(c);
      setLogs(l);
      setAccountGroups(ag);
      setProxies(px);
      setCoverage(cov);
    } catch (e) {
      // silent; individual actions toast their own errors
    }
  }, []);

  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 8000);
    return () => clearInterval(t);
  }, [loadAll]);

  const activeCampaigns = campaigns.filter((c) => c.running || c.status === "running").length;

  return (
    <div className="flex h-screen w-full bg-[#0B0F19] text-slate-100 overflow-hidden font-sans tp-grain">
      <Sidebar
        active={section}
        onChange={(s) => { setSection(s); setMobileNav(false); }}
        accountCount={accounts.length}
        activeCampaigns={activeCampaigns}
      />

      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {/* top bar */}
        <div className="sticky top-0 z-20 backdrop-blur-xl bg-[#0B0F19]/80 border-b border-slate-800/80 px-5 md:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              data-testid="mobile-nav-toggle"
              className="md:hidden text-slate-400"
              onClick={() => setMobileNav((v) => !v)}
            >
              <Menu size={22} />
            </button>
            <div>
              <p className="text-[11px] font-mono uppercase tracking-widest text-indigo-500/70">OpenAds</p>
              <h1 className="font-display text-lg font-bold text-white -mt-0.5">{SECTION_TITLES[section]}</h1>
            </div>
          </div>
          {(section === "overview" || section === "campaigns") && accounts.length > 0 && (
            <CampaignCreator accountCount={accounts.length} accountGroups={accountGroups} onCreated={loadAll} />
          )}
        </div>

        {/* mobile nav */}
        {mobileNav && (
          <div className="md:hidden border-b border-slate-800 bg-[#090D16] p-3 flex flex-wrap gap-2">
            {["overview", "accounts", "campaigns", "logs", "proxies", "tester"].map((k) => (
              <button
                key={k}
                data-testid={`mobile-nav-${k}`}
                onClick={() => { setSection(k); setMobileNav(false); }}
                className={`px-3 py-1.5 rounded-lg text-xs capitalize ${section === k ? "bg-indigo-500/15 text-indigo-300" : "bg-slate-800 text-slate-300"}`}
              >
                {k}
              </button>
            ))}
          </div>
        )}

        <div className="p-5 md:p-8 space-y-8">
          {section === "overview" && (
            <>
              <StatsCards stats={stats} />
              <div>
                <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white mb-5">Campaigns</h2>
                <CampaignList campaigns={campaigns} onRefresh={loadAll} accountCount={accounts.length} accountGroups={accountGroups} />
              </div>
            </>
          )}

          {section === "accounts" && <AccountsManager accounts={accounts} accountGroups={accountGroups} onRefresh={loadAll} />}

          {section === "campaigns" && (
            <div>
              <div className="flex items-center justify-between mb-5">
                <div>
                  <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white">Campaigns</h2>
                  <p className="text-sm text-slate-400 mt-1">Toggle campaigns on to auto-broadcast at your set interval.</p>
                </div>
                {accounts.length > 0 && <CampaignCreator accountCount={accounts.length} accountGroups={accountGroups} onCreated={loadAll} />}
              </div>
              <CampaignList campaigns={campaigns} onRefresh={loadAll} accountCount={accounts.length} accountGroups={accountGroups} />
            </div>
          )}

          {section === "logs" && <ActivityLogs logs={logs} onRefresh={loadAll} />}

          {section === "proxies" && (
            <ProxyManager proxies={proxies} coverage={coverage} accountGroups={accountGroups} onRefresh={loadAll} />
          )}

          {section === "tester" && <SessionTester accounts={accounts} />}
        </div>
      </main>
    </div>
  );
}

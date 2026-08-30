import { motion } from "framer-motion";
import { toast } from "sonner";
import { Play, Square, Trash2, Megaphone, Clock, Users, Type, Image as ImageIcon, Forward, Layers, Gauge, Info, UserMinus } from "lucide-react";
import { Button } from "./ui/button";
import { CampaignCreator } from "./CampaignCreator";
import { TargetsHealth } from "./TargetsHealth";
import { BansList } from "./BansList";
import { api } from "../api";

const typeIcon = { text: Type, media: ImageIcon, forward: Forward };

export const CampaignList = ({ campaigns, onRefresh, accountCount = 0, accountGroups = [] }) => {
  const toggle = async (c) => {
    try {
      if (c.running || c.status === "running") {
        await api.stopCampaign(c.id);
        toast.info("Campaign stopped");
      } else {
        await api.startCampaign(c.id);
        toast.success("Campaign started — broadcasting now");
      }
      onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Action failed");
    }
  };

  const remove = async (c) => {
    if (!window.confirm(`Are you sure you want to delete campaign "${c.name}"?`)) return;
    try {
      await api.deleteCampaign(c.id);
      toast.success("Campaign deleted");
      onRefresh();
    } catch {
      toast.error("Delete failed");
    }
  };

  const removeAccounts = async (c) => {
    if (!c.account_batch_id) {
      toast.error("This campaign uses All accounts — pick a campaign with a named section first");
      return;
    }
    const section = c.account_batch_name || "this section";
    const ok = window.confirm(
      `Remove ALL accounts used by campaign "${c.name}"?\n\nSection: ${section}\n\nOnly this campaign's accounts will be deleted — not accounts from other sections.\nThe campaign will be stopped.`
    );
    if (!ok) return;
    try {
      const res = await api.deleteCampaignAccounts(c.id);
      toast.success(`Removed ${res.deleted} account(s) from "${res.campaign_name}" (${res.batch_name || section})`);
      onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to remove campaign accounts");
    }
  };

  if (campaigns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-12 text-center">
        <Megaphone className="mx-auto text-slate-700" size={40} />
        {accountCount === 0 ? (
          <>
            <p className="mt-3 text-slate-300 text-sm font-medium">Upload accounts first</p>
            <p className="mt-1 text-slate-500 text-sm max-w-sm mx-auto">
              Go to <span className="text-indigo-400">Accounts</span> and upload your Telegram <span className="font-mono">.session</span> files. Once connected, the <span className="text-indigo-400">Create Ad Campaign</span> button will appear here.
            </p>
          </>
        ) : (
          <p className="mt-3 text-slate-400 text-sm">No campaigns yet. Click <span className="text-indigo-400">Create Ad Campaign</span> above to start broadcasting.</p>
        )}
      </div>
    );
  }

  return (
    <div data-testid="campaign-dashboard-list" className="grid grid-cols-1 xl:grid-cols-2 gap-4">
      {campaigns.map((c, i) => {
        const running = c.running || c.status === "running";
        const Icon = typeIcon[c.message_type] || Type;
        return (
          <motion.div
            key={c.id}
            data-testid={`campaign-card-${c.id}`}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: i * 0.04 }}
            className={`rounded-xl border bg-slate-900/90 p-5 transition-all duration-200 ${
              running ? "border-indigo-500/40 shadow-[0_0_22px_rgba(99,102,241,0.12)]" : "border-slate-800"
            }`}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3 min-w-0">
                <div className="h-10 w-10 rounded-lg bg-slate-800 flex items-center justify-center flex-shrink-0">
                  <Icon size={18} className="text-indigo-300" />
                </div>
                <div className="min-w-0">
                  <p className="font-semibold text-white truncate">{c.name}</p>
                  <p className="text-xs text-slate-500 flex items-center gap-1"><Layers size={11} /> {c.account_batch_name || "All accounts"}</p>
                </div>
              </div>
              <span
                data-testid={`campaign-status-${c.id}`}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium flex-shrink-0 ${
                  running
                    ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                    : "bg-slate-700/30 text-slate-400 border border-slate-700"
                }`}
              >
                {running && <span className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-pulse" />}
                {running ? "running" : "stopped"}
              </span>
            </div>

            {c.text && <p className="mt-4 text-sm text-slate-400 line-clamp-2 bg-slate-950/50 rounded-lg p-3 border border-slate-800">{c.text}</p>}

            {!running && c.last_error && (
              <p data-testid={`campaign-last-error-${c.id}`} className="mt-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2 flex items-start gap-2">
                <Info size={13} className="mt-0.5 flex-shrink-0" /> Stopped: {c.last_error}
              </p>
            )}

            <div className="mt-4 grid grid-cols-6 gap-3 text-center">
              <div>
                <p className="text-[10px] font-mono uppercase text-slate-500">Interval</p>
                <p className="text-sm font-semibold text-slate-200 flex items-center justify-center gap-1"><Clock size={12} />{c.interval_seconds ?? (c.interval_minutes ? c.interval_minutes * 60 : 60)}s</p>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase text-slate-500">Speed</p>
                <p className="text-sm font-semibold text-slate-200 flex items-center justify-center gap-1"><Gauge size={12} />{c.concurrency ?? 25}x</p>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase text-slate-500">Targets</p>
                <p className="text-sm font-semibold text-slate-200 flex items-center justify-center gap-1"><Users size={12} />{c.target_groups?.length || 0}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase text-slate-500">Sent</p>
                <p className="text-sm font-semibold text-indigo-400">{c.sent_count || 0}</p>
              </div>
              <div>
                <p className="text-[10px] font-mono uppercase text-slate-500">Dead</p>
                <p className="text-sm font-semibold text-red-400">{c.dead_groups_count || 0}</p>
              </div>
              <div>
                <BansList campaign={c} bannedCount={c.banned_pairs_count} />
              </div>
            </div>

            <div className="mt-5 flex items-center justify-between gap-2 flex-wrap">
              <Button
                data-testid={`campaign-toggle-${c.id}`}
                size="sm"
                onClick={() => toggle(c)}
                className={`gap-2 h-9 px-4 font-medium ${
                  running
                    ? "bg-rose-600 hover:bg-rose-500 text-white"
                    : "bg-indigo-600 hover:bg-indigo-500 text-white"
                }`}
              >
                {running ? <><Square size={14} /> Stop</> : <><Play size={14} /> Start</>}
              </Button>
              <div className="flex items-center gap-1 flex-wrap justify-end">
                <TargetsHealth campaign={c} onRefresh={onRefresh} />
                <CampaignCreator
                  editCampaign={c}
                  accountCount={accountCount}
                  accountGroups={accountGroups}
                  onCreated={onRefresh}
                />
                <Button
                  data-testid={`campaign-remove-accounts-${c.id}`}
                  variant="ghost"
                  size="sm"
                  onClick={() => removeAccounts(c)}
                  className="text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 h-8 gap-1.5"
                  title="Remove only accounts used by this campaign"
                >
                  <UserMinus size={14} /> Remove accounts
                </Button>
                <Button
                  data-testid={`campaign-delete-${c.id}`}
                  variant="ghost"
                  size="sm"
                  onClick={() => remove(c)}
                  className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 h-8 gap-1.5"
                >
                  <Trash2 size={14} /> Delete
                </Button>
              </div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
};

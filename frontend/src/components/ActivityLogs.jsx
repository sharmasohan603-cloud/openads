import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, XCircle, ScrollText, Trash2, Filter } from "lucide-react";
import { Button } from "./ui/button";
import { api } from "../api";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "success", label: "Success" },
  { key: "failed", label: "Failed" },
];

export const ActivityLogs = ({ logs, onRefresh }) => {
  const [filter, setFilter] = useState("all");

  const clear = async () => {
    try {
      await api.clearLogs();
      toast.success("Logs cleared");
      onRefresh();
    } catch {
      toast.error("Failed to clear");
    }
  };

  const rows = logs.filter((l) => filter === "all" || l.status === filter);

  return (
    <section data-testid="activity-logs-table">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white">Activity Logs</h2>
          <p className="text-sm text-slate-400 mt-1">Real-time send results across all campaigns.</p>
        </div>
        <Button
          data-testid="logs-clear-button"
          onClick={clear}
          variant="outline"
          size="sm"
          className="border-slate-700 bg-slate-950 hover:bg-slate-800 text-slate-300 gap-2"
        >
          <Trash2 size={14} /> Clear
        </Button>
      </div>

      <div className="flex items-center gap-2 mb-4">
        <Filter size={14} className="text-slate-500" />
        {FILTERS.map((f) => (
          <button
            key={f.key}
            data-testid={`log-filter-${f.key}`}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              filter === f.key
                ? "bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
                : "bg-slate-900 text-slate-400 border border-slate-800 hover:text-slate-200"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900/90 overflow-hidden">
        {rows.length === 0 ? (
          <div className="p-12 text-center">
            <ScrollText className="mx-auto text-slate-700" size={36} />
            <p className="mt-3 text-slate-500 text-sm">No log entries.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="text-[11px] font-mono uppercase tracking-wider text-slate-500 border-b border-slate-800">
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Campaign</th>
                  <th className="px-5 py-3">Account</th>
                  <th className="px-5 py-3">Group</th>
                  <th className="px-5 py-3">Time</th>
                  <th className="px-5 py-3">Detail</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((l) => (
                  <tr key={l.id} data-testid={`log-row-${l.id}`} className="border-b border-slate-800/60 hover:bg-slate-800/30 transition-colors">
                    <td className="px-5 py-3">
                      {l.status === "success" ? (
                        <span className="inline-flex items-center gap-1.5 text-indigo-400 text-xs"><CheckCircle2 size={14} /> Sent</span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-rose-400 text-xs"><XCircle size={14} /> Failed</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-slate-300">{l.campaign_name}</td>
                    <td className="px-5 py-3 text-slate-400">{l.account_name}</td>
                    <td className="px-5 py-3 text-slate-400">{l.group_title}</td>
                    <td className="px-5 py-3 text-slate-500 font-mono text-xs">{new Date(l.timestamp).toLocaleString()}</td>
                    <td className={`px-5 py-3 text-xs max-w-[220px] truncate ${l.status === "failed" ? "text-rose-400/80" : "text-amber-400/80"}`}>{l.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
};

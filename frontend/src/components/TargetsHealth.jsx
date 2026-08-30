import { useState } from "react";
import { toast } from "sonner";
import { Activity, Loader2, Trash2, CheckCircle2, XCircle, HelpCircle, AlertTriangle } from "lucide-react";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "./ui/dialog";
import { api } from "../api";

const HEALTH = {
  dead: { label: "Dead", cls: "text-rose-400 bg-rose-500/10 border-rose-500/20", icon: XCircle },
  failing: { label: "Failing", cls: "text-amber-400 bg-amber-500/10 border-amber-500/20", icon: AlertTriangle },
  ok: { label: "OK", cls: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20", icon: CheckCircle2 },
  unknown: { label: "No data", cls: "text-slate-400 bg-slate-700/30 border-slate-700", icon: HelpCircle },
};

export const TargetsHealth = ({ campaign, onRefresh }) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState([]);
  const [removing, setRemoving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.campaignTargets(campaign.id);
      setRows(data);
    } catch {
      toast.error("Failed to load target health");
    } finally {
      setLoading(false);
    }
  };

  const removeOne = async (id) => {
    try {
      await api.removeGroups(campaign.id, [id]);
      toast.success("Group removed from campaign");
      setRows((r) => r.filter((x) => x.id !== id));
      onRefresh?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to remove");
    }
  };

  const removeAllDead = async () => {
    const dead = rows.filter((r) => r.health === "dead").map((r) => r.id);
    if (dead.length === 0) return toast.info("No dead groups to remove");
    setRemoving(true);
    try {
      await api.removeGroups(campaign.id, dead);
      toast.success(`Removed ${dead.length} dead groups`);
      setRows((r) => r.filter((x) => x.health !== "dead"));
      onRefresh?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to remove");
    } finally {
      setRemoving(false);
    }
  };

  const deadCount = rows.filter((r) => r.health === "dead").length;

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) load(); }}>
      <DialogTrigger asChild>
        <Button
          data-testid={`campaign-targets-open-${campaign.id}`}
          variant="ghost"
          size="sm"
          className="text-slate-300 hover:text-indigo-300 hover:bg-indigo-500/10 h-8 gap-1.5"
        >
          <Activity size={14} /> Targets
        </Button>
      </DialogTrigger>
      <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <Activity size={18} className="text-indigo-400" /> Target Health — {campaign.name}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            Per-group delivery results. Prune dead groups (0 delivered, only failures) to lift your success rate.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between py-1">
          <p className="text-xs font-mono text-slate-400">
            {rows.length} groups · <span className="text-rose-400">{deadCount} dead</span>
          </p>
          <Button
            data-testid="remove-all-dead-button"
            onClick={removeAllDead}
            disabled={removing || deadCount === 0}
            size="sm"
            className="bg-rose-600 hover:bg-rose-500 text-white gap-2 h-8"
          >
            {removing ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} Remove all dead ({deadCount})
          </Button>
        </div>

        <div className="overflow-y-auto rounded-lg border border-slate-800 flex-1">
          {loading ? (
            <div className="p-10 text-center text-slate-500"><Loader2 className="animate-spin mx-auto" /></div>
          ) : rows.length === 0 ? (
            <div className="p-10 text-center text-slate-500 text-sm">No targets.</div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-[11px] font-mono uppercase text-slate-500 border-b border-slate-800">
                  <th className="px-4 py-2.5">Group</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5 text-center">Sent</th>
                  <th className="px-4 py-2.5 text-center">Failed</th>
                  <th className="px-4 py-2.5">Last reason</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const h = HEALTH[r.health] || HEALTH.unknown;
                  const Icon = h.icon;
                  return (
                    <tr key={r.id} data-testid={`target-row-${r.id}`} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                      <td className="px-4 py-2.5 font-mono text-slate-200 max-w-[160px] truncate">{r.title}</td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] border ${h.cls}`}>
                          <Icon size={12} /> {h.label}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-center text-indigo-400">{r.success}</td>
                      <td className="px-4 py-2.5 text-center text-rose-400">{r.failed}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-500 max-w-[200px] truncate">{r.last_error || "—"}</td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          data-testid={`target-remove-${r.id}`}
                          onClick={() => removeOne(r.id)}
                          className="text-slate-500 hover:text-rose-400"
                          title="Remove from campaign"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

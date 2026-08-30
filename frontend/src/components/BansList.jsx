import { useState } from "react";
import { toast } from "sonner";
import { ShieldAlert, Loader2 } from "lucide-react";
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

export const BansList = ({ campaign, bannedCount }) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [bans, setBans] = useState([]);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.campaignBans(campaign.id);
      setBans(data);
    } catch {
      toast.error("Failed to load bans");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) load(); }}>
      <DialogTrigger asChild>
        <button className="text-left w-full hover:bg-slate-800/50 p-1 -m-1 rounded transition-colors group">
          <p className="text-[10px] font-mono uppercase text-slate-500 group-hover:text-amber-400 transition-colors">Bans</p>
          <p className="text-sm font-semibold text-amber-400 group-hover:text-amber-300 transition-colors cursor-pointer">{bannedCount || 0}</p>
        </button>
      </DialogTrigger>
      <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-lg max-h-[85vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            <ShieldAlert size={18} className="text-amber-400" /> Banned Pairs — {campaign.name}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            These (account, group) pairs got a ban error during this run. They will be skipped for the rest of this campaign's cycles.
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-y-auto rounded-lg border border-slate-800 flex-1 min-h-[300px]">
          {loading ? (
            <div className="p-10 text-center text-slate-500"><Loader2 className="animate-spin mx-auto" /></div>
          ) : bans.length === 0 ? (
            <div className="p-10 text-center text-slate-500 text-sm">No bans recorded in memory yet.</div>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-900">
                <tr className="text-[11px] font-mono uppercase text-slate-500 border-b border-slate-800">
                  <th className="px-4 py-2.5">Account ID</th>
                  <th className="px-4 py-2.5">Group ID</th>
                </tr>
              </thead>
              <tbody>
                {bans.map((b, i) => (
                  <tr key={i} className="border-b border-slate-800/60 hover:bg-slate-800/30">
                    <td className="px-4 py-2.5 font-mono text-slate-200">{b.account_id}</td>
                    <td className="px-4 py-2.5 font-mono text-slate-200">{b.group_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

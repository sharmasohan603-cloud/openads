import { useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Shield, Loader2, Upload, Trash2, Zap, Link2, ServerCog, CheckCircle2 } from "lucide-react";
import { Button } from "./ui/button";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { api } from "../api";

export const ProxyManager = ({ proxies, coverage, accountGroups = [], onRefresh }) => {
  const [text, setText] = useState("");
  const [ptype, setPtype] = useState("socks5");
  const [loading, setLoading] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [testing, setTesting] = useState(false);
  const [assignBatch, setAssignBatch] = useState("all");

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const content = await file.text();
    setText(content);
    toast.success(`Loaded ${file.name}`);
  };

  const load = async () => {
    if (!text.trim()) return toast.error("Paste or upload a proxy list first");
    setLoading(true);
    try {
      const res = await api.loadProxies({ text, proxy_type: ptype });
      toast.success(`Added ${res.added} proxies (${res.skipped} skipped) — ${res.total} total`);
      setText("");
      onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load proxies");
    } finally {
      setLoading(false);
    }
  };

  const testFirst = async () => {
    if (proxies.length === 0) return toast.error("No proxies to test");
    setTesting(true);
    const p = proxies[0];
    try {
      await api.testStoredProxy(p.id);
      toast.success(`Proxy ${p.label} reaches Telegram ✓`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Proxy test failed");
    } finally {
      setTesting(false);
    }
  };

  const assign = async () => {
    setAssigning(true);
    try {
      const res = await api.assignProxies({ batch_id: assignBatch === "all" ? null : assignBatch });
      toast.success(`Assigned proxies to ${res.assigned} accounts (rotating ${res.proxies_used})`);
      onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Assign failed");
    } finally {
      setAssigning(false);
    }
  };

  const unassign = async () => {
    try {
      const res = await api.unassignProxies({ batch_id: assignBatch === "all" ? null : assignBatch });
      toast.info(`Removed proxies from ${res.unassigned} accounts`);
      onRefresh();
    } catch {
      toast.error("Failed to remove proxies");
    }
  };

  const clearAll = async () => {
    try {
      await api.clearProxies();
      toast.success("Proxy list cleared");
      onRefresh();
    } catch {
      toast.error("Failed to clear");
    }
  };

  const pct = coverage?.total_accounts
    ? Math.round((coverage.accounts_with_proxy / coverage.total_accounts) * 100)
    : 0;

  return (
    <section data-testid="proxy-manager-section" className="space-y-6">
      <div>
        <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white">Proxies</h2>
        <p className="text-sm text-slate-400 mt-1">
          Give accounts their own IPs to avoid mass-ban from running many sessions on one server IP.
        </p>
      </div>

      {/* coverage banner */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-5">
          <p className="text-xs font-mono uppercase text-slate-500">Proxies Loaded</p>
          <p className="mt-2 font-display text-3xl font-extrabold text-white">{coverage?.proxy_count ?? proxies.length}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-5">
          <p className="text-xs font-mono uppercase text-slate-500">Accounts Covered</p>
          <p className="mt-2 font-display text-3xl font-extrabold text-white">
            {coverage?.accounts_with_proxy ?? 0}<span className="text-lg text-slate-500">/{coverage?.total_accounts ?? 0}</span>
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-5">
          <p className="text-xs font-mono uppercase text-slate-500">Coverage</p>
          <p className="mt-2 font-display text-3xl font-extrabold text-indigo-400">{pct}%</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Load */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-6 space-y-4">
          <div className="flex items-center gap-2">
            <Upload className="text-indigo-400" size={18} />
            <h3 className="font-semibold text-white">Load Proxy List</h3>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-slate-300">Type</Label>
              <Select value={ptype} onValueChange={setPtype}>
                <SelectTrigger data-testid="proxy-type-select" className="bg-slate-950 border-slate-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-slate-900 border-slate-700 text-slate-100">
                  <SelectItem value="socks5">SOCKS5</SelectItem>
                  <SelectItem value="socks4">SOCKS4</SelectItem>
                  <SelectItem value="http">HTTP</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-slate-300">Or upload .txt</Label>
              <input
                data-testid="proxy-file-input"
                type="file"
                accept=".txt"
                onChange={onFile}
                className="block w-full text-xs text-slate-400 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-slate-700 file:text-white file:cursor-pointer"
              />
            </div>
          </div>
          <Textarea
            data-testid="proxy-textarea"
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"One per line:\nuser:pass@host:port\nhost:port\nhost:port:user:pass"}
            className="bg-slate-950 border-slate-700 font-mono text-xs"
          />
          <div className="flex gap-2">
            <Button data-testid="proxy-load-button" onClick={load} disabled={loading} className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2 flex-1">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />} Load Proxies
            </Button>
          </div>
        </div>

        {/* Assign */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/90 p-6 space-y-4">
          <div className="flex items-center gap-2">
            <ServerCog className="text-indigo-400" size={18} />
            <h3 className="font-semibold text-white">Assign to Accounts</h3>
          </div>
          <p className="text-sm text-slate-400">Proxies are rotated round-robin across the chosen accounts. Assigning reconnects them through the proxy.</p>
          <div className="space-y-1.5">
            <Label className="text-slate-300">Target Section</Label>
            <Select value={assignBatch} onValueChange={setAssignBatch}>
              <SelectTrigger data-testid="proxy-assign-batch-select" className="bg-slate-950 border-slate-700">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-900 border-slate-700 text-slate-100">
                <SelectItem value="all">All accounts ({coverage?.total_accounts ?? 0})</SelectItem>
                {accountGroups.map((g) => (
                  <SelectItem key={g.batch_id} value={g.batch_id}>{g.batch_name} ({g.count})</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button data-testid="proxy-assign-button" onClick={assign} disabled={assigning || proxies.length === 0} className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2">
              {assigning ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />} Assign
            </Button>
            <Button data-testid="proxy-test-button" onClick={testFirst} disabled={testing || proxies.length === 0} variant="outline" className="border-slate-700 bg-slate-950 hover:bg-slate-800 text-slate-200 gap-2">
              {testing ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />} Test First
            </Button>
            <Button data-testid="proxy-unassign-button" onClick={unassign} variant="ghost" className="text-amber-400 hover:text-amber-300 hover:bg-amber-500/10 gap-2">
              Remove
            </Button>
          </div>
        </div>
      </div>

      {/* Proxy list */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/90 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Shield className="text-indigo-400" size={16} />
            <h3 className="font-semibold text-white text-sm">Loaded Proxies ({proxies.length})</h3>
          </div>
          {proxies.length > 0 && (
            <Button data-testid="proxy-clear-button" onClick={clearAll} variant="ghost" size="sm" className="text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 gap-2">
              <Trash2 size={14} /> Clear All
            </Button>
          )}
        </div>
        {proxies.length === 0 ? (
          <div className="p-12 text-center">
            <Shield className="mx-auto text-slate-700" size={36} />
            <p className="mt-3 text-slate-500 text-sm">No proxies loaded yet.</p>
          </div>
        ) : (
          <div className="max-h-[360px] overflow-y-auto divide-y divide-slate-800/60">
            {proxies.map((p, i) => (
              <motion.div
                key={p.id}
                data-testid={`proxy-row-${p.id}`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.2, delay: Math.min(i * 0.01, 0.3) }}
                className="flex items-center justify-between px-5 py-3 hover:bg-slate-800/30"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-slate-800 text-indigo-300">{p.proxy_type}</span>
                  <span className="font-mono text-sm text-slate-200 truncate">{p.label}</span>
                  {p.username && <span className="font-mono text-xs text-slate-500 truncate">· {p.username}</span>}
                </div>
                <button data-testid={`proxy-delete-${p.id}`} onClick={async () => { await api.deleteProxy(p.id); onRefresh(); }} className="text-slate-500 hover:text-rose-400">
                  <Trash2 size={14} />
                </button>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
};

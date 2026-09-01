import { useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Plus, Trash2, UserCircle2, Loader2, KeyRound, ShieldCheck, Upload, FileArchive, Shield, ShieldOff, FolderPlus, FolderOpen } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger,
} from "./ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { api } from "../api";

const empty = { name: "" };

export const AccountsManager = ({ accounts, accountGroups = [], onRefresh }) => {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [file, setFile] = useState(null);
  const [saving, setSaving] = useState(false);
  const [selectedBatch, setSelectedBatch] = useState("new");

  const submit = async () => {
    const isNew = selectedBatch === "new";
    if (isNew && !form.name) {
      toast.error("Enter a section name for the new folder");
      return;
    }

    if (!file) {
      toast.error("Please select a .session file or a .zip");
      return;
    }
    setSaving(true);
    try {
      const fd = new FormData();
      fd.append("name", isNew ? form.name : "");

      fd.append("file", file);
      if (!isNew) {
        fd.append("batch_id", selectedBatch);
      }
      const res = await api.uploadAccount(fd);
      const n = res.created?.length || 0;
      const folderName = res.batch_name || form.name;
      toast.success(`${n} account${n > 1 ? "s" : ""} added to "${folderName}"`);
      if (res.errors?.length) {
        toast.warning(`${res.errors.length} session(s) failed to load`);
      }
      setForm(empty);
      setFile(null);
      setSelectedBatch("new");
      setOpen(false);
      onRefresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to add account");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id) => {
    try {
      await api.deleteAccount(id);
      toast.success("Account removed");
      onRefresh();
    } catch {
      toast.error("Failed to remove account");
    }
  };

  const selectedGroup = accountGroups.find((g) => g.batch_id === selectedBatch);

  return (
    <section data-testid="accounts-manager-section">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white">Telegram Accounts</h2>
          <p className="text-sm text-slate-400 mt-1">Upload Telethon <span className="font-mono text-indigo-400">.session</span> files (or a .zip of them).</p>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button
              data-testid="account-add-button"
              className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2 rounded-lg"
            >
              <Plus size={16} /> Add Account
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-lg">
            <DialogHeader>
              <DialogTitle className="font-display flex items-center gap-2">
                <KeyRound size={18} className="text-indigo-400" /> Connect Telegram Account
              </DialogTitle>
              <DialogDescription className="text-slate-400">
                Upload a Telethon <span className="font-mono">.session</span> file or a <span className="font-mono">.zip</span> of them. Pick an existing folder or create a new one.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-2">
              {/* --- Folder / Section Picker --- */}
              <div className="space-y-1.5">
                <Label className="text-slate-300 flex items-center gap-2">
                  <FolderOpen size={14} /> Add to Section
                </Label>
                <Select value={selectedBatch} onValueChange={setSelectedBatch}>
                  <SelectTrigger data-testid="batch-select-trigger" className="bg-slate-950 border-slate-700 text-slate-100">
                    <SelectValue placeholder="Choose a folder..." />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-900 border-slate-700 text-slate-100">
                    <SelectItem value="new" data-testid="batch-opt-new">
                      <span className="flex items-center gap-2">
                        <FolderPlus size={14} className="text-indigo-400" /> Create New Section
                      </span>
                    </SelectItem>
                    {accountGroups.map((g) => (
                      <SelectItem key={g.batch_id} value={g.batch_id} data-testid={`batch-opt-${g.batch_id}`}>
                        {g.batch_name} ({g.count} accounts)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedBatch !== "new" && selectedGroup && (
                  <p className="text-[11px] text-indigo-400/70 flex items-center gap-1.5">
                    <FolderOpen size={11} /> Sessions will be added to &quot;{selectedGroup.batch_name}&quot; ({selectedGroup.count} existing)
                  </p>
                )}
              </div>

              {/* New section name — only shown when creating new */}
              {selectedBatch === "new" && (
                <div className="space-y-1.5">
                  <Label className="text-slate-300">New Section Name</Label>
                  <Input
                    data-testid="account-name-input"
                    placeholder="e.g. Ryker, Alpha Batch, VIP"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="bg-slate-950 border-slate-700 text-slate-100"
                  />
                  <p className="text-[11px] text-slate-500">This creates a new folder. You can add more sessions to it later.</p>
                </div>
              )}


              <div className="space-y-1.5">
                <Label className="text-slate-300">Session File (.session or .zip)</Label>
                <label
                  htmlFor="session-file"
                  className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-700 bg-slate-950 px-4 py-6 cursor-pointer hover:border-indigo-500/40 transition-colors"
                >
                  {file ? (
                    <>
                      <FileArchive className="text-indigo-400" size={26} />
                      <span className="text-sm text-slate-200 font-mono break-all text-center">{file.name}</span>
                      <span className="text-[11px] text-slate-500">Click to choose a different file</span>
                    </>
                  ) : (
                    <>
                      <Upload className="text-slate-500" size={26} />
                      <span className="text-sm text-slate-400">Click to select a .session or .zip file</span>
                      <span className="text-[11px] text-slate-600">A .zip may contain multiple sessions (bulk add)</span>
                    </>
                  )}
                </label>
                <input
                  id="session-file"
                  data-testid="session-file-input"
                  type="file"
                  accept=".session,.zip"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button
                data-testid="account-submit-button"
                onClick={submit}
                disabled={saving}
                className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2 w-full sm:w-auto"
              >
                {saving ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                {saving ? "Loading session..." : selectedBatch === "new" ? "Upload & Connect" : `Add to ${selectedGroup?.batch_name || "Folder"}`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {accounts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/40 p-12 text-center">
          <UserCircle2 className="mx-auto text-slate-700" size={40} />
          <p className="mt-3 text-slate-400 text-sm">No accounts connected yet.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {accounts.map((a, i) => (
            <motion.div
              key={a.id}
              data-testid={`account-card-${a.id}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25, delay: i * 0.05 }}
              className="rounded-xl border border-slate-800 bg-slate-900/90 p-5 hover:border-indigo-500/30 transition-all duration-200"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-11 w-11 rounded-full bg-gradient-to-br from-indigo-500/30 to-indigo-500/30 flex items-center justify-center border border-slate-700">
                    <UserCircle2 className="text-indigo-300" size={22} />
                  </div>
                  <div>
                    <p className="font-semibold text-white leading-tight">{a.name}</p>
                    <p className="text-xs text-slate-500">{a.display_name}</p>
                  </div>
                </div>
                <span
                  data-testid={`account-status-badge-${a.id}`}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium ${
                    a.status === "connected"
                      ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                      : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                  }`}
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-current" /> {a.status}
                </span>
              </div>
              <div className="mt-4 space-y-1.5 text-xs font-mono text-slate-400">
                <p>@{a.username || "n/a"}</p>
                <p>{a.phone || "hidden number"}</p>
                {a.batch_name && (
                  <p className="flex items-center gap-1.5 text-slate-500">
                    <FolderOpen size={11} /> {a.batch_name}
                  </p>
                )}
                {a.proxy_label ? (
                  <p className="flex items-center gap-1.5 text-indigo-400/80"><Shield size={11} /> {a.proxy_label}</p>
                ) : (
                  <p className="flex items-center gap-1.5 text-slate-600"><ShieldOff size={11} /> direct (no proxy)</p>
                )}
              </div>
              <Button
                data-testid={`account-delete-${a.id}`}
                variant="ghost"
                size="sm"
                onClick={() => remove(a.id)}
                className="mt-4 text-rose-400 hover:text-rose-300 hover:bg-rose-500/10 gap-2 px-2"
              >
                <Trash2 size={14} /> Remove
              </Button>
            </motion.div>
          ))}
        </div>
      )}
    </section>
  );
};

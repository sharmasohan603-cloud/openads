import { useState, useEffect } from "react";
import { toast } from "sonner";
import {
  Plus,
  Loader2,
  Type,
  Image as ImageIcon,
  Forward,
  Users,
  Clock,
  Send,
  Layers,
  Gauge,
  Pencil,
} from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Slider } from "./ui/slider";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from "./ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import { api, API } from "../api";

const MSG_TYPES = [
  { key: "text", label: "Text", icon: Type },
  { key: "media", label: "Text + Media", icon: ImageIcon },
  { key: "forward", label: "Forward Post", icon: Forward },
];

export const CampaignCreator = ({ accountCount, accountGroups = [], onCreated, editCampaign = null }) => {
  const isEdit = !!editCampaign;
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [msgType, setMsgType] = useState("text");
  const [text, setText] = useState("");
  const [forwardLink, setForwardLink] = useState("");
  const [interval, setIntervalSec] = useState(60);
  const [groupsText, setGroupsText] = useState("");
  const [media, setMedia] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [batchId, setBatchId] = useState("all");
  const [concurrency, setConcurrency] = useState(25);

  const reset = () => {
    setName(""); setMsgType("text"); setText(""); setForwardLink("");
    setIntervalSec(60); setGroupsText(""); setMedia(null); setBatchId("all"); setConcurrency(25);
  };

  const prefill = () => {
    const c = editCampaign;
    setName(c.name || "");
    setMsgType(c.message_type || "text");
    setText(c.text || "");
    setForwardLink(c.forward_link || "");
    setIntervalSec(c.interval_seconds ?? 60);
    setGroupsText((c.target_groups || []).map((g) => g.id).join("\n"));
    setBatchId(c.account_batch_id || "all");
    setConcurrency(c.concurrency ?? 25);
    setMedia(c.media_path ? { media_path: c.media_path, media_url: c.media_url, filename: c.media_filename } : null);
  };

  useEffect(() => {
    if (open && isEdit) prefill();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const parsedGroups = groupsText
    .split(/[\n,]/)
    .map((g) => g.trim())
    .filter(Boolean);

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await api.upload(fd);
      setMedia(res);
      toast.success("Media uploaded");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    if (!name) return toast.error("Campaign name required");
    if (parsedGroups.length === 0) return toast.error("Add at least one group");
    if (msgType === "text" && !text) return toast.error("Enter ad text");
    if (msgType === "media" && !media) return toast.error("Upload media");
    if (msgType === "forward" && !forwardLink) return toast.error("Enter a forward link");

    setSaving(true);
    try {
      const payload = {
        name,
        message_type: msgType,
        text,
        media_path: media?.media_path || null,
        media_url: media?.media_url || null,
        media_filename: media?.filename || null,
        forward_link: forwardLink || null,
        target_groups: parsedGroups,
        interval_seconds: parseInt(interval, 10) || 60,
        account_batch_id: batchId === "all" ? null : batchId,
        concurrency: concurrency,
      };
      if (isEdit) {
        await api.updateCampaign(editCampaign.id, payload);
        toast.success("Campaign updated — changes apply on the next cycle");
      } else {
        await api.createCampaign(payload);
        toast.success("Campaign created");
        reset();
      }
      setOpen(false);
      onCreated();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to save campaign");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o && !isEdit) reset(); }}>
      <DialogTrigger asChild>
        {isEdit ? (
          <Button
            data-testid={`campaign-edit-open-${editCampaign.id}`}
            variant="ghost"
            size="sm"
            className="text-slate-300 hover:text-indigo-300 hover:bg-indigo-500/10 h-8 gap-1.5"
          >
            <Pencil size={14} /> Edit
          </Button>
        ) : (
          <Button
            data-testid="campaign-create-open"
            className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2 rounded-lg"
          >
            <Plus size={16} /> New Campaign
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="bg-slate-900 border-slate-800 text-slate-100 max-w-3xl max-h-[88vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-display flex items-center gap-2">
            {isEdit ? <Pencil size={18} className="text-indigo-400" /> : <Send size={18} className="text-indigo-400" />}
            {isEdit ? "Edit Campaign" : "Create Ad Campaign"}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            {isEdit
              ? "Edit an ongoing campaign — changes take effect on the next broadcast cycle."
              : "Paste your groups, set the interval — all loaded accounts auto-rotate to deliver."}
          </DialogDescription>
        </DialogHeader>

        {/* account pool banner */}
        <div
          data-testid="account-pool-banner"
          className="flex items-center gap-3 rounded-lg border border-indigo-500/25 bg-indigo-500/10 px-4 py-3"
        >
          <Layers className="text-indigo-400 flex-shrink-0" size={20} />
          <p className="text-sm text-indigo-100">
            All target groups are sent <span className="font-semibold">in parallel</span> each cycle, auto-rotated across
            the accounts in the chosen section — then it waits your interval and repeats. Fast even with many groups.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 py-2">
          {/* Left: config */}
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label className="text-slate-300">Campaign Name</Label>
              <Input
                data-testid="campaign-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Summer Promo"
                className="bg-slate-950 border-slate-700"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-slate-300">Account Section (which upload sends this)</Label>
              <Select value={batchId} onValueChange={setBatchId}>
                <SelectTrigger data-testid="campaign-batch-select" className="bg-slate-950 border-slate-700">
                  <SelectValue placeholder="Choose account section" />
                </SelectTrigger>
                <SelectContent className="bg-slate-900 border-slate-700 text-slate-100">
                  <SelectItem value="all" data-testid="batch-opt-all">All accounts ({accountCount})</SelectItem>
                  {accountGroups.map((g) => (
                    <SelectItem key={g.batch_id} value={g.batch_id} data-testid={`batch-opt-${g.batch_id}`}>
                      {g.batch_name} ({g.count})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-[11px] text-slate-500">Each uploaded zip/file is its own section — pick which one runs this campaign.</p>
            </div>

            <div className="space-y-1.5">
              <Label className="text-slate-300">Message Type</Label>
              <div className="grid grid-cols-3 gap-2">
                {MSG_TYPES.map((t) => {
                  const Icon = t.icon;
                  const on = msgType === t.key;
                  return (
                    <button
                      key={t.key}
                      data-testid={`msgtype-${t.key}`}
                      onClick={() => setMsgType(t.key)}
                      className={`flex flex-col items-center gap-1.5 py-3 rounded-lg border text-xs transition-all duration-200 ${
                        on
                          ? "border-indigo-500/40 bg-indigo-500/10 text-indigo-300"
                          : "border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-600"
                      }`}
                    >
                      <Icon size={18} /> {t.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {msgType !== "forward" && (
              <div className="space-y-1.5">
                <Label className="text-slate-300">Ad Text {msgType === "media" && "(caption)"}</Label>
                <Textarea
                  data-testid="campaign-text-input"
                  rows={4}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="Write your ad message..."
                  className="bg-slate-950 border-slate-700"
                />
              </div>
            )}

            {msgType === "media" && (
              <div className="space-y-1.5">
                <Label className="text-slate-300">Media File</Label>
                <input
                  data-testid="campaign-media-input"
                  type="file"
                  accept="image/*,video/*"
                  onChange={onUpload}
                  className="block w-full text-xs text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-indigo-600 file:text-white file:cursor-pointer"
                />
                {uploading && <p className="text-xs text-slate-500 flex items-center gap-2"><Loader2 size={12} className="animate-spin" /> uploading...</p>}
                {media && (
                  <img
                    src={`${API}/uploads/${media.media_path}`}
                    alt="preview"
                    className="mt-2 rounded-lg max-h-40 border border-slate-700 object-cover"
                  />
                )}
              </div>
            )}

            {msgType === "forward" && (
              <div className="space-y-1.5">
                <Label className="text-slate-300">Message Link to Forward</Label>
                <Input
                  data-testid="campaign-forward-input"
                  value={forwardLink}
                  onChange={(e) => setForwardLink(e.target.value)}
                  placeholder="https://t.me/yourchannel/123"
                  className="bg-slate-950 border-slate-700 font-mono text-xs"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <Label className="text-slate-300 flex items-center gap-2"><Clock size={14} /> Repeat Cycle Every (seconds)</Label>
              <Input
                data-testid="campaign-interval-input"
                type="number"
                min={1}
                value={interval}
                onChange={(e) => setIntervalSec(e.target.value)}
                className="bg-slate-950 border-slate-700 font-mono"
              />
              <p className="text-[11px] text-slate-500">All groups blast in parallel, then it waits this long and repeats. Default 60s.</p>
            </div>

            <div className="space-y-2">
              <Label className="text-slate-300 flex items-center justify-between">
                <span className="flex items-center gap-2"><Gauge size={14} /> Parallel Sends (speed)</span>
                <span className="font-mono text-indigo-400" data-testid="concurrency-value">{concurrency}</span>
              </Label>
              <Slider
                data-testid="campaign-concurrency-slider"
                min={1}
                max={100}
                step={1}
                value={[concurrency]}
                onValueChange={(v) => setConcurrency(v[0])}
                className="py-1"
              />
              <p className="text-[11px] text-slate-500">How many groups are messaged at the same time. Higher = faster, lower = safer against flood limits.</p>
            </div>
          </div>

          {/* Right: groups list */}
          <div className="space-y-2">
            <Label className="text-slate-300 flex items-center gap-2"><Users size={15} /> Target Groups</Label>
            <Textarea
              data-testid="campaign-groups-input"
              rows={14}
              value={groupsText}
              onChange={(e) => setGroupsText(e.target.value)}
              placeholder={"One group per line, e.g.\n@mygroup\nhttps://t.me/anothergroup\nhttps://t.me/+invitehash\n-1001234567890"}
              className="bg-slate-950 border-slate-700 font-mono text-xs h-full"
            />
            <p className="text-xs text-indigo-400 font-mono">{parsedGroups.length} groups</p>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Accept @usernames, t.me links, invite links, or numeric IDs. Accounts auto-join public groups before sending.
              of each group will be picked automatically.
            </p>
          </div>
        </div>

        <Button
          data-testid="campaign-submit-button"
          onClick={submit}
          disabled={saving}
          className="bg-indigo-600 hover:bg-indigo-500 text-white gap-2 w-full mt-2"
        >
          {saving ? <Loader2 size={16} className="animate-spin" /> : (isEdit ? <Pencil size={16} /> : <Plus size={16} />)}
          {isEdit ? "Save Changes" : "Create Campaign"}
        </Button>
      </DialogContent>
    </Dialog>
  );
};

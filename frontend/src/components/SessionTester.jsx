import { useState } from "react";
import { toast } from "sonner";
import { Zap, Loader2, Send } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
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

export const SessionTester = ({ accounts }) => {
  const [accountId, setAccountId] = useState("");
  const [target, setTarget] = useState("me");
  const [text, setText] = useState("✅ OpenAds test message");
  const [sending, setSending] = useState(false);

  const send = async () => {
    if (!accountId) return toast.error("Select an account");
    setSending(true);
    try {
      await api.sessionTest({ account_id: accountId, target, text });
      toast.success("Test message sent!");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Test failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <section data-testid="session-tester-widget">
      <div className="mb-5">
        <h2 className="font-display text-xl sm:text-2xl font-bold tracking-tight text-white">Session Tester</h2>
        <p className="text-sm text-slate-400 mt-1">Verify a session by sending a quick test message.</p>
      </div>

      <div className="max-w-xl rounded-xl border border-slate-800 bg-slate-900/90 p-6 space-y-4">
        <div className="flex items-center gap-3 pb-2">
          <div className="h-10 w-10 rounded-lg bg-amber-500/15 flex items-center justify-center">
            <Zap className="text-amber-400" size={20} />
          </div>
          <p className="text-sm text-slate-400">Sends to <span className="font-mono text-slate-200">me</span> (Saved Messages) by default, or any group id / @username.</p>
        </div>

        <div className="space-y-1.5">
          <Label className="text-slate-300">Account</Label>
          <Select value={accountId} onValueChange={setAccountId}>
            <SelectTrigger data-testid="tester-account-select" className="bg-slate-950 border-slate-700">
              <SelectValue placeholder="Choose account" />
            </SelectTrigger>
            <SelectContent className="bg-slate-900 border-slate-700 text-slate-100">
              {accounts.map((a) => (
                <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-slate-300">Target (me / @username / group id)</Label>
          <Input
            data-testid="tester-target-input"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            className="bg-slate-950 border-slate-700 font-mono"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-slate-300">Message</Label>
          <Textarea
            data-testid="tester-text-input"
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="bg-slate-950 border-slate-700"
          />
        </div>

        <Button
          data-testid="tester-send-button"
          onClick={send}
          disabled={sending}
          className="bg-amber-600 hover:bg-amber-500 text-white gap-2 w-full"
        >
          {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
          Send Test Message
        </Button>
      </div>
    </section>
  );
};

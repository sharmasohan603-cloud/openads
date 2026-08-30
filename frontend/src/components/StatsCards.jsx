import { motion } from "framer-motion";
import { Users, Megaphone, CheckCircle2, Send } from "lucide-react";

const CARDS = [
  { key: "total-accounts", label: "Connected Accounts", field: "total_accounts", icon: Users, color: "text-indigo-400", ring: "rgba(99,102,241,0.15)" },
  { key: "active-campaigns", label: "Active Campaigns", field: "active_campaigns", icon: Megaphone, color: "text-indigo-400", ring: "rgba(99,102,241,0.15)" },
  { key: "total-sent", label: "Messages Sent", field: "total_sent", icon: Send, color: "text-indigo-400", ring: "rgba(99,102,241,0.15)" },
  { key: "success-rate", label: "Success Rate", field: "success_rate", icon: CheckCircle2, color: "text-amber-400", ring: "rgba(245,158,11,0.15)", suffix: "%" },
];

export const StatsCards = ({ stats }) => {
  return (
    <div data-testid="stats-overview-cards" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
      {CARDS.map((c, i) => {
        const Icon = c.icon;
        const val = stats?.[c.field];
        return (
          <motion.div
            key={c.key}
            data-testid={`stats-card-${c.key}`}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: i * 0.06, ease: "easeOut" }}
            className="rounded-xl border border-slate-800 bg-slate-900/90 p-5 transition-all duration-200 hover:border-indigo-500/30 hover:-translate-y-0.5"
            style={{ boxShadow: `0 0 0 1px transparent` }}
          >
            <div className="flex items-start justify-between">
              <p className="text-xs font-mono uppercase tracking-wider text-slate-500">{c.label}</p>
              <div className="h-9 w-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: c.ring }}>
                <Icon className={`h-4.5 w-4.5 ${c.color}`} size={18} />
              </div>
            </div>
            <p className="mt-4 font-display text-3xl font-extrabold text-white tracking-tight">
              {val === undefined ? "—" : val}
              {c.suffix && val !== undefined ? <span className="text-xl text-slate-500">{c.suffix}</span> : null}
            </p>
          </motion.div>
        );
      })}
    </div>
  );
};

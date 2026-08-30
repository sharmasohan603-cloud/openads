import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Lock, User } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "@/lib/auth";
import { LOGIN } from "@/constants/testIds";
import { OpenAdsLogo } from "@/components/OpenAdsLogo";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const result = await login(username, password);
      if (result.ok) {
        toast.success("Welcome back to OpenAds.");
        navigate("/", { replace: true });
      } else {
        toast.error(result.error || "Invalid credentials");
      }
    } catch {
      toast.error("Login failed — check your connection");
    }

    setLoading(false);
  };

  return (
    <div className="min-h-screen w-full bg-[#0B0F19] text-slate-100 tp-grain flex items-center justify-center p-6">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-32 -left-32 h-96 w-96 rounded-full bg-indigo-500/10 blur-3xl" />
        <div className="absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-blue-500/10 blur-3xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="relative w-full max-w-md"
      >
        <div className="rounded-2xl border border-slate-800/80 bg-[#090D16]/90 backdrop-blur-xl shadow-[0_0_40px_rgba(0,0,0,0.45)] p-8">
          <div className="flex flex-col items-center text-center mb-8">
            <OpenAdsLogo size="lg" vertical />
            <p className="text-sm text-slate-400 mt-5">Admin sign in to access the OpenAds command center</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="username" className="text-slate-300 text-sm">
                Username
              </Label>
              <div className="relative">
                <User className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                <Input
                  id="username"
                  data-testid="login-username-input"
                  type="text"
                  autoComplete="username"
                  placeholder="Enter username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="pl-10 h-11 bg-slate-900/60 border-slate-700/80 text-white placeholder:text-slate-500 focus-visible:ring-indigo-500/40 focus-visible:border-indigo-500/50"
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="password" className="text-slate-300 text-sm">
                Password
              </Label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                <Input
                  id="password"
                  data-testid={LOGIN.passwordInput}
                  type="password"
                  autoComplete="current-password"
                  placeholder="Enter password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-10 h-11 bg-slate-900/60 border-slate-700/80 text-white placeholder:text-slate-500 focus-visible:ring-indigo-500/40 focus-visible:border-indigo-500/50"
                  required
                />
              </div>
            </div>

            <Button
              type="submit"
              data-testid={LOGIN.submitButton}
              disabled={loading}
              className="w-full h-11 mt-2 bg-gradient-to-r from-indigo-500 to-blue-500 hover:from-indigo-400 hover:to-blue-400 text-black font-semibold shadow-[0_0_20px_rgba(99,102,241,0.25)] border-0"
            >
              {loading ? "Signing in..." : "Sign In to OpenAds"}
            </Button>
          </form>

          <p className="text-center text-xs text-slate-500 mt-6 font-mono">
            © OpenAds · Authorized personnel only
          </p>
        </div>
      </motion.div>
    </div>
  );
}

export function OpenAdsLogo({ size = "md", showTagline = true, vertical = false, className = "" }) {
  const sizes = {
    sm: { box: "h-9 w-9", img: "h-7 w-7", title: "text-base", tagline: "text-[9px]" },
    md: { box: "h-10 w-10", img: "h-8 w-8", title: "text-lg", tagline: "text-[10px]" },
    lg: { box: "h-14 w-14", img: "h-11 w-11", title: "text-2xl", tagline: "text-[11px]" },
  };
  const s = sizes[size] || sizes.md;

  return (
    <div className={`flex ${vertical ? "flex-col items-center text-center gap-3" : "items-center gap-3"} ${className}`}>
      <div
        className={`${s.box} rounded-xl flex items-center justify-center bg-black border border-indigo-500/20 shadow-[0_0_20px_rgba(99,102,241,0.15)] overflow-hidden flex-shrink-0`}
      >
        <img
          src={`${process.env.PUBLIC_URL}/openads.png`}
          alt="OpenAds logo"
          className={`${s.img} object-contain`}
        />
      </div>
      {(showTagline || size !== "sm") && (
        <div className={`leading-tight ${vertical ? "text-center" : ""}`}>
          <p className={`font-display font-extrabold tracking-tight text-white ${s.title}`}>OpenAds</p>
          {showTagline && (
            <p className={`font-mono uppercase tracking-widest text-indigo-400/80 ${s.tagline}`}>
              Ad Platform
            </p>
          )}
        </div>
      )}
    </div>
  );
}

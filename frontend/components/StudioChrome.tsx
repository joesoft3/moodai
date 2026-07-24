import Link from "next/link";

function toneCls(tone: "default" | "accent" | "warn") {
  if (tone === "accent") return "border-accent/30 bg-accent/10 text-accent";
  if (tone === "warn") return "border-yellow-500/30 bg-yellow-500/10 text-yellow-300";
  return "border-line bg-white/5 text-gray-400";
}

export function StudioActionLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-xl border border-line bg-white/5 px-3 py-2 text-xs text-gray-300 hover:border-accent/40 hover:bg-white/10 transition"
    >
      {children}
    </Link>
  );
}

export function StudioActionButton({ onClick, children, tone = "default" }: {
  onClick: () => void;
  children: React.ReactNode;
  tone?: "default" | "accent" | "warn";
}) {
  const cls =
    tone === "accent"
      ? "border-accent/30 bg-accent/10 text-accent hover:bg-accent/20"
      : tone === "warn"
        ? "border-red-400/30 bg-red-400/10 text-red-300 hover:bg-red-400/20"
        : "border-line bg-white/5 text-gray-300 hover:border-accent/40 hover:bg-white/10";
  return (
    <button onClick={onClick} className={`rounded-xl border px-3 py-2 text-xs transition ${cls}`}>
      {children}
    </button>
  );
}

export function StudioHero({
  icon,
  title,
  subtitle,
  actions,
  stats,
}: {
  icon?: React.ReactNode;
  title: string;
  subtitle: string;
  actions?: React.ReactNode;
  stats?: { label: string; value: React.ReactNode }[];
}) {
  return (
    <section className="rounded-2xl border border-line bg-panel p-4 sm:p-5 space-y-4">
      <div className="flex items-start gap-3 flex-wrap">
        {icon && <div className="grid h-11 w-11 place-items-center rounded-xl bg-accent/15 text-accent shrink-0">{icon}</div>}
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold text-gray-100">{title}</h1>
          <p className="text-xs text-gray-400 mt-1">{subtitle}</p>
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {stats && stats.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
          {stats.map((item) => (
            <div key={item.label} className="rounded-xl bg-base border border-line px-3 py-3">
              <p className="text-lg font-semibold text-gray-100">{item.value}</p>
              <p className="text-[10px] text-gray-500">{item.label}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function StudioNotice({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "accent" | "warn";
}) {
  return <div className={`rounded-xl border px-3 py-2 text-xs ${toneCls(tone)}`}>{children}</div>;
}

export function StudioEmptyState({
  emoji,
  title,
  description,
  actions,
}: {
  emoji: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="text-center text-gray-600 pt-20 space-y-3">
      <div className="text-4xl">{emoji}</div>
      <p className="text-sm text-gray-300 font-medium">{title}</p>
      <p className="text-sm text-gray-500 max-w-xl mx-auto">{description}</p>
      {actions && <div className="flex justify-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

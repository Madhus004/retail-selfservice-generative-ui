// frontend/components/WelcomeCanvas.tsx
//
// Not used by the assistant panel (see components/assistant/inline/InlineWelcome.tsx)
// — retained for potential future full-page reuse (Phase 3).

import type { ReactNode } from "react";
import { CheckCircle2, Clock3, Truck } from "lucide-react";

export function WelcomeCanvas() {
  return (
    <div className="relative flex min-h-full overflow-hidden rounded-[1.5rem] bg-[#efe7dc] p-8">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_80%_10%,rgba(196,181,253,0.65),transparent_30%),radial-gradient(circle_at_15%_90%,rgba(251,207,232,0.65),transparent_30%)]" />

      <div className="relative z-10 flex max-w-4xl flex-col justify-between">
        <div>
          <p className="mb-4 text-xs font-black uppercase tracking-[0.28em] text-neutral-500">
            Generative Retail Support
          </p>
          <h2 className="text-5xl font-black tracking-[-0.06em] text-neutral-950">
            Your order answers, visually explained.
          </h2>
          <p className="mt-5 max-w-2xl text-base leading-7 text-neutral-700">
            Ask Uni for help and the workspace adapts to the task. For order
            tracking, it can show package details, item images, promise status,
            delivery proof, and next available support actions.
          </p>
        </div>

        <div className="grid max-w-4xl gap-4 md:grid-cols-3">
          <FeatureCard
            icon={<Truck size={20} />}
            title="Package-aware tracking"
            text="Show each package and compare its journey against the delivery promise."
          />
          <FeatureCard
            icon={<Clock3 size={20} />}
            title="Promise confidence"
            text="Translate events into a clear on-promise confidence score."
          />
          <FeatureCard
            icon={<CheckCircle2 size={20} />}
            title="Dynamic next action"
            text="Show refunds, coupons, delivery proof, or forms based on the use case."
          />
        </div>
      </div>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  text,
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="rounded-3xl border border-white/70 bg-white/75 p-5 shadow-sm backdrop-blur">
      <div className="mb-4 inline-flex rounded-2xl bg-black p-3 text-white">
        {icon}
      </div>
      <h3 className="font-black tracking-[-0.03em]">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-neutral-600">{text}</p>
    </div>
  );
}
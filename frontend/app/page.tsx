// frontend/app/page.tsx

import { HomePageContext } from "@/components/HomePageContext";
import { ProductGrid } from "@/components/retail/ProductGrid";

export default function Home() {
  return (
    <main className="min-h-screen bg-[#f7f3ed] text-[#111111]">
      <HomePageContext />
      <section className="mx-auto max-w-[1700px] px-8 pb-8 pt-12">
        <div className="max-w-3xl">
          <p className="mb-3 text-xs font-bold uppercase tracking-[0.28em] text-neutral-500">
            Unicorn Apparel
          </p>
          <h1 className="max-w-3xl text-5xl font-black tracking-[-0.055em] text-neutral-950 md:text-6xl">
            Clothes built for real life.
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-neutral-600">
            Browse new arrivals, check an order, or ask Uni — our AI
            self-service associate — for help any time. Open the assistant
            from the launcher in the bottom-right corner.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-[1700px] px-8 pb-16">
        <p className="mb-4 text-xs font-bold uppercase tracking-[0.28em] text-neutral-500">
          New Arrivals
        </p>

        <ProductGrid />
      </section>
    </main>
  );
}

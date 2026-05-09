// frontend/components/RetailHeader.tsx

export function RetailHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-black/10 bg-[#f7f3ed]/90 backdrop-blur">
      <div className="mx-auto flex h-20 max-w-[1700px] items-center justify-between px-8">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-black text-sm font-black text-white">
            U
          </div>
          <div>
            <p className="text-xl font-black tracking-[-0.04em]">Unicorn</p>
            <p className="text-xs font-medium uppercase tracking-[0.22em] text-neutral-500">
              D2C Apparel
            </p>
          </div>
        </div>

        <nav className="hidden items-center gap-8 text-sm font-semibold text-neutral-700 md:flex">
          <a href="#">New Arrivals</a>
          <a href="#">Women</a>
          <a href="#">Men</a>
          <a href="#">Orders</a>
          <a href="#">Help</a>
        </nav>

        <button className="rounded-full bg-black px-5 py-3 text-sm font-bold text-white shadow-sm">
          Shop Now
        </button>
      </div>
    </header>
  );
}
import Link from "next/link";
import { ArrowRight, ShieldCheck } from "lucide-react";

export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-3xl flex-col justify-center px-6 py-16">
      <div className="mb-6 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-cyan-700 text-white">
        <ShieldCheck className="h-6 w-6" aria-hidden />
      </div>
      <h1 className="text-4xl font-semibold tracking-tight text-white">
        Data Airlock Suite
      </h1>
      <p className="mt-3 max-w-xl text-lg text-slate-400">
        Pre-transformation ingestion control plane — configure property contracts,
        adjudicate blocked landings, and dry-run Gates 1–4.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link
          href="/dashboard"
          className="inline-flex w-fit items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-cyan-600"
        >
          Adjudication Queue
          <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
        <Link
          href="/properties/setup"
          className="inline-flex w-fit items-center gap-2 rounded-lg border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-200 transition hover:border-slate-500"
        >
          Configuration
        </Link>
      </div>
    </main>
  );
}

-- Allow Property Setup UI (anon key) to manage contracts/properties during
-- control-plane configuration. Tighten to authenticated-only before production.

create policy "Anon can select ingestion_contracts"
  on public.ingestion_contracts for select
  to anon
  using (true);

create policy "Anon can insert ingestion_contracts"
  on public.ingestion_contracts for insert
  to anon
  with check (true);

create policy "Anon can update ingestion_contracts"
  on public.ingestion_contracts for update
  to anon
  using (true)
  with check (true);

create policy "Anon can select properties"
  on public.properties for select
  to anon
  using (true);

create policy "Anon can insert properties"
  on public.properties for insert
  to anon
  with check (true);

create policy "Anon can update properties"
  on public.properties for update
  to anon
  using (true)
  with check (true);

create policy "Anon can select run_reports"
  on public.run_reports for select
  to anon
  using (true);

create policy "Anon can insert run_reports"
  on public.run_reports for insert
  to anon
  with check (true);

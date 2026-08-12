-- Fix PostgreSQL 22003: epoch-ms values (e.g. 1786501628757) overflow INT4.
-- Widen any millisecond / version integer columns on ingestion_contracts to BIGINT.
-- Safe no-op when columns are already BIGINT or TEXT (repo init uses TEXT version).

do $$
declare
  col record;
  sql text;
begin
  for col in
    select c.column_name, c.data_type, c.udt_name
    from information_schema.columns c
    where c.table_schema = 'public'
      and c.table_name = 'ingestion_contracts'
      and c.column_name in (
        'version',
        'contract_version',
        'created_at_ms',
        'updated_at_ms'
      )
      and (
        c.data_type = 'integer'
        or c.data_type = 'smallint'
        or c.udt_name in ('int2', 'int4')
      )
  loop
    sql := format(
      'alter table public.ingestion_contracts alter column %I type bigint using %I::bigint',
      col.column_name,
      col.column_name
    );
    execute sql;
    raise notice 'Widened ingestion_contracts.% to bigint', col.column_name;
  end loop;
end $$;

-- If a sequence backs any of these integer columns, promote it to BIGINT.
do $$
declare
  seq_reg regclass;
  col_name text;
begin
  foreach col_name in array array[
    'version',
    'contract_version',
    'created_at_ms',
    'updated_at_ms'
  ]
  loop
    select pg_get_serial_sequence('public.ingestion_contracts', col_name)
      into seq_reg;
    if seq_reg is not null then
      execute format('alter sequence %s as bigint', seq_reg);
    end if;
  end loop;
end $$;

comment on column public.ingestion_contracts.version is
  'Contract revision token. When numeric, stored as BIGINT to hold JS epoch-ms values.';

-- One feed per (property_id, feed_category).
-- Preset switches update the existing row in-place instead of inserting duplicates
-- that violate uq_property_feed when (property_id, feed_category, preset_id) collided.

-- Keep the best row per (property_id, feed_category): prefer active_contract_id, else newest.
with ranked as (
  select
    id,
    row_number() over (
      partition by property_id, feed_category
      order by
        (active_contract_id is not null) desc,
        created_at desc nulls last,
        id desc
    ) as rn
  from public.property_feeds
)
delete from public.property_feeds pf
using ranked r
where pf.id = r.id
  and r.rn > 1;

alter table public.property_feeds
  drop constraint if exists uq_property_feed;

alter table public.property_feeds
  add constraint uq_property_feed unique (property_id, feed_category);

comment on constraint uq_property_feed on public.property_feeds is
  'Exactly one feed row per property + category; system_preset/preset_id updates in place.';

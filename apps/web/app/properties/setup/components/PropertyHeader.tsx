"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { BookOpen, ChevronDown, Download, Play, Plus, Save } from "lucide-react";
import type { CustomerTree, PropertyFeed, PropertyWithFeeds } from "../types";
import { categoryOf } from "../presets";

export function PropertyTopBar({
  tree,
  property,
  contractLabel,
  onSelectProperty,
  onAddProperty,
  onOpenTestBench,
}: {
  tree: CustomerTree[];
  property: PropertyWithFeeds | null;
  contractLabel: string;
  onSelectProperty: (propertyId: string) => void;
  onAddProperty: () => void;
  onOpenTestBench: () => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, []);

  const allProps = tree.flatMap((c) =>
    c.properties.map((p) => ({ ...p, customerName: c.customer_name }))
  );

  return (
    <div className="setup-top">
      <div className="setup-crumb">
        <span>Data Airlock</span>
        <span className="sep">/</span>
        <span>Properties</span>
        <span className="sep">/</span>
        <div className="psw" ref={menuRef}>
          <button
            type="button"
            className="pswb"
            onClick={(e) => {
              e.stopPropagation();
              setOpen((v) => !v);
            }}
          >
            <span>{property?.property_name ?? "Select property"}</span>
            {property && <span className="code">{property.property_id}</span>}
            <ChevronDown />
          </button>
          <div className={`pswm ${open ? "on" : ""}`}>
            <div className="mk">Properties · {allProps.length}</div>
            {allProps.map((p) => (
              <button
                key={p.property_id}
                type="button"
                className={`pswi ${
                  p.property_id === property?.property_id ? "on" : ""
                }`}
                onClick={() => {
                  onSelectProperty(p.property_id);
                  setOpen(false);
                }}
              >
                <span className="pn2">
                  <b>{p.property_name}</b>
                  <i>
                    {p.customerName} · {p.property_feeds.length} feed
                    {p.property_feeds.length === 1 ? "" : "s"}
                  </i>
                </span>
                <span className="cd">{p.property_id}</span>
              </button>
            ))}
            <div className="psw-div" />
            <button
              type="button"
              className="pswi"
              onClick={() => {
                setOpen(false);
                onAddProperty();
              }}
            >
              <span className="pn2">
                <b style={{ color: "var(--setup-blue)" }}>+ Add property</b>
                <i>Onboard a new site</i>
              </span>
            </button>
          </div>
        </div>
        <button type="button" className="btn sm" onClick={onAddProperty}>
          <Plus strokeWidth={2.4} />
          Add property
        </button>
      </div>
      <div className="topR">
        <span
          className={`ver${
            contractLabel.includes("published") ? " published" : ""
          }`}
          data-testid="contract-status"
        >
          {contractLabel}
        </span>
        <button type="button" className="btn sm" onClick={onOpenTestBench}>
          <Play />
          Test bench
        </button>
      </div>
    </div>
  );
}

export function PropertyHeader({
  property,
  feed,
  customerName,
  onOpenTestBench,
  onSave,
  onExportYaml,
  saving,
}: {
  property: PropertyWithFeeds | null;
  feed: PropertyFeed | null;
  customerName: string;
  onOpenTestBench: () => void;
  onSave: () => void;
  onExportYaml: () => void;
  saving: boolean;
}) {
  const feedCrumb = feed
    ? `${categoryOf(feed.feed_category).name} contract`
    : "Feed contract";

  return (
    <div className="phead" data-testid="property-setup-header">
      <div className="phead-row">
        <div className="phead-left" style={{ minWidth: 0 }}>
          <div className="hier">
            <span className="cu">{customerName}</span>
            <span className="chev">›</span>
            <span className="cu">{property?.property_name ?? "Property"}</span>
            <span className="chev">›</span>
            <span>{feedCrumb}</span>
          </div>
          <h1>
            {property?.property_name ?? "No property selected"}
            {property && <span className="code">{property.property_id}</span>}
          </h1>
          <div className="hsub">
            <span>
              <em>Timezone</em>
              <b>{property?.timezone ?? "—"}</b>
            </span>
            <span className="dot" />
            <span>
              <em>Landing prefix</em>
              <span className="code" style={{ fontSize: 11 }}>
                {feed?.s3_prefix ?? property?.s3_prefix_pattern ?? "—"}
              </span>
            </span>
          </div>
        </div>
        <div className="hact phead-primary" data-testid="property-header-primary-actions">
          <button
            type="button"
            className="btn"
            disabled={!property || !feed}
            onClick={onExportYaml}
            data-testid="export-yaml-btn"
          >
            <Download />
            Export profile YAML
          </button>
          <button
            type="button"
            className="btn pri"
            disabled={!feed || saving}
            onClick={onSave}
            aria-busy={saving}
            data-testid="save-contract-btn"
          >
            {saving ? <span className="spin" aria-hidden /> : <Save />}
            {saving ? "Saving…" : "Save airlock contract"}
          </button>
        </div>
      </div>
      <div className="phead-tools" data-testid="property-header-secondary-actions">
        {property ? (
          <Link
            href={`/properties/${encodeURIComponent(property.property_id)}/journal`}
            className="btn"
            data-testid="journal-history-link"
          >
            <BookOpen />
            Journal &amp; History
          </Link>
        ) : null}
        <button type="button" className="btn" onClick={onOpenTestBench}>
          <Play />
          Test against live S3 file
        </button>
      </div>
    </div>
  );
}

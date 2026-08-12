"use client";

import { useMemo, useState } from "react";
import { X } from "lucide-react";
import type { CreatePropertyInput, Customer, FeedCategory } from "../types";
import {
  FEED_CATEGORIES,
  defaultPrefix,
  presetsForCategory,
} from "../presets";

const TIMEZONES = [
  "Europe/Madrid",
  "Europe/London",
  "Europe/Amsterdam",
  "America/New_York",
  "Asia/Dubai",
  "Australia/Sydney",
  "UTC",
];

export function AddPropertyDrawer({
  open,
  customers,
  onClose,
  onSubmit,
}: {
  open: boolean;
  customers: Customer[];
  onClose: () => void;
  onSubmit: (input: CreatePropertyInput) => Promise<void>;
}) {
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [customerId, setCustomerId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [propertyName, setPropertyName] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [timezone, setTimezone] = useState("Europe/Madrid");
  const [cat, setCat] = useState<FeedCategory>("pos");
  const [presetId, setPresetId] = useState("onesait");
  const [schedule, setSchedule] = useState("Daily");
  const [cutoff, setCutoff] = useState("07:00");
  const [overridePrefix, setOverridePrefix] = useState("");

  const presets = presetsForCategory(cat);
  const prefix = useMemo(
    () =>
      overridePrefix.trim() ||
      (propertyId ? defaultPrefix(propertyId, cat) : "—"),
    [overridePrefix, propertyId, cat]
  );

  const canStep1 =
    (customerId || customerName.trim().length >= 2) &&
    propertyName.trim().length >= 2 &&
    /^[A-Z0-9.]{3,20}$/.test(propertyId);

  const next = async () => {
    setError(null);
    if (step < 2) {
      setStep((s) => s + 1);
      return;
    }
    setBusy(true);
    try {
      const selected = customers.find((c) => c.id === customerId);
      await onSubmit({
        customerId: customerId || null,
        customerName: selected?.customer_name || customerName.trim(),
        customerCode: selected?.customer_code,
        propertyId: propertyId.trim().toUpperCase(),
        propertyName: propertyName.trim(),
        timezone,
        feedCategory: cat,
        presetId,
        schedule,
        slaCutoff: cutoff,
        s3Prefix: overridePrefix.trim() || undefined,
      });
      setStep(0);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create property");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className={`scrim ${open ? "on" : ""}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside
        className={`drw ${open ? "on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-hidden={!open}
      >
        <div className="dhd">
          <div>
            <div className="t">Add property</div>
            <div className="s">
              Three steps: who it belongs to, what it first delivers, and where
              that lands.
            </div>
          </div>
          <button type="button" className="x" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="dbd">
          <div className="steps">
            {["Basics", "First feed", "Prefix"].map((label, i) => (
              <span
                key={label}
                className={`stp ${i === step ? "on" : ""} ${
                  i < step ? "done" : ""
                }`}
              >
                <span className="sn">{i < step ? "✓" : i + 1}</span>
                <span className="sl">{label}</span>
                {i < 2 && <span className="bar2" />}
              </span>
            ))}
          </div>

          <div className={`step ${step === 0 ? "on" : ""}`}>
            <div className="f">
              <label>Existing customer</label>
              <select
                value={customerId}
                onChange={(e) => {
                  setCustomerId(e.target.value);
                  const c = customers.find((x) => x.id === e.target.value);
                  if (c) setCustomerName(c.customer_name);
                }}
              >
                <option value="">— create new —</option>
                {customers
                  .filter((c) => c.id !== "__unassigned__")
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.customer_name}
                    </option>
                  ))}
              </select>
            </div>
            {!customerId && (
              <div className="f">
                <label>Customer / brand</label>
                <input
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  placeholder="e.g. Minor Hotels"
                />
              </div>
            )}
            <div className="f">
              <label>Property name</label>
              <input
                value={propertyName}
                onChange={(e) => setPropertyName(e.target.value)}
                placeholder="e.g. NH Collection Sevilla"
              />
            </div>
            <div className="row two">
              <div className="f">
                <label>Property code</label>
                <input
                  className="mono"
                  value={propertyId}
                  onChange={(e) =>
                    setPropertyId(e.target.value.toUpperCase())
                  }
                  placeholder="SEVI.BARRA"
                />
              </div>
              <div className="f">
                <label>Local timezone</label>
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                >
                  {TIMEZONES.map((tz) => (
                    <option key={tz}>{tz}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className={`step ${step === 1 ? "on" : ""}`}>
            <div className="f">
              <label>First feed category</label>
              <div className="cats">
                {FEED_CATEGORIES.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    className={`cat ${cat === c.id ? "on" : ""}`}
                    onClick={() => {
                      setCat(c.id);
                      const first = presetsForCategory(c.id)[0];
                      if (first) setPresetId(first.id);
                    }}
                  >
                    {c.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="f">
              <label>System preset</label>
              <div className="presets">
                {presets.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`pchip ${presetId === p.id ? "on" : ""}`}
                    onClick={() => setPresetId(p.id)}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="row two">
              <div className="f">
                <label>Delivery schedule</label>
                <select
                  value={schedule}
                  onChange={(e) => setSchedule(e.target.value)}
                >
                  {["Daily", "Nightly", "Hourly", "Continuous"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div className="f">
                <label>Expected cutoff</label>
                <input
                  type="time"
                  value={cutoff}
                  onChange={(e) => setCutoff(e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className={`step ${step === 2 ? "on" : ""}`}>
            <div className="prev">
              <div className="pk2">Landing storage prefix</div>
              <div className="pv mono">{prefix}</div>
            </div>
            <div className="f">
              <label>Override prefix · optional</label>
              <input
                className="mono"
                value={overridePrefix}
                onChange={(e) => setOverridePrefix(e.target.value)}
                placeholder="leave blank to use the generated prefix"
              />
            </div>
            <div className="sum">
              <div>
                <b>{propertyName}</b> ({propertyId})
              </div>
              <div>
                {cat.toUpperCase()} · {presetId} · {schedule} @ {cutoff}
              </div>
            </div>
          </div>

          {error && <p className="err">{error}</p>}
        </div>
        <div className="dft">
          <button
            type="button"
            className="btn"
            style={{ visibility: step === 0 ? "hidden" : "visible" }}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
          >
            Back
          </button>
          <button
            type="button"
            className="btn pri"
            disabled={busy || (step === 0 && !canStep1)}
            onClick={() => void next()}
          >
            {step < 2 ? "Continue" : busy ? "Creating…" : "Create property"}
          </button>
        </div>
      </aside>
    </>
  );
}

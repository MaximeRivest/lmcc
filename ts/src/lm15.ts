/**
 * lmcc × lm15: typed convenience over a shared wire.
 *
 * The kernel already speaks lm15's canonical JSON (kernel §3). This module is
 * the thin typed face on top of `@lm15/lm15` (the kernel never imports it):
 * it uses lm15's own serde in both directions, so there is no translation and
 * nothing here can drift from what lm15 says a request or a response is. It
 * mirrors the Python bridge, `lmcc_lm15`.
 *
 * - `request(rendered, {model, config})` → an lm15 `Request`: the plan's
 *   request settings (what the adapter needs: `config.reasoning` for native
 *   thinking, `config.response_format` for a JSON reader, `tools` for a put)
 *   are the base; the caller's `Config` fills the rest. A caller value that
 *   contradicts the settings throws `ConfigConflict` unless `override`.
 * - `read`/`parse(plan, response)` → typed values from a `Response` or `Message`.
 * - `stream(plan, events)` → drive a plan's sans-I/O stream from lm15 stream events.
 * - `step(rendered, response)` → the turn with this reply recorded (§3a).
 */

import { Config, Delta, Message, Request, Response, type StreamEvent } from "@lm15/lm15";
import type { JsonObject } from "@lm15/lm15";
import type { Plan, Reading, RenderResult } from "./plan.ts";
import type { StreamEvent as LmccEvent, StreamResult } from "./stream.ts";
import type { Turn } from "./turn.ts";
import { isObj } from "./core.ts";
import { jsonEqual } from "./json.ts";

/** The caller's Config contradicts what the plan's request settings require. */
export class ConfigConflict extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigConflict";
  }
}

function merge(base: Record<string, unknown>, extra: Record<string, unknown>, path: string, override: boolean): Record<string, unknown> {
  const out: Record<string, unknown> = { ...base };
  for (const key of Object.keys(extra)) {
    const value = extra[key];
    const here = path ? `${path}.${key}` : key;
    if (key in out && isObj(out[key]) && isObj(value)) {
      out[key] = merge(out[key] as Record<string, unknown>, value, here, override);
    } else if (key in out && !jsonEqual(out[key], value) && !override) {
      throw new ConfigConflict(`${here}: the plan's request settings require ${JSON.stringify(out[key])} (a transport or reader asked for it) but the caller's Config says ${JSON.stringify(value)}; pass override: true to insist`);
    } else {
      out[key] = value;
    }
  }
  return out;
}

/** The lm15 `Request` for a rendered plan, with the caller's `Config` merged under the plan's settings. */
export function request(rendered: RenderResult, opts: { model: string; config?: Config; override?: boolean }): Request {
  const d = rendered.request(opts.model);
  if (opts.config !== undefined) {
    d["config"] = merge((d["config"] as Record<string, unknown>) ?? {}, Config.toJSON(opts.config) as Record<string, unknown>, "config", opts.override ?? false);
  }
  return Request.fromJSON(d as JsonObject);
}

function canonical(response: Response | Message): Record<string, unknown> {
  // by shape, not instanceof: a Response from another copy of lm15 is still a response
  return "message" in response ? Response.toJSON(response as Response) : Message.toJSON(response as Message);
}

/** Typed values and repairs (§4a) from an lm15 `Response` or `Message`; a cut response refuses `parse-truncated`. */
export function read<O>(plan: Plan<any, O>, response: Response | Message): Reading<O> {
  return plan.read(canonical(response));
}

/** Typed values from an lm15 `Response` or assistant `Message`. */
export function parse<O>(plan: Plan<any, O>, response: Response | Message): O {
  return read(plan, response).values;
}

/**
 * Feed lm15 stream events into `plan.stream()`: every delta as its canonical
 * JSON (§8 coalesces same-type text deltas). Returns all lmcc events in
 * order and the `StreamResult` from `finish`.
 */
export async function stream<O>(plan: Plan<any, O>, events: AsyncIterable<StreamEvent> | Iterable<StreamEvent>,
  onEvent?: (event: LmccEvent) => void): Promise<[LmccEvent[], StreamResult<O>]> {
  const s = plan.stream();
  const out: LmccEvent[] = [];
  let finishReason: string | null = null;
  const emit = (batch: LmccEvent[]) => {
    for (const e of batch) {
      out.push(e);
      onEvent?.(e);
    }
  };
  for await (const event of events as AsyncIterable<StreamEvent>) {
    if (event.type === "end") finishReason = event.finishReason ?? null;
    if (event.type === "error") throw new Error(`lm15 stream error: ${event.error.code}: ${event.error.message}`);
    if (event.type !== "delta") continue;
    emit(s.feed(Delta.toJSON(event.delta) as Record<string, unknown>));
  }
  const result = s.finish(finishReason);
  emit(result.events);
  return [out, result];
}

/** The rendered turn with this reply recorded as its next model step (§3a). */
export function step(rendered: RenderResult, response: Response | Message): Turn {
  return rendered.step(canonical(response));
}

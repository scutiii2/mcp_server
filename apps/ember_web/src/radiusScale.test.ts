/// <reference types="node" />
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/** Guards the corner-radius scale (`--radius-sm/md/lg/xl/full` in style.css): a
 * component takes its radius from a token, or from a `calc()` over one (a nested
 * corner is the outer radius minus the padding), never from a literal like `10px`
 * or `50%`. A literal `0` (a square corner, e.g. on an edge) is fine. */

export interface LiteralRadius {
  property: string;
  value: string;
}

/** Every `border-*radius` declaration in `source` whose value still has a literal length or percentage. */
export function findLiteralRadii(source: string): LiteralRadius[] {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/<!--[\s\S]*?-->/g, "");
  const found: LiteralRadius[] = [];
  const declaration = /(border(?:-[a-z]+){0,2}-radius)\s*:\s*([^;}"'\n]+)/g;
  for (const match of withoutComments.matchAll(declaration)) {
    const value = match[2]!.trim();
    // Take out each var(...) and calc(...) (calc may nest parentheses), then what is left must be 0s.
    if (stripFunctions(value).split(/\s+/).filter(Boolean).every((token) => token === "0")) continue;
    found.push({ property: match[1]!, value });
  }
  return found;
}

/** `value` without its `var(...)` and `calc(...)` calls, with balanced parentheses. */
function stripFunctions(value: string): string {
  let out = "";
  let depth = 0;
  for (let i = 0; i < value.length; i++) {
    const rest = value.slice(i);
    if (depth === 0 && /^(var|calc)\(/.test(rest)) {
      depth = 1;
      i += rest.indexOf("(");
      continue;
    }
    if (depth > 0) {
      if (value[i] === "(") depth++;
      else if (value[i] === ")") depth--;
      continue;
    }
    out += value[i];
  }
  return out;
}

describe("findLiteralRadii", () => {
  it("accepts tokens, calc over a token, and a literal 0", () => {
    const css = `
      .a { border-radius: var(--radius-md); }
      .b { border-radius: calc(var(--radius-lg) - 8px); }
      .c { border-radius: var(--radius-xl) var(--radius-xl) 0 0; }
      .d { border-radius: 0 var(--radius-md) var(--radius-md) 0; }
      .e { border-radius: calc(var(--radius-lg) - 1px) calc(var(--radius-lg) - 1px) 0 0; }
      .f { border-radius: 0; }
    `;

    expect(findLiteralRadii(css)).toEqual([]);
  });

  it("flags a literal length, a percentage, and a literal mixed in with tokens", () => {
    const css = `
      .a { border-radius: 10px; }
      .b { border-radius: 50%; }
      .c { border-radius: 999px; }
      .d { border-radius: var(--radius-xl) var(--radius-xl) 4px 4px; }
    `;

    expect(findLiteralRadii(css).map((r) => r.value)).toEqual([
      "10px",
      "50%",
      "999px",
      "var(--radius-xl) var(--radius-xl) 4px 4px",
    ]);
  });

  it("sees the longhand corner properties and inline one-line rules", () => {
    const css = `.x { border-top-left-radius: 6px; } .y { padding: 1px; border-radius: 8px; color: red; }`;

    expect(findLiteralRadii(css)).toEqual([
      { property: "border-top-left-radius", value: "6px" },
      { property: "border-radius", value: "8px" },
    ]);
  });

  it("ignores comments", () => {
    expect(findLiteralRadii("/* border-radius: 10px; */ <!-- border-radius: 3px --> .a { border-radius: var(--radius-sm); }")).toEqual([]);
  });
});

// The only literal radii left, on purpose: 10 to 11 px chart swatches and heatmap cells, where the 4 px
// `sm` step would round them into blobs. Adding a file here needs the same reason.
const ALLOWED_LITERALS: Record<string, string[]> = {
  "components/analytics/chart.css": ["2px"],
  "components/UsageHeatmap.vue": ["2px"],
  "views/WatchersView.vue": ["2px"],
};

/** Every `.vue` and `.css` file under `src/`, keyed by its path from `src/` (read from disk: Vitest
 * hands CSS imports back empty, even with `?raw`). */
function readStyleSources(): Record<string, string> {
  const root = dirname(fileURLToPath(import.meta.url));
  const sources: Record<string, string> = {};
  const walk = (dir: string): void => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (/\.(vue|css)$/.test(entry.name)) sources[relative(root, path).replaceAll("\\", "/")] = readFileSync(path, "utf-8");
    }
  };
  walk(root);
  return sources;
}

describe("the radius scale", () => {
  const sources = readStyleSources();

  it("scans the app's styles, CSS files included", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    expect(sources["style.css"]).toContain("--radius-md");
    expect(sources["components/UsageHeatmap.vue"]).toContain("border-radius");
  });

  it("uses a token in every component: no literal border radius outside the allowed marks", () => {
    const offenders: Record<string, string[]> = {};
    for (const [path, source] of Object.entries(sources)) {
      const literals = findLiteralRadii(source).map((r) => r.value);
      if (literals.length > 0) offenders[path] = literals;
    }

    // A failure lists each file and its literal values: swap them for a --radius-* token (see style.css).
    expect(offenders).toEqual(ALLOWED_LITERALS);
  });
});

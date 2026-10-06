import { apiRequest } from "./http";

export type GuiResultKind = "secret" | "message" | "table" | "fields";

export interface GuiResultSpec {
  kind: GuiResultKind;
  /** The result value to show (required for secret and table). */
  field?: string;
  /** A second result value shown below as plain text. */
  detail?: string;
  /** A numeric result field: seconds until the tool is run again. */
  refresh_after?: string;
}

export interface GuiFieldSpec {
  param: string;
  label?: string;
  order?: number;
  hidden?: boolean;
}

export interface GuiFormSectionSpec {
  type: "form";
  id: string;
  title: string;
  tool: string;
  submit: string;
  fields: GuiFieldSpec[];
  result: GuiResultSpec;
}

export interface GuiTextSectionSpec {
  type: "text";
  id: string;
  title?: string;
  text: string;
}

export interface GuiPageSpec {
  version: 1;
  title: string;
  description: string;
  sections: (GuiFormSectionSpec | GuiTextSectionSpec)[];
}

/** A capability's page layout, as mcp_server validated it (ember_api passes it through).
 * Typed as unknown: `parseGuiPage` checks it again before anything is drawn. */
export const capabilityPagesClient = {
  get: (name: string) => apiRequest<unknown>("GET", `/api/capabilities/${encodeURIComponent(name)}/gui`),
};

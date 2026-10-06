import { apiRequest } from "./http";

export type ConfigIssueSeverity = "error" | "warning";

export interface ConfigIssue {
  file: string;
  key: string;
  message: string;
  severity: ConfigIssueSeverity;
}

export const configIssuesClient = {
  list: () => apiRequest<ConfigIssue[]>("GET", "/api/config-issues"),
};
